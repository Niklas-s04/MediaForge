import subprocess
import sys

import pytest
from sqlmodel import SQLModel, Session, create_engine
from apps.api.app.models import Job
from apps.worker import worker


def test_silent_media_process_times_out_and_is_reaped(monkeypatch):
    monkeypatch.setenv('MEDIA_CONVERT_TIMEOUT_SECONDS', '1')
    monkeypatch.setattr(worker, '_probe_duration', lambda path: 1)
    monkeypatch.setattr(worker, '_validate_media_command_encoders', lambda cmd: None)
    monkeypatch.setattr(worker, '_set_job_progress', lambda *args, **kwargs: None)
    processes = []
    original = subprocess.Popen
    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(worker.subprocess, 'Popen', spawn)
    with pytest.raises(subprocess.TimeoutExpired):
        worker._run_ffmpeg_with_progress(
            [sys.executable, '-c', 'import time; time.sleep(3)', 'out'],
            session=None, job=None, input_path='in', start_progress=0, end_progress=100, step='test')
    assert all(p.poll() is not None for p in processes)


@pytest.mark.parametrize('task', [worker.process_convert, worker.process_download_and_convert])
def test_late_delivery_does_not_restart_failed_job(monkeypatch, tmp_path, task):
    engine = create_engine('sqlite:///' + str(tmp_path / 'test.sqlite'))
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        job = Job(type='convert', status='failed', error_message='job_dispatch_failed', input={})
        session.add(job)
        session.commit()
        job_id = job.id
    monkeypatch.setattr(worker, '_get_engine', lambda: engine)
    monkeypatch.setattr(worker, '_log', lambda *args: None)
    task.run(job_id)
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job.error_message == 'job_dispatch_failed'
        assert job.started_at is None
