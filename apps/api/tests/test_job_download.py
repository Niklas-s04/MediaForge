from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from apps.api.app.main import download_job_output
from apps.api.app.models import Job


def create_test_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_download_job_output_returns_file_response(monkeypatch, tmp_path: Path):
    engine = create_test_engine()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_file = output_dir / "result.mp3"
    output_file.write_bytes(b"media")
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))

    with Session(engine) as session:
        job = Job(type="convert", status="success", output_path=str(output_file), input={})
        session.add(job)
        session.commit()
        session.refresh(job)

        response = download_job_output(job.id, session=session)

    assert response.path == str(output_file)
    assert response.filename == "result.mp3"


def test_download_job_output_rejects_unfinished_job(tmp_path: Path):
    engine = create_test_engine()

    with Session(engine) as session:
        job = Job(type="convert", status="running", input={})
        session.add(job)
        session.commit()
        session.refresh(job)

        with pytest.raises(HTTPException) as exc:
            download_job_output(job.id, session=session)

    assert exc.value.status_code == 409

