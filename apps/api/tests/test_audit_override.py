import os
import json
import tempfile

from apps.api.app.audit import audit_override


def test_audit_override_writes_jsonl(tmp_path):
    payload = {"type": "download", "input": {"url": "https://example.com/file.mp3"}}
    username = "tester"
    profile = "small"
    log_path = tmp_path / "override_audit.log"

    p = audit_override(payload=payload, username=username, profile=profile, lang='de', log_path=str(log_path))
    assert os.path.exists(p)
    # read lines
    with open(p, 'r', encoding='utf-8') as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry['username'] == username
    assert entry['profile'] == profile
    assert entry['payload']['type'] == 'download'


def test_create_audit_entry_in_db(tmp_path):
    from sqlmodel import create_engine, Session, SQLModel
    from apps.api.app import crud
    from apps.api.app.models import AuditEntry

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        e = crud.create_audit_entry(session, username='tester', profile='small', payload={'foo': 'bar'}, lang='de')
        assert e.id is not None
        rows = crud.list_audit_entries(session, limit=10)
        assert any(r.id == e.id for r in rows)
