from io import BytesIO
from types import SimpleNamespace
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

from apps.api.app import crud, main
from apps.api.app.models import Job


@pytest.fixture
def session():
    engine = create_engine('sqlite:///:memory:')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_broker_failure_marks_upload_failed_and_removes_source(monkeypatch, tmp_path, session):
    monkeypatch.setenv('DATA_UPLOAD_DIR', str(tmp_path))
    monkeypatch.setattr(main, 'scan_file', lambda path: None)
    monkeypatch.setattr(main, 'validate_compression_warning', lambda **kw: None)
    def fail(job):
        raise ConnectionError('broker offline')
    monkeypatch.setattr(main, 'dispatch_job', fail)
    upload = SimpleNamespace(filename='test.wav', file=BytesIO(b'audio'), content_type='audio/wav')
    with pytest.raises(HTTPException) as error:
        main.create_convert_upload_job(file=upload, preset='default', compression_family='audio',
                                       compression_profile='balanced', lang='de', force=True, session=session)
    assert error.value.status_code == 503
    job = session.exec(select(Job)).one()
    assert job.status == 'failed'
    assert job.error_message == 'job_dispatch_failed'
    assert job.finished_at is not None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('endpoint', ['/api/jobs', '/api/audit', '/api/flows/1/runs'])
@pytest.mark.parametrize('limit', [-1, 0, 501])
def test_list_limits_rejected_before_database_access(endpoint, limit):
    client = TestClient(main.app, raise_server_exceptions=False)
    assert client.get(endpoint, params={'limit': limit}).status_code == 422


def test_internal_limits_do_not_allow_unbounded_sql(session):
    for i in range(3):
        crud.create_job(session, 'convert', {})
    assert len(crud.list_jobs(session, limit=-1)) == 1


def test_log_tail_bounds_bytes_even_for_single_huge_line(monkeypatch, tmp_path):
    monkeypatch.setenv('DATA_LOG_DIR', str(tmp_path))
    (tmp_path / 'job-1.log').write_bytes(b'x' * 200000 + b'\nlast\n')
    result = crud.read_job_log(1)
    assert result.endswith('\nlast\n')
    assert len(result.encode()) <= 65536


def test_archive_uses_private_temp_not_output(monkeypatch, tmp_path, session):
    import tempfile
    output = tmp_path / 'output'
    scratch = tmp_path / 'scratch'
    output.mkdir()
    scratch.mkdir()
    source = output / 'sample.mp3'
    source.write_bytes(b'audio')
    monkeypatch.setenv('DATA_OUTPUT_DIR', str(output))
    monkeypatch.setattr(tempfile, 'tempdir', str(scratch))
    monkeypatch.setattr(main, 'scan_file', lambda path: None)
    job = Job(type='convert', status='success', output_path=str(source), input={})
    session.add(job)
    session.commit()
    response = main.download_history_output(session=session)
    try:
        assert os.path.commonpath([str(scratch), response.path]) == str(scratch)
    finally:
        os.remove(response.path)


def test_dispatch_error_after_worker_claim_preserves_active_upload(monkeypatch, tmp_path, session):
    path = tmp_path / 'input.wav'
    path.write_bytes(b'audio')
    monkeypatch.setenv('DATA_UPLOAD_DIR', str(tmp_path))
    job = crud.create_job(session, 'convert', {'source': 'upload', 'file_path': str(path)})
    def delivered_then_error(job):
        job.status = 'running'
        session.add(job)
        session.commit()
        raise ConnectionError('confirmation lost')
    monkeypatch.setattr(main, 'dispatch_job', delivered_then_error)
    assert main.dispatch_or_fail(session, job)
    assert path.exists()
    assert job.status == 'running'


def test_archive_budget_rejected_before_creating_zip(monkeypatch, tmp_path, session):
    monkeypatch.setenv('DATA_OUTPUT_DIR', str(tmp_path))
    monkeypatch.setenv('MALWARE_SCAN_MAX_BYTES', '1024')
    monkeypatch.setattr(main, 'scan_file', lambda path: None)
    source = tmp_path / 'large.mp3'
    source.write_bytes(b'x' * 2048)
    session.add(Job(type='convert', status='success', output_path=str(source), input={}))
    session.commit()
    with pytest.raises(HTTPException) as error:
        main.download_history_output(session=session)
    assert error.value.status_code == 413
