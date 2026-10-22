from __future__ import annotations

import datetime
import os
import types
import sys
import zipfile
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select


WORKER_DIR = Path(__file__).resolve().parents[1]
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

if "yt_dlp" not in sys.modules:
    sys.modules["yt_dlp"] = types.ModuleType("yt_dlp")

import worker  # noqa: E402
from apps.api.app.models import Flow as ApiFlow, FlowRun as ApiFlowRun, Job as ApiJob  # noqa: E402


@pytest.fixture(autouse=True)
def clean_malware_scan(monkeypatch):
    monkeypatch.setattr(worker, "scan_file", lambda path: None)
    monkeypatch.setattr(worker, "validate_remote_url", lambda url, resolve: str(url).strip())


def create_test_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_worker_uses_shared_api_models():
    assert worker.Job is ApiJob
    assert worker.Flow is ApiFlow
    assert worker.FlowRun is ApiFlowRun


def test_scan_job_file_blocks_and_removes_detected_input(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    source = tmp_path / "detected.bin"
    source.write_bytes(b"payload")
    monkeypatch.setenv("DATA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(
        worker,
        "scan_file",
        lambda path: (_ for _ in ()).throw(worker.MalwareDetectedError("Test.Signature")),
    )

    with Session(engine) as session:
        job = worker.Job(type="convert", status="running", input={})
        session.add(job)
        session.commit()
        session.refresh(job)

        assert worker._scan_job_file(session, job, str(source), "test input") is False
        session.refresh(job)

        assert job.status == "failed"
        assert job.error_message == "malware_detected"
        assert job.finished_at is not None
        assert not source.exists()


def test_remote_download_size_limit_removes_partial_file(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    download_dir = tmp_path / "download"
    download_dir.mkdir()
    partial = download_dir / "partial.bin"
    monkeypatch.setenv("REMOTE_DOWNLOAD_MAX_BYTES", "4")

    class OversizedYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def download(self, urls):
            partial.write_bytes(b"12345")
            self.options["progress_hooks"][0](
                {"status": "downloading", "downloaded_bytes": 5, "total_bytes": 5}
            )

    monkeypatch.setattr(sys.modules["yt_dlp"], "YoutubeDL", OversizedYoutubeDL, raising=False)

    with Session(engine) as session:
        job = worker.Job(type="download", status="running", input={})
        session.add(job)
        session.commit()
        session.refresh(job)

        with pytest.raises(worker.RemoteDownloadTooLargeError):
            worker._download_with_ytdlp(
                session=session,
                job=job,
                job_id=job.id,
                input_url="https://example.com/media",
                fmt="best",
                outtmpl=str(download_dir / "%(id)s.%(ext)s"),
                attempt=1,
                retries=1,
                download_timeout=10,
            )

    assert not partial.exists()


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
    expected_output = str(output_dir / "audio.mp3")

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
        Path(cmd[-1]).write_bytes(b"fake-mp3")
        return 0

    monkeypatch.setattr(sys.modules["yt_dlp"], "YoutubeDL", FakeYoutubeDL, raising=False)
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
    assert "Starting remote download" in log_text
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
    expected_output = output_dir / "video.webm"
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
        Path(cmd[-1]).write_bytes(b"fake-webm")
        return 0

    monkeypatch.setattr(sys.modules["yt_dlp"], "YoutubeDL", FakeYoutubeDL, raising=False)
    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    monkeypatch.setattr(worker.subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(worker.glob, "glob", lambda pattern: [str(downloaded)])
    monkeypatch.setattr(worker.os.path, "getsize", lambda path: Path(path).stat().st_size)

    result = worker.process_download_and_convert(job_id)

    assert result == {"output": str(expected_output)}
    assert "height<=720" in captured["ydl_options"]["format"]
    assert "-c:v" in captured["ffmpeg_cmd"]
    assert "libvpx-vp9" in captured["ffmpeg_cmd"]
    assert captured["ffmpeg_cmd"][-1].endswith(f".mediaforge-job-{job_id}.partial.webm")


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


def test_build_media_command_preserves_or_removes_metadata_explicitly():
    preserve_cmd = worker._build_media_command(
        "input.flac", "output.mp3", "audio", "mp3", "balanced", False, {}
    )
    strip_cmd = worker._build_media_command(
        "input.flac", "output.mp3", "audio", "mp3", "balanced", True, {}
    )

    assert preserve_cmd[preserve_cmd.index("-map_metadata") + 1] == "0"
    assert strip_cmd[strip_cmd.index("-map_metadata") + 1] == "-1"


def test_publish_output_uses_original_stem_and_collision_suffix(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "Urlaub.mp3").write_bytes(b"existing")
    partial = output_dir / ".mediaforge-job-7.partial.mp3"
    partial.write_bytes(b"new")

    result = worker._publish_output(str(partial), str(output_dir), "Urlaub", "mp3")

    assert result == str(output_dir / "Urlaub (2).mp3")
    assert Path(result).read_bytes() == b"new"
    assert not partial.exists()


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

    def fake_convert(path, *, outputstream):
        captured["path"] = path
        outputstream.write(b"pdf")

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

    def fake_convert(path, *, outputstream):
        captured["img2pdf_path"] = path
        outputstream.write(b"pdf")

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


def test_ffmpeg_child_is_reaped_when_progress_is_interrupted(monkeypatch):
    from celery.exceptions import SoftTimeLimitExceeded
    processes = []
    original_popen = worker.subprocess.Popen
    def spawn(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        processes.append(child)
        return child
    calls = 0
    def progress(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SoftTimeLimitExceeded()
    monkeypatch.setattr(worker.subprocess, "Popen", spawn)
    monkeypatch.setattr(worker, "_probe_duration", lambda _: 10)
    monkeypatch.setattr(worker, "_validate_media_command_encoders", lambda _: None)
    monkeypatch.setattr(worker, "_set_job_progress", progress)
    command = [sys.executable, "-c", "import time; print('out_time_us=1000000', flush=True); time.sleep(60)", "output"]
    try:
        with pytest.raises(SoftTimeLimitExceeded):
            worker._run_ffmpeg_with_progress(command, session=None, job=None, input_path="input",
                                            start_progress=0, end_progress=90, step="convert")
        assert processes[0].poll() is not None
        assert processes[0].stdout.closed
    finally:
        for child in processes:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()


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

    expected_output = output_dir / "sample.mp3"

    def fake_check_call(cmd, stdout, stderr):
        output_dir.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"fake-mp3")
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


@pytest.fixture
def flow_db(monkeypatch, tmp_path):
    engine = create_test_engine(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'worker.db'}")
    monkeypatch.setenv("DATA_LOG_DIR", str(tmp_path / "logs"))
    yield engine
    engine.dispose()


def add_flow(engine, steps):
    with Session(engine) as session:
        flow = worker.Flow(name="test", steps=steps)
        session.add(flow)
        session.commit()
        session.refresh(flow)
        return flow.id


def test_two_flows_complete_with_one_execution_slot(monkeypatch, flow_db):
    queue = []
    monkeypatch.setattr(worker.celery_app, "send_task", lambda *a, **k: pytest.fail("Flow must return its slot before the download executes"))
    monkeypatch.setattr(worker.process_download_and_convert, "apply_async",
                        lambda args, **options: queue.append((args[0], options)))
    monkeypatch.setattr(worker.time, "sleep", lambda _: pytest.fail("Flow must not wait for a worker slot"))
    steps = [{"action": "download", "timeout": 12, "input": {"url": "https://example.com/a"}}] * 2
    ids = [add_flow(flow_db, steps), add_flow(flow_db, steps)]
    for flow_id in ids:
        assert worker.run_flow(flow_id)["status"] == "running"
    assert len(queue) == 2
    completed = []
    while queue:
        job_id, options = queue.pop(0)
        assert options["soft_time_limit"] == 12
        assert options["time_limit"] > 12
        with Session(flow_db) as session:
            job = session.get(worker.Job, job_id)
            job.status = "success"
            session.add(job)
            session.commit()
        callback = options["link"]
        assert callback.immutable
        callback()
        # Repeated delivery must not create another next-step job.
        callback()
        completed.append(job_id)
    with Session(flow_db) as session:
        runs = session.exec(select(worker.FlowRun)).all()
        assert [run.status for run in runs] == ["completed", "completed"]
        assert all(len(run.job_ids) == 2 for run in runs)
        assert len(completed) == 4


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_flow_observes_step_failure_and_cancellation(monkeypatch, flow_db, status):
    queued = []
    monkeypatch.setattr(worker.process_download_and_convert, "apply_async",
                        lambda args, **options: queued.append((args[0], options)))
    flow_id = add_flow(flow_db, [{"action": "download", "input": {}}])
    worker.run_flow(flow_id)
    job_id, options = queued.pop()
    with Session(flow_db) as session:
        job = session.get(worker.Job, job_id)
        job.status = status
        session.add(job)
        session.commit()
    assert options["link"]()["status"] == "failed"
    with Session(flow_db) as session:
        assert session.get(worker.Job, job_id).status == status


@pytest.mark.parametrize("step,error", [
    ({"action": "download", "timeout": 0}, "flow_step_timeout"),
    ({"action": "download", "timeout": "bad"}, "flow_step_timeout"),
    ({"action": "download", "timeout": "NaN"}, "flow_step_timeout"),
    ({"action": "mystery"}, "unknown_action:mystery"),
])
def test_flow_rejects_invalid_step(flow_db, step, error):
    flow_id = add_flow(flow_db, [step])
    assert worker.run_flow(flow_id)["status"] == "failed"
    with Session(flow_db) as session:
        job = session.exec(select(worker.Job)).one()
        assert job.status == "failed"
        assert job.error_message == error


def test_hard_timeout_errback_works_without_result_backend(monkeypatch, flow_db):
    from celery.exceptions import TimeLimitExceeded
    from celery.app.task import Context
    queued = []
    monkeypatch.setattr(worker.process_download_and_convert, "apply_async",
                        lambda args, **options: queued.append((args[0], options)))
    monkeypatch.setattr(worker.run_flow, "apply_async", lambda args, **kw: worker.run_flow(*args))
    flow_id = add_flow(flow_db, [{"action": "download", "timeout": 1}])
    worker.run_flow(flow_id)
    job_id, options = queued.pop()
    request = Context(id="timed-out", errbacks=[options["link_error"]], chain=None)
    worker.celery_app.backend.mark_as_failure("timed-out", TimeLimitExceeded(1), request=request, store_result=False)
    with Session(flow_db) as session:
        job = session.get(worker.Job, job_id)
        assert job.status == "failed"
        assert job.error_message == "flow_step_timeout"
        assert session.exec(select(worker.FlowRun)).one().status == "failed"
    assert worker.celery_app.conf.result_backend is None
    assert worker.celery_app.conf.task_ignore_result is True
