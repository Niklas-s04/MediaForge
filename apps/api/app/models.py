from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON
from datetime import datetime


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str
    status: str = Field(default="queued")
    progress: int = Field(default=0)
    current_step: Optional[str] = None
    input: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class Flow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    steps: Optional[list] = Field(sa_column=Column(JSON), default=None)
    trigger: str = Field(default="manual")
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FileAsset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: Optional[int] = None
    role: Optional[str] = None
    path: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FlowRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    flow_id: int = Field(foreign_key="flow.id")
    status: str = Field(default="running")
    job_ids: Optional[list] = Field(sa_column=Column(JSON), default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


class AuditEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow)
    username: Optional[str] = None
    profile: Optional[str] = None
    lang: Optional[str] = None
    payload: Optional[dict] = Field(sa_column=Column(JSON), default=None)
