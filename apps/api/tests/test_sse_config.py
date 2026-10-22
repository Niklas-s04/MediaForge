from starlette.requests import Request
from sqlmodel import SQLModel, Session, create_engine

from apps.api.app import main
from apps.api.app.main import get_log_dir, get_resume_offset
from apps.api.app.models import Flow, FlowRun, Job


def test_completed_job_drains_large_utf8_log_in_bounded_events(monkeypatch, tmp_path):
    import asyncio
    import json

    engine = create_test_engine(tmp_path)
    patch_session(monkeypatch, engine)
    monkeypatch.setenv("DATA_LOG_DIR", str(tmp_path))
    with Session(engine) as session:
        job = Job(type="convert", status="success", input={})
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id
    content = ("ä" * 40000 + "\n") * 3
    (tmp_path / f"job-{job_id}.log").write_bytes(content.encode("utf-8"))
    response = main.job_events(job_id, make_request([]))
    text = asyncio.run(collect_stream_text(response))
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert len(events) > 1
    assert all(len(event["chunk"].encode("utf-8")) <= 65536 for event in events)
    assert "".join(event["chunk"] for event in events) == content
    assert f"id: {len(content.encode('utf-8'))}" in text


def test_completed_run_drains_all_matching_log_lines(monkeypatch, tmp_path):
    import asyncio
    import json

    engine = create_test_engine(tmp_path)
    patch_session(monkeypatch, engine)
    monkeypatch.setenv("DATA_LOG_DIR", str(tmp_path))
    with Session(engine) as session:
        flow = Flow(name="large-log", steps=[])
        session.add(flow)
        session.commit()
        session.refresh(flow)
        run = FlowRun(flow_id=flow.id, status="completed", job_ids=[])
        session.add(run)
        session.commit()
        session.refresh(run)
        flow_id, run_id = flow.id, run.id
    lines = [f"(run {run_id}) line {i} " + "x" * 500 for i in range(400)]
    (tmp_path / f"flow-{flow_id}.log").write_text("\n".join(lines), encoding="utf-8")
    response = main.run_events(run_id, make_request([]))
    text = asyncio.run(collect_stream_text(response))
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert len(events) > 1
    assert [line for event in events for line in event["run_log"].splitlines()] == lines


def make_request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_run_events_preserves_long_line_continuations(monkeypatch, tmp_path):
    import asyncio
    import json

    engine = create_test_engine(tmp_path)
    patch_session(monkeypatch, engine)
    monkeypatch.setenv("DATA_LOG_DIR", str(tmp_path))
    with Session(engine) as session:
        flow = Flow(name="long-line", steps=[])
        session.add(flow)
        session.commit()
        session.refresh(flow)
        run = FlowRun(flow_id=flow.id, status="completed", job_ids=[])
        session.add(run)
        session.commit()
        session.refresh(run)
        flow_id, run_id = flow.id, run.id
    expected = f"(run {run_id}) " + "ä" * 70000 + "\n"
    content = expected + "(run 999999) unrelated\n"
    (tmp_path / f"flow-{flow_id}.log").write_bytes(content.encode("utf-8"))
    response = main.run_events(run_id, make_request([]))
    text = asyncio.run(collect_stream_text(response))
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert "".join(event["run_log"] for event in events) == expected
    assert all(len(event["run_log"].encode("utf-8")) <= 65536 for event in events)


def create_test_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sse.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def patch_session(monkeypatch, engine):
    def get_test_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(main, "get_session", get_test_session)


async def collect_stream_text(response):
    parts = []
    async for part in response.body_iterator:
        if isinstance(part, bytes):
            parts.append(part.decode("utf-8"))
        else:
            parts.append(part)
    return "".join(parts)


def test_data_log_dir_takes_precedence(monkeypatch, tmp_path):
    data_log_dir = tmp_path / "data-logs"
    legacy_log_dir = tmp_path / "legacy-logs"
    monkeypatch.setenv("DATA_LOG_DIR", str(data_log_dir))
    monkeypatch.setenv("LOG_DIR", str(legacy_log_dir))

    assert get_log_dir() == str(data_log_dir)


def test_log_dir_legacy_fallback(monkeypatch, tmp_path):
    legacy_log_dir = tmp_path / "legacy-logs"
    monkeypatch.delenv("DATA_LOG_DIR", raising=False)
    monkeypatch.setenv("LOG_DIR", str(legacy_log_dir))

    assert get_log_dir() == str(legacy_log_dir)


def test_resume_offset_reads_last_event_id():
    request = make_request([(b"last-event-id", b"42")])

    assert get_resume_offset(request) == 42


def test_resume_offset_defaults_to_zero_for_invalid_header():
    request = make_request([(b"last-event-id", b"not-a-number")])

    assert get_resume_offset(request) == 0


def test_job_events_uses_data_log_dir_and_resume_offset(monkeypatch, tmp_path):
    import asyncio

    engine = create_test_engine(tmp_path)
    patch_session(monkeypatch, engine)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))

    with Session(engine) as session:
        job = Job(type="download", status="success", progress=100, current_step="Fertig", input={})
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    (log_dir / f"job-{job_id}.log").write_text("hello resumed", encoding="utf-8")
    request = make_request([(b"last-event-id", b"6")])

    response = main.job_events(job_id, request=request)
    text = asyncio.run(collect_stream_text(response))

    assert "id: 13" in text
    assert '"status": "success"' in text
    assert '"progress": 100' in text
    assert '"current_step": "Fertig"' in text
    assert '"chunk": "resumed"' in text


def test_flow_events_uses_data_log_dir_and_resume_offset(monkeypatch, tmp_path):
    import asyncio

    engine = create_test_engine(tmp_path)
    patch_session(monkeypatch, engine)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))

    with Session(engine) as session:
        flow = Flow(name="sse-flow", steps=[])
        session.add(flow)
        session.commit()
        session.refresh(flow)
        flow_id = flow.id

    (log_dir / f"flow-{flow_id}.log").write_text("skip completed", encoding="utf-8")
    request = make_request([(b"last-event-id", b"5")])

    response = main.flow_events(flow_id, request=request)
    text = asyncio.run(collect_stream_text(response))

    assert "id: 14" in text
    assert '"status": "enabled"' in text
    assert '"chunk": "completed"' in text


def test_run_events_uses_data_log_dir_and_resume_offset(monkeypatch, tmp_path):
    import asyncio

    engine = create_test_engine(tmp_path)
    patch_session(monkeypatch, engine)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("DATA_LOG_DIR", str(log_dir))

    with Session(engine) as session:
        flow = Flow(name="sse-flow", steps=[])
        session.add(flow)
        session.commit()
        session.refresh(flow)
        run = FlowRun(flow_id=flow.id, status="completed", job_ids=[])
        session.add(run)
        session.commit()
        session.refresh(run)
        flow_id = flow.id
        run_id = run.id

    (log_dir / f"flow-{flow_id}.log").write_text(f"skip\n(run {run_id}) resumed", encoding="utf-8")
    request = make_request([(b"last-event-id", b"5")])

    response = main.run_events(run_id, request=request)
    text = asyncio.run(collect_stream_text(response))

    assert f"id: {len((log_dir / f'flow-{flow_id}.log').read_bytes())}" in text
    assert '"status": "completed"' in text
    assert f"(run {run_id}) resumed" in text

