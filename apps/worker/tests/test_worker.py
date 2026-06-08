from __future__ import annotations

import datetime
import os
import types
import sys
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

    def fake_run(cmd, check, stdout, stderr, timeout):
        tmpdir.mkdir(parents=True, exist_ok=True)
        downloaded.write_bytes(b"fake-audio")
        return None

    def fake_check_call(cmd, stdout, stderr):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"job-{job_id}.mp3").write_bytes(b"fake-mp3")
        return 0

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
