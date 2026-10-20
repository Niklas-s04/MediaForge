import gzip
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from apps.api.app.compression import normalize_compression
from apps.worker.compress import compress_file


@pytest.mark.parametrize("fmt", ["zip", "gz", "xz"])
def test_archives_roundtrip_exact_bytes(tmp_path, fmt):
    data = b"MediaForge test data\n" * 10000
    source = tmp_path / "data.txt"
    source.write_bytes(data)
    target = tmp_path / ("result." + fmt)
    options = normalize_compression(source.name, {"output_format": fmt, "level": 9})
    options["original_filename"] = "../data.txt"
    compress_file(str(source), str(target), options, lambda: pytest.fail("Unexpected media conversion"))
    if fmt == "zip":
        with zipfile.ZipFile(target) as archive:
            assert archive.namelist() == ["data.txt"]
            assert archive.read("data.txt") == data
    else:
        assert (gzip.decompress if fmt == "gz" else lzma.decompress)(target.read_bytes()) == data
    assert target.stat().st_size < source.stat().st_size


@pytest.mark.parametrize("fmt", ["docx", "xlsx", "pptx", "odt", "ods", "odp", "epub"])
def test_native_document_repack_preserves_all_entries(tmp_path, fmt):
    source, target = tmp_path / ("source." + fmt), tmp_path / ("out." + fmt)
    payload = {"mimetype": b"application/test", "content.xml": b"<document>data</document>" * 10000}
    with zipfile.ZipFile(source, "w") as archive:
        for name, content in payload.items():
            archive.writestr(name, content)
    options = normalize_compression(source.name, {"level": 9})
    compress_file(source, target, options, None)
    with zipfile.ZipFile(target) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == payload
        assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
    assert target.stat().st_size < source.stat().st_size


def test_repack_enforces_expansion_limit(monkeypatch, tmp_path):
    source = tmp_path / "large.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.xml", b"x" * 5000)
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "100")
    with pytest.raises(ValueError, match="Entpacklimit"):
        compress_file(source, tmp_path / "out.docx", normalize_compression(source.name, {}), None)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
@pytest.mark.parametrize("family,source_ext,fmt", [
    ("audio", "wav", "opus"), ("audio", "wav", "flac"), ("audio", "wav", "mp3"), ("audio", "wav", "m4a"),
    ("video", "mkv", "mp4"), ("video", "mkv", "webm"), ("video", "mkv", "mkv"),
    ("image", "bmp", "webp"), ("image", "bmp", "avif"), ("image", "bmp", "jpg"), ("image", "bmp", "png"),
])
def test_real_media_compression_is_decodable(tmp_path, family, source_ext, fmt):
    from apps.worker.worker import _build_media_command
    source, target = tmp_path / ("source." + source_ext), tmp_path / ("result." + fmt)
    if family == "audio":
        generator = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "pcm_s16le"]
    elif family == "video":
        generator = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12:duration=1", "-c:v", "ffv1"]
    else:
        generator = ["-f", "lavfi", "-i", "testsrc=size=320x240", "-frames:v", "1"]
    subprocess.run(["ffmpeg", "-y", "-v", "error", *generator, str(source)], check=True, capture_output=True, timeout=30)
    options = normalize_compression(source.name, {"output_format": fmt})
    def convert():
        subprocess.run(_build_media_command(str(source), str(target), family, fmt, "balanced", False, options), check=True, capture_output=True, timeout=60)
    compress_file(source, target, options, convert)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(target), "-f", "null", "-"], check=True, capture_output=True, timeout=30)
    assert target.stat().st_size > 0


@pytest.mark.skipif(not (shutil.which("gs") or shutil.which("gswin64c")), reason="Ghostscript unavailable")
def test_real_pdf_compression(tmp_path):
    from PIL import Image
    import pikepdf
    source, target = tmp_path / "source.pdf", tmp_path / "result.pdf"
    Image.new("RGB", (1800, 2400), "white").save(source, resolution=300)
    compress_file(str(source), str(target), normalize_compression(source.name, {"pdf_dpi": 72}), None)
    with pikepdf.open(target) as pdf:
        assert len(pdf.pages) == 1
    assert target.stat().st_size < source.stat().st_size


def test_http_upload_worker_download_roundtrip(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from sqlmodel import SQLModel, Session, create_engine
    from apps.api.app import main
    from apps.worker import worker
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for key, directory in [("DATA_UPLOAD_DIR", "uploads"), ("DATA_OUTPUT_DIR", "outputs"), ("DATA_LOG_DIR", "logs")]:
        monkeypatch.setenv(key, str(tmp_path / directory))
    monkeypatch.setattr(main, "scan_file", lambda path: None)
    monkeypatch.setattr(worker, "scan_file", lambda path: None)
    monkeypatch.setattr(worker, "_get_engine", lambda: engine)
    monkeypatch.setattr(main, "dispatch_job", lambda job: worker.process_convert.run(job.id))
    def session():
        with Session(engine) as db:
            yield db
    main.app.dependency_overrides[main.get_session] = session
    data = b"HTTP to worker to download\n" * 10000
    try:
        client = TestClient(main.app)
        response = client.post("/api/jobs/convert-batch", data={"operation": "compress", "settings": '[{"output_format":"gz"}]'}, files={"files": ("test.txt", data, "text/plain")})
        assert response.status_code == 200, response.text
        job_id = response.json()["jobs"][0]["id"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "success", job
        result = client.get(f"/api/jobs/{job_id}/download")
        assert result.status_code == 200
        assert gzip.decompress(result.content) == data
        assert not list((tmp_path / "uploads").iterdir())
        assert job["expires_at"]
        def fail_compression(source, target, options, media):
            Path(target).write_bytes(b"partial")
            raise RuntimeError("Invalid source")
        monkeypatch.setattr(worker, "compress_file", fail_compression)
        response = client.post("/api/jobs/convert-batch", data={"operation": "compress", "settings": '[{"output_format":"gz"}]'}, files={"files": ("bad.txt", data, "text/plain")})
        failed = client.get(f'/api/jobs/{response.json()["jobs"][0]["id"]}').json()
        assert failed["status"] == "failed"
        assert not list((tmp_path / "uploads").iterdir())
        assert not list((tmp_path / "outputs").glob("*.partial.*"))
    finally:
        main.app.dependency_overrides.pop(main.get_session, None)
