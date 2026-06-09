from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from apps.api.app import main as api_main
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


def test_download_job_output_rejects_expired_job():
    engine = create_test_engine()

    with Session(engine) as session:
        job = Job(type="convert", status="expired", input={})
        session.add(job)
        session.commit()
        session.refresh(job)

        with pytest.raises(HTTPException) as exc:
            download_job_output(job.id, session=session)

    assert exc.value.status_code == 410


def test_expire_old_job_outputs_deletes_file_and_hides_job(monkeypatch, tmp_path: Path):
    engine = create_test_engine()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_file = output_dir / "old.mp4"
    output_file.write_bytes(b"old-media")
    fresh_file = output_dir / "fresh.mp4"
    fresh_file.write_bytes(b"fresh-media")
    now = datetime.utcnow()
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("OUTPUT_RETENTION_HOURS", "24")

    with Session(engine) as session:
        old_job = Job(
            type="convert",
            status="success",
            output_path=str(output_file),
            input={},
            finished_at=now - timedelta(hours=25),
        )
        fresh_job = Job(
            type="convert",
            status="success",
            output_path=str(fresh_file),
            input={},
            finished_at=now - timedelta(hours=2),
        )
        session.add(old_job)
        session.add(fresh_job)
        session.commit()

        assert api_main.expire_old_job_outputs(session, now=now) == 1
        session.refresh(old_job)
        session.refresh(fresh_job)
        visible_jobs = api_main.list_jobs(session=session)
        all_jobs = api_main.list_jobs(session=session, include_expired=True)

    assert not output_file.exists()
    assert fresh_file.exists()
    assert old_job.status == "expired"
    assert old_job.output_path is None
    assert fresh_job.status == "success"
    assert [job.id for job in visible_jobs] == [fresh_job.id]
    assert {job.id for job in all_jobs} == {old_job.id, fresh_job.id}


def test_expire_old_job_outputs_skips_paths_outside_output_dir(monkeypatch, tmp_path: Path):
    engine = create_test_engine()
    output_dir = tmp_path / "output"
    outside_dir = tmp_path / "outside"
    output_dir.mkdir()
    outside_dir.mkdir()
    outside_file = outside_dir / "old.mp4"
    outside_file.write_bytes(b"do-not-touch")
    now = datetime.utcnow()
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))

    with Session(engine) as session:
        job = Job(
            type="convert",
            status="success",
            output_path=str(outside_file),
            input={},
            finished_at=now - timedelta(hours=25),
        )
        session.add(job)
        session.commit()

        assert api_main.expire_old_job_outputs(session, now=now) == 0
        session.refresh(job)

    assert outside_file.exists()
    assert job.status == "success"
    assert job.output_path == str(outside_file)


def test_media_options_include_added_common_formats():
    options = api_main.get_media_options()

    assert {"flv", "wmv", "ogv", "ts", "vob"}.issubset(set(options["convert"]["formats"]["video"]))
    assert {"alac", "wma", "oga"}.issubset(set(options["convert"]["formats"]["audio"]))
    assert "tif" in options["convert"]["formats"]["image"]
    assert "heic" not in options["convert"]["formats"]["image"]
    assert {"document", "spreadsheet", "presentation", "pdf", "text"}.issubset(set(options["convert"]["formats"]))
    assert {"docx", "pdf", "html"}.issubset(set(options["convert"]["formats"]["document"]))
    assert {"xlsx", "csv", "pdf"}.issubset(set(options["convert"]["formats"]["spreadsheet"]))
    assert {"pptx", "odp", "pdf"}.issubset(set(options["convert"]["formats"]["presentation"]))


def test_retention_column_migration_adds_missing_sqlite_columns(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "legacy.sqlite3"
    legacy_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE job (id INTEGER PRIMARY KEY, type VARCHAR NOT NULL, status VARCHAR NOT NULL)"
        )

    monkeypatch.setattr(api_main, "engine", legacy_engine)
    api_main.ensure_job_retention_columns()
    api_main.ensure_job_retention_columns()

    with legacy_engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(job)").fetchall()}

    assert {"expires_at", "deleted_at"}.issubset(columns)


def test_extend_job_output_adds_24_hours(monkeypatch, tmp_path: Path):
    engine = create_test_engine()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_file = output_dir / "result.pdf"
    output_file.write_bytes(b"pdf")
    now = datetime.utcnow()
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))

    with Session(engine) as session:
        job = Job(
            type="convert",
            status="success",
            output_path=str(output_file),
            input={},
            finished_at=now,
            expires_at=now + timedelta(hours=3),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        original_expiry = job.expires_at

        updated = api_main.extend_job_output(job.id, session=session)

    assert updated.expires_at == original_expiry + timedelta(hours=24)


def test_extend_job_output_rejects_unavailable_jobs():
    engine = create_test_engine()

    with Session(engine) as session:
        job = Job(type="convert", status="expired", input={})
        session.add(job)
        session.commit()
        session.refresh(job)

        with pytest.raises(HTTPException) as exc:
            api_main.extend_job_output(job.id, session=session)

    assert exc.value.status_code == 410


def test_delete_job_output_removes_file_and_hides_job(monkeypatch, tmp_path: Path):
    engine = create_test_engine()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_file = output_dir / "result.docx"
    output_file.write_bytes(b"docx")
    monkeypatch.setenv("DATA_OUTPUT_DIR", str(output_dir))

    with Session(engine) as session:
        job = Job(type="convert", status="success", output_path=str(output_file), input={})
        session.add(job)
        session.commit()
        session.refresh(job)

        deleted = api_main.delete_job_output(job.id, session=session)
        visible_jobs = api_main.list_jobs(session=session)
        all_jobs = api_main.list_jobs(session=session, include_expired=True)

    assert deleted.status == "deleted"
    assert not output_file.exists()
    assert visible_jobs == []
    assert all_jobs[0].status == "deleted"
