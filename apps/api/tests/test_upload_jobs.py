from io import BytesIO
from types import SimpleNamespace
import sys
import types

import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine, select

from apps.api.app import main as api_main
from apps.api.app.models import Job
from apps.api.app.schemas import JobCreate


def create_test_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def fake_upload(filename: str, content: bytes, content_type: str = "audio/wav"):
    return SimpleNamespace(
        filename=filename,
        file=BytesIO(content),
        content_type=content_type,
    )


def test_create_job_rejects_convert_type():
    engine = create_test_engine()

    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc:
            api_main.create_job(
                JobCreate(type="convert", input={}),
                session=session,
            )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unsupported job type 'convert'"


def test_create_download_job_normalizes_media_options(monkeypatch):
    engine = create_test_engine()
    sent_jobs = []
    monkeypatch.setattr(api_main, "dispatch_job", lambda job: sent_jobs.append(job.id))

    with Session(engine) as session:
        result = api_main.create_job(
            JobCreate(
                type="download",
                input={
                    "url": "https://example.invalid/video",
                    "output_kind": "video",
                    "output_format": "webm",
                    "download_quality": "720p",
                    "quality_preset": "high",
                    "strip_metadata": False,
                },
            ),
            force=True,
            session=session,
        )
        saved = session.exec(select(Job).where(Job.id == result.id)).first()

    assert result.type == "download"
    assert sent_jobs == [result.id]
    assert saved.input["output_kind"] == "video"
    assert saved.input["output_format"] == "webm"
    assert saved.input["download_quality"] == "720p"
    assert saved.input["quality_preset"] == "high"
    assert saved.input["compression_profile"] == "balanced"
    assert saved.input["strip_metadata"] is False


def test_create_download_job_rejects_invalid_format():
    engine = create_test_engine()

    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc:
            api_main.create_job(
                JobCreate(
                    type="download",
                    input={
                        "url": "https://example.invalid/video",
                        "output_kind": "video",
                        "output_format": "mp3",
                    },
                ),
                session=session,
            )

    assert exc.value.status_code == 400
    assert "Unsupported video download format" in exc.value.detail


def test_normalizers_accept_extended_output_formats():
    download = api_main.normalize_download_input(
        {
            "url": "https://example.invalid/video",
            "output_kind": "video",
            "output_format": "mov",
            "quality_preset": "balanced",
        }
    )
    assert download["output_format"] == "mov"

    image = api_main.normalize_convert_options(
        file=fake_upload("photo.tif", b"image", content_type="image/tiff"),
        compression_family="image",
        compression_profile="balanced",
        output_format="avif",
        quality_preset="balanced",
        strip_metadata=True,
    )
    assert image["source_family"] == "image"
    assert image["output_format"] == "avif"

    document = api_main.normalize_convert_options(
        file=fake_upload(
            "report.docx",
            b"doc",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        compression_family="pdf",
        compression_profile="balanced",
        output_format="pdf",
        quality_preset="balanced",
        strip_metadata=True,
    )
    assert document["source_family"] == "document"
    assert document["family"] == "pdf"
    assert document["output_format"] == "pdf"


def test_store_upload_file_removes_partial_file_when_too_large(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload = fake_upload("too-big.wav", b"abcdef")

    with pytest.raises(HTTPException) as exc:
        api_main.store_upload_file(upload, str(upload_dir), max_bytes=2)

    assert exc.value.status_code == 413
    assert list(upload_dir.glob("*")) == []


def test_create_convert_upload_job_stores_file_and_dispatches(monkeypatch, tmp_path):
    engine = create_test_engine()
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("DATA_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("AUDIT_OVERRIDE_LOG", str(tmp_path / "audit.log"))
    sent_jobs = []
    monkeypatch.setattr(api_main, "dispatch_job", lambda job: sent_jobs.append(job.id))

    with Session(engine) as session:
        result = api_main.create_convert_upload_job(
            file=fake_upload("sample.wav", b"audio"),
            preset="default",
            compression_family="audio",
            compression_profile="balanced",
            lang="de",
            force=True,
            session=session,
        )

    assert result.type == "convert"
    assert sent_jobs == [result.id]
    stored_files = list(upload_dir.glob("*"))
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == b"audio"


def test_convert_options_reject_image_to_video():
    with pytest.raises(HTTPException) as exc:
        api_main.normalize_convert_options(
            file=fake_upload("photo.jpg", b"image", content_type="image/jpeg"),
            compression_family="video",
            compression_profile="balanced",
            output_format="mp4",
            quality_preset="balanced",
            strip_metadata=True,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Cannot convert image to video"


def test_convert_options_allow_video_to_audio():
    result = api_main.normalize_convert_options(
        file=fake_upload("clip.mp4", b"video", content_type="video/mp4"),
        compression_family="audio",
        compression_profile="balanced",
        output_format="mp3",
        quality_preset="balanced",
        strip_metadata=True,
    )

    assert result["source_family"] == "video"
    assert result["family"] == "audio"
    assert result["output_format"] == "mp3"


def test_inspect_download_summarizes_yt_dlp_result(monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download):
            assert url == "https://example.invalid/video"
            assert download is False
            return {
                "title": "Sample Video",
                "uploader": "Example",
                "duration": 125,
                "thumbnail": "https://example.invalid/thumb.jpg",
                "formats": [
                    {"height": 720, "ext": "mp4", "fps": 30},
                    {"height": 1080, "ext": "webm", "fps": 60},
                    {"height": 720, "ext": "webm", "fps": 30},
                    {"ext": "m4a"},
                ],
            }

    fake_module = types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)

    result = api_main.inspect_download(
        api_main.DownloadInspectRequest(url=" https://example.invalid/video "),
    )

    assert result["title"] == "Sample Video"
    assert result["uploader"] == "Example"
    assert result["duration"] == 125
    assert result["formats"] == [
        {"height": 1080, "ext": "webm", "fps": 60},
        {"height": 720, "ext": "mp4", "fps": 30},
    ]

