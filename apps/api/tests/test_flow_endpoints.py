import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine

from apps.api.app.main import run_flow_endpoint


def create_test_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_run_missing_flow_returns_404():
    engine = create_test_engine()

    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc:
            run_flow_endpoint(999, username="tester", session=session)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Flow not found"
