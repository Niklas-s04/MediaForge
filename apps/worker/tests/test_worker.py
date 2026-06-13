from __future__ import annotations

import datetime
import os
import types
import sys
import zipfile
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select


WORKER_DIR = Path(__file__).resolve().parents[1]
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

if "yt_dlp" not in sys.modules:
    sys.modules["yt_dlp"] = types.ModuleType("yt_dlp")

import worker  # noqa: E402
from apps.api.app.models import Flow as ApiFlow, FlowRun as ApiFlowRun, Job as ApiJob  # noqa: E402


def create_test_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_worker_uses_shared_api_models():
    assert worker.Job is ApiJob
    assert worker.Flow is ApiFlow
    assert worker.FlowRun is ApiFlowRun


def test_process_download_and_convert_success(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    tmp_root = tmp_path / "tmp"
    output_dir = tmp_path / "output"
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATA_TMP_DIR", str(tmp_root))
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        job = worker.Job(type="download", input={"url": "https://example.invalid/audio.mp3", "preset": "default"})
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    tmpdir = tmp_root / f"job-{job_id}"
    downloaded = tmpdir / "audio.mp3"
    expected_output = str(output_dir / f"job-{job_id}.mp3")

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def download(self, urls):
            tmpdir.mkdir(parents=True, exist_ok=True)
            downloaded.write_bytes(b"fake-audio")
            for hook in self.options["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10, "speed": 1000, "eta": 1})
                hook({"status": "finished"})
            return 0

    def fake_run(cmd, check, stdout, stderr, timeout):
        return None

    def fake_check_call(cmd, stdout, stderr):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"job-{job_id}.mp3").write_bytes(b"fake-mp3")
        return 0

    monkeypatch.setattr(worker.yt_dlp, "YoutubeDL", FakeYoutubeDL, raising=False)
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(worker.glob, "glob", lambda pattern: [str(downloaded)])
    monkeypatch.setattr(worker.os.path, "getsize", lambda path: Path(path).stat().st_size)

    result = worker.process_download_and_convert(job_id)

    assert result == {"output": expected_output}
    with Session(engine) as session:
        saved = session.exec(select(worker.Job).where(worker.Job.id == job_id)).first()
        assert saved is not None
        assert saved.status == "success"
        assert saved.output_path == expected_output
        assert saved.finished_at is not None

    log_text = (log_dir / f"job-{job_id}.log").read_text(encoding="utf-8")
    assert "Starting download" in log_text
    assert "Conversion finished" in log_text


def test_process_download_and_convert_video_options(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    tmp_root = tmp_path / "tmp"
    output_dir = tmp_path / "output"
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATA_TMP_DIR", str(tmp_root))
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        job = worker.Job(
            type="download",
            input={
                "url": "https://example.invalid/video",
                "preset": "default",
                "output_kind": "video",
                "output_format": "webm",
                "download_quality": "720p",
                "quality_preset": "small",
            },
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    tmpdir = tmp_root / f"job-{job_id}"
    downloaded = tmpdir / "video.mp4"
    expected_output = output_dir / f"job-{job_id}.webm"
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            captured["ydl_options"] = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def download(self, urls):
            tmpdir.mkdir(parents=True, exist_ok=True)
            downloaded.write_bytes(b"fake-video")
            for hook in self.options["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes_estimate": 2})
                hook({"status": "finished"})
            return 0

    def fake_run(cmd, check, stdout, stderr, timeout):
        return None

    def fake_check_call(cmd, stdout, stderr):
        captured["ffmpeg_cmd"] = cmd
        output_dir.mkdir(parents=True, exist_ok=True)
        expected_output.write_bytes(b"fake-webm")
        return 0

    monkeypatch.setattr(worker.yt_dlp, "YoutubeDL", FakeYoutubeDL, raising=False)
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(worker.glob, "glob", lambda pattern: [str(downloaded)])
    monkeypatch.setattr(worker.os.path, "getsize", lambda path: Path(path).stat().st_size)

    result = worker.process_download_and_convert(job_id)

    assert result == {"output": str(expected_output)}
    assert "height<=720" in captured["ydl_options"]["format"]
    assert "-c:v" in captured["ffmpeg_cmd"]
    assert "libvpx-vp9" in captured["ffmpeg_cmd"]
    assert str(expected_output) == captured["ffmpeg_cmd"][-1]


def test_build_media_command_supports_extended_formats():
    ogg_cmd = worker._build_media_command("in.wav", "out.ogg", "audio", "ogg", "balanced", True, {})
    assert "libvorbis" in ogg_cmd

    oga_cmd = worker._build_media_command("in.wav", "out.oga", "audio", "oga", "balanced", True, {})
    assert "libvorbis" in oga_cmd

    alac_cmd = worker._build_media_command("in.wav", "out.alac", "audio", "alac", "balanced", True, {})
    assert "alac" in alac_cmd
    assert "ipod" in alac_cmd

    wma_cmd = worker._build_media_command("in.wav", "out.wma", "audio", "wma", "balanced", True, {})
    assert "wmav2" in wma_cmd

    weba_cmd = worker._build_media_command("in.wav", "out.weba", "audio", "weba", "balanced", True, {})
    assert "libopus" in weba_cmd

    mka_cmd = worker._build_media_command("in.wav", "out.mka", "audio", "mka", "balanced", True, {})
    assert "libopus" in mka_cmd

    avi_cmd = worker._build_media_command("in.mp4", "out.avi", "video", "avi", "balanced", True, {})
    assert "mpeg4" in avi_cmd
    assert "libmp3lame" in avi_cmd

    wmv_cmd = worker._build_media_command("in.mp4", "out.wmv", "video", "wmv", "balanced", True, {})
    assert "msmpeg4v3" in wmv_cmd
    assert "wmav2" in wmv_cmd

    ogv_cmd = worker._build_media_command("in.mp4", "out.ogv", "video", "ogv", "balanced", True, {})
    assert "libvpx" in ogv_cmd
    assert "libvorbis" in ogv_cmd

    ts_cmd = worker._build_media_command("in.mp4", "out.ts", "video", "ts", "balanced", True, {})
    assert "mpeg2video" in ts_cmd
    assert "mp2" in ts_cmd

    m2ts_cmd = worker._build_media_command("in.mp4", "out.m2ts", "video", "m2ts", "balanced", True, {})
    assert "mpeg2video" in m2ts_cmd
    assert "mp2" in m2ts_cmd

    gp3_cmd = worker._build_media_command("in.mp4", "out.3gp", "video", "3gp", "balanced", True, {})
    assert "mpeg4" in gp3_cmd
    assert "aac" in gp3_cmd

    avif_cmd = worker._build_media_command("in.png", "out.avif", "image", "avif", "balanced", True, {})
    assert "libaom-av1" in avif_cmd

    ico_cmd = worker._build_media_command("in.png", "out.ico", "image", "ico", "balanced", True, {})
    assert ico_cmd[-1] == "out.ico"
    assert "min(256,iw)" in " ".join(ico_cmd)

    jp2_cmd = worker._build_media_command("in.png", "out.jp2", "image", "jp2", "balanced", True, {})
    assert jp2_cmd[-1] == "out.jp2"

    tga_cmd = worker._build_media_command("in.png", "out.tga", "image", "tga", "balanced", True, {})
    assert tga_cmd[-1] == "out.tga"


def test_build_media_command_accepts_added_codec_options():
    av1_cmd = worker._build_media_command(
        "in.mp4",
        "out.mp4",
        "video",
        "mp4",
        "balanced",
        True,
        {"video_codec": "libaom-av1", "audio_codec": "alac"},
    )
    assert "libaom-av1" in av1_cmd
    assert "alac" in av1_cmd

    vp8_cmd = worker._build_media_command(
        "in.mp4",
        "out.webm",
        "video",
        "webm",
        "balanced",
        True,
        {"video_codec": "libvpx"},
    )
    assert "libvpx" in vp8_cmd
    assert "-b:v" in vp8_cmd

    wma_cmd = worker._build_media_command(
        "in.wav",
        "out.wma",
        "audio",
        "wma",
        "balanced",
        True,
        {"audio_codec": "wmav2"},
    )
    assert "wmav2" in wma_cmd


def test_run_document_conversion_uses_libreoffice(monkeypatch, tmp_path):
    input_file = tmp_path / "input.docx"
    input_file.write_bytes(b"docx")
    output_file = tmp_path / "out" / "result.pdf"
    captured = {}

    def fake_run(cmd, check, stdout, stderr, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        (outdir / "input.pdf").write_bytes(b"pdf")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setenv("DOCUMENT_CONVERT_TIMEOUT_SECONDS", "77")
    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    worker._run_document_conversion(str(input_file), str(output_file), "document", "pdf")

    assert output_file.read_bytes() == b"pdf"
    assert captured["cmd"][0] == "soffice"
    assert "--headless" in captured["cmd"]
    assert captured["timeout"] == 77


def test_run_document_conversion_extracts_pdf_text(monkeypatch, tmp_path):
    input_file = tmp_path / "input.pdf"
    input_file.write_bytes(b"pdf")
    output_file = tmp_path / "result.txt"
    captured = {}

    def fake_run(cmd, check, stdout, stderr, timeout):
        captured["cmd"] = cmd
        Path(cmd[-1]).write_text("extracted", encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    worker._run_document_conversion(str(input_file), str(output_file), "pdf", "txt")

    assert captured["cmd"][0] == "pdftotext"
    assert output_file.read_text(encoding="utf-8") == "extracted"


def test_run_document_conversion_copies_same_format(tmp_path):
    input_file = tmp_path / "input.pdf"
    input_file.write_bytes(b"pdf")
    output_file = tmp_path / "result.pdf"

    worker._run_document_conversion(str(input_file), str(output_file), "pdf", "pdf")

    assert output_file.read_bytes() == b"pdf"


def test_run_image_to_pdf_conversion_uses_img2pdf(monkeypatch, tmp_path):
    input_file = tmp_path / "photo.jpg"
    input_file.write_bytes(b"jpg")
    output_file = tmp_path / "out" / "photo.pdf"
    captured = {}

    def fake_convert(path):
        captured["path"] = path
        return b"pdf"

    fake_img2pdf = types.SimpleNamespace(convert=fake_convert)
    monkeypatch.setitem(sys.modules, "img2pdf", fake_img2pdf)

    worker._run_image_to_pdf_conversion(str(input_file), str(output_file))

    assert captured["path"] == str(input_file)
    assert output_file.read_bytes() == b"pdf"


def test_run_image_to_pdf_conversion_rasterizes_other_image_formats(monkeypatch, tmp_path):
    input_file = tmp_path / "photo.webp"
    input_file.write_bytes(b"webp")
    output_file = tmp_path / "out" / "photo.pdf"
    captured = {}

    def fake_check_call(cmd, stdout, stderr):
        captured["ffmpeg_cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"png")
        return 0

    def fake_convert(path):
        captured["img2pdf_path"] = path
        return b"pdf"

    monkeypatch.setattr(worker.subprocess, "check_call", fake_check_call)
    monkeypatch.setitem(sys.modules, "img2pdf", types.SimpleNamespace(convert=fake_convert))

    worker._run_image_to_pdf_conversion(str(input_file), str(output_file))

    assert captured["ffmpeg_cmd"][:4] == ["ffmpeg", "-y", "-i", str(input_file)]
    assert captured["img2pdf_path"].endswith("image.png")
    assert output_file.read_bytes() == b"pdf"


def test_run_image_vectorization_uses_vtracer(monkeypatch, tmp_path):
    input_file = tmp_path / "photo.png"
    input_file.write_bytes(b"png")
    output_file = tmp_path / "out" / "photo.svg"
    captured = {}

    def fake_convert(input_path, output_path):
        captured["input_path"] = input_path
        captured["output_path"] = output_path
        Path(output_path).write_text("<svg />", encoding="utf-8")

    monkeypatch.setitem(sys.modules, "vtracer", types.SimpleNamespace(convert_image_to_svg_py=fake_convert))

    worker._run_image_vectorization(str(input_file), str(output_file))

    assert captured == {"input_path": str(input_file), "output_path": str(output_file)}
    assert output_file.read_text(encoding="utf-8") == "<svg />"


def test_run_image_vectorization_rasterizes_non_jpg_png_inputs(monkeypatch, tmp_path):
    input_file = tmp_path / "photo.webp"
    input_file.write_bytes(b"webp")
    output_file = tmp_path / "out" / "photo.svg"
    captured = {}

    def fake_check_call(cmd, stdout, stderr):
        captured["ffmpeg_cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"png")
        return 0

    def fake_convert(input_path, output_path):
        captured["vtracer_input"] = input_path
        Path(output_path).write_text("<svg />", encoding="utf-8")

    monkeypatch.setattr(worker.subprocess, "check_call", fake_check_call)
    monkeypatch.setitem(sys.modules, "vtracer", types.SimpleNamespace(convert_image_to_svg_py=fake_convert))

    worker._run_image_vectorization(str(input_file), str(output_file))

    assert captured["ffmpeg_cmd"][:4] == ["ffmpeg", "-y", "-i", str(input_file)]
    assert captured["vtracer_input"].endswith("vector-source.png")
    assert output_file.read_text(encoding="utf-8") == "<svg />"


def test_run_svg_to_image_conversion_renders_before_media_command(monkeypatch, tmp_path):
    input_file = tmp_path / "icon.svg"
    input_file.write_text("<svg />", encoding="utf-8")
    output_file = tmp_path / "out" / "icon.png"
    captured = {}

    def fake_run(cmd, check, stdout, stderr, timeout):
        captured["rsvg_cmd"] = cmd
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"png")
        return types.SimpleNamespace(returncode=0)

    def fake_check_call(cmd, stdout, stderr):
        captured["ffmpeg_cmd"] = cmd
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(b"out")
        return 0

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(worker, "_validate_media_command_encoders", lambda cmd: None)

    worker._run_svg_to_image_conversion(str(input_file), str(output_file), "png", "balanced", True, {})

    assert captured["rsvg_cmd"][0] == "rsvg-convert"
    assert captured["ffmpeg_cmd"][:3] == ["ffmpeg", "-y", "-i"]
    assert output_file.read_bytes() == b"out"


def test_run_pdf_to_image_zip_creates_stable_jpg_entries(monkeypatch, tmp_path):
    input_file = tmp_path / "scan.pdf"
    input_file.write_bytes(b"pdf")
    output_file = tmp_path / "scan-jpg.zip"

    def fake_run(cmd, check, stdout, stderr, timeout):
        prefix = Path(cmd[-1])
        prefix.parent.mkdir(parents=True, exist_ok=True)
        (prefix.parent / f"{prefix.name}-1.jpg").write_bytes(b"page-1")
        (prefix.parent / f"{prefix.name}-2.jpg").write_bytes(b"page-2")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    worker._run_pdf_to_image_zip(str(input_file), str(output_file), "jpg", "balanced", True, {}, stem="scan")

    with zipfile.ZipFile(output_file) as archive:
        assert archive.namelist() == ["scan-page-001.jpg", "scan-page-002.jpg"]
        assert archive.read("scan-page-001.jpg") == b"page-1"


def test_run_pdf_to_image_zip_always_zips_single_page(monkeypatch, tmp_path):
    input_file = tmp_path / "one.pdf"
    input_file.write_bytes(b"pdf")
    output_file = tmp_path / "one-png.zip"

    def fake_run(cmd, check, stdout, stderr, timeout):
        prefix = Path(cmd[-1])
        prefix.parent.mkdir(parents=True, exist_ok=True)
        (prefix.parent / f"{prefix.name}-1.png").write_bytes(b"page-1")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    worker._run_pdf_to_image_zip(str(input_file), str(output_file), "png", "balanced", True, {}, stem="one")

    assert output_file.suffix == ".zip"
    with zipfile.ZipFile(output_file) as archive:
        assert archive.namelist() == ["one-page-001.png"]


def test_download_progress_hook_maps_known_and_unknown_totals():
    progress, step = worker._download_progress_from_hook(
        {"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 2048, "eta": 4},
        attempt=1,
        retries=3,
    )
    assert progress == 23
    assert "50 KB" in step or "1 KB" in step
    assert "verbleibend" in step

    unknown_progress, unknown_step = worker._download_progress_from_hook(
        {"status": "downloading", "downloaded_bytes": 4096},
        attempt=2,
        retries=3,
    )
    assert unknown_progress == 10
    assert "Groesse unbekannt" in unknown_step

    finished_progress, finished_step = worker._download_progress_from_hook({"status": "finished"}, attempt=1, retries=3)
    assert finished_progress == 38
    assert "abgeschlossen" in finished_step


def test_ffmpeg_progress_parser_handles_supported_and_bad_lines():
    assert worker._parse_ffmpeg_progress_seconds("out_time_ms=2500000") == 2.5
    assert worker._parse_ffmpeg_progress_seconds("out_time=01:02:03.50") == 3723.5
    assert worker._parse_ffmpeg_progress_seconds("out_time_ms=bad", current=7.0) == 7.0
    assert worker._parse_ffmpeg_progress_seconds("progress=end", current=9.0) == 9.0


def test_process_convert_success(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "output"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    input_file = upload_dir / "sample.wav"
    input_file.write_bytes(b"fake-audio")

    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATA_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        job = worker.Job(
            type="convert",
            input={
                "source": "upload",
                "file_path": str(input_file),
                "original_filename": "sample.wav",
                "mime_type": "audio/wav",
                "compression_profile": "balanced",
            },
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    expected_output = output_dir / f"job-{job_id}-sample.mp3"

    def fake_check_call(cmd, stdout, stderr):
        output_dir.mkdir(parents=True, exist_ok=True)
        expected_output.write_bytes(b"fake-mp3")
        return 0

    monkeypatch.setattr(worker.subprocess, "check_call", fake_check_call)

    result = worker.process_convert(job_id)

    assert result == {"output": str(expected_output)}
    assert not input_file.exists()
    with Session(engine) as session:
        saved = session.exec(select(worker.Job).where(worker.Job.id == job_id)).first()
        assert saved is not None
        assert saved.status == "success"
        assert saved.output_path == str(expected_output)
        assert saved.finished_at is not None

    log_text = (log_dir / f"job-{job_id}.log").read_text(encoding="utf-8")
    assert "Starting local conversion" in log_text
    assert "Conversion finished" in log_text


def test_process_convert_rejects_path_outside_upload_dir(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    outside_file = tmp_path / "outside.wav"
    outside_file.write_bytes(b"fake-audio")

    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATA_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        job = worker.Job(
            type="convert",
            input={
                "source": "upload",
                "file_path": str(outside_file),
                "original_filename": "outside.wav",
                "mime_type": "audio/wav",
                "compression_profile": "balanced",
            },
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    result = worker.process_convert(job_id)

    assert result is None
    assert outside_file.exists()
    with Session(engine) as session:
        saved = session.exec(select(worker.Job).where(worker.Job.id == job_id)).first()
        assert saved is not None
        assert saved.status == "failed"
        assert saved.error_message == "invalid_upload_source"


def test_process_convert_failure_cleans_uploaded_source(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "output"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    input_file = upload_dir / "broken.wav"
    input_file.write_bytes(b"fake-audio")

    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATA_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        job = worker.Job(
            type="convert",
            input={
                "source": "upload",
                "file_path": str(input_file),
                "original_filename": "broken.wav",
                "mime_type": "audio/wav",
                "compression_profile": "balanced",
            },
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    def fake_check_call(cmd, stdout, stderr):
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(worker.subprocess, "check_call", fake_check_call)

    result = worker.process_convert(job_id)

    assert result is None
    assert not input_file.exists()
    with Session(engine) as session:
        saved = session.exec(select(worker.Job).where(worker.Job.id == job_id)).first()
        assert saved is not None
        assert saved.status == "failed"
        assert "ffmpeg failed" in saved.error_message


def test_run_flow_creates_job_and_completes(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        flow = worker.Flow(
            name="smoke-flow",
            description="test",
            steps=[{"action": "download", "input": {"url": "https://example.invalid/file.mp3", "preset": "default"}}],
        )
        session.add(flow)
        session.commit()
        session.refresh(flow)
        flow_id = flow.id

    sent_tasks = []

    def fake_send_task(task_name, args=None, kwargs=None):
        sent_tasks.append((task_name, args, kwargs))
        job_id = args[0]
        with Session(engine) as session:
            job = session.exec(select(worker.Job).where(worker.Job.id == job_id)).first()
            assert job is not None
            job.status = "success"
            job.output_path = f"/data/output/job-{job_id}.mp3"
            job.finished_at = datetime.datetime.utcnow()
            session.add(job)
            session.commit()
        return {"task_id": "fake-task"}

    monkeypatch.setattr(worker.celery_app, "send_task", fake_send_task)
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: None)

    result = worker.run_flow(flow_id)

    assert result == {"flow": flow_id, "run": 1, "status": "completed"}
    assert sent_tasks == [("worker.process_download_and_convert", [1], None)]

    with Session(engine) as session:
        run = session.exec(select(worker.FlowRun).where(worker.FlowRun.flow_id == flow_id)).first()
        assert run is not None
        assert run.status == "completed"
        assert run.job_ids == [1]

        job = session.exec(select(worker.Job).where(worker.Job.id == 1)).first()
        assert job is not None
        assert job.status == "success"
        assert job.created_at is not None

    flow_log = (log_dir / f"flow-{flow_id}.log").read_text(encoding="utf-8")
    assert "Starting flow" in flow_log
    assert "Flow 1 completed" in flow_log


def test_run_flow_marks_failed_when_job_fails(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        flow = worker.Flow(
            name="failing-flow",
            steps=[{"action": "download", "input": {"url": "https://example.invalid/file.mp3"}}],
        )
        session.add(flow)
        session.commit()
        session.refresh(flow)
        flow_id = flow.id

    def fake_send_task(task_name, args=None, kwargs=None):
        job_id = args[0]
        with Session(engine) as session:
            job = session.exec(select(worker.Job).where(worker.Job.id == job_id)).first()
            assert job is not None
            job.status = "failed"
            job.error_message = "download_failed"
            job.finished_at = datetime.datetime.utcnow()
            session.add(job)
            session.commit()
        return {"task_id": "fake-task"}

    monkeypatch.setattr(worker.celery_app, "send_task", fake_send_task)
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: None)

    result = worker.run_flow(flow_id)

    assert result == {"flow": flow_id, "run": 1, "status": "failed"}
    with Session(engine) as session:
        run = session.exec(select(worker.FlowRun).where(worker.FlowRun.flow_id == flow_id)).first()
        assert run is not None
        assert run.status == "failed"


def test_run_flow_marks_failed_on_timeout(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        flow = worker.Flow(
            name="timeout-flow",
            steps=[{"action": "download", "timeout": 0, "input": {"url": "https://example.invalid/file.mp3"}}],
        )
        session.add(flow)
        session.commit()
        session.refresh(flow)
        flow_id = flow.id

    monkeypatch.setattr(worker.celery_app, "send_task", lambda *args, **kwargs: {"task_id": "fake-task"})
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: None)

    result = worker.run_flow(flow_id)

    assert result == {"flow": flow_id, "run": 1, "status": "failed"}
    with Session(engine) as session:
        run = session.exec(select(worker.FlowRun).where(worker.FlowRun.flow_id == flow_id)).first()
        job = session.exec(select(worker.Job).where(worker.Job.id == 1)).first()
        assert run is not None
        assert run.status == "failed"
        assert job is not None
        assert job.status == "failed"
        assert job.error_message == "flow_step_timeout"


def test_run_flow_marks_failed_on_unknown_action(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)

    with Session(engine) as session:
        flow = worker.Flow(name="bad-flow", steps=[{"action": "mystery", "input": {}}])
        session.add(flow)
        session.commit()
        session.refresh(flow)
        flow_id = flow.id

    result = worker.run_flow(flow_id)

    assert result == {"flow": flow_id, "run": 1, "status": "failed"}
    with Session(engine) as session:
        run = session.exec(select(worker.FlowRun).where(worker.FlowRun.flow_id == flow_id)).first()
        job = session.exec(select(worker.Job).where(worker.Job.id == 1)).first()
        assert run is not None
        assert run.status == "failed"
        assert job is not None
        assert job.status == "failed"
        assert job.error_message == "unknown_action:mystery"
