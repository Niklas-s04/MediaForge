from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from apps.api.app import main as api_main
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
                username="tester",
                session=session,
            )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Unsupported job type 'convert'"


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
            username="tester",
            session=session,
        )

    assert result.type == "convert"
    assert sent_jobs == [result.id]
    stored_files = list(upload_dir.glob("*"))
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == b"audio"
