from sqlmodel import SQLModel, create_engine, Session
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/db.sqlite3")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
