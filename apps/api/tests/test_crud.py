from sqlmodel import SQLModel, create_engine, Session
from apps.api.app.models import User, Job
from apps.api.app import crud


def create_test_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def test_create_and_get_user():
    engine = create_test_engine()
    with Session(engine) as session:
        user = crud.create_user(session, 'testuser', 'hashedpw', is_admin=False)
        assert user.username == 'testuser'
        fetched = crud.get_user_by_username(session, 'testuser')
        assert fetched is not None
        assert fetched.username == 'testuser'


def test_create_job_and_update_status():
    engine = create_test_engine()
    with Session(engine) as session:
        job = crud.create_job(session, 'convert', {'input_path': '/tmp/a.mp3'})
        assert job.id is not None
        assert job.status == 'queued'
        job2 = crud.update_job_status(session, job, 'running', progress=10)
        assert job2.status == 'running'
        assert job2.progress == 10
