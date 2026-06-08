from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class JobCreate(BaseModel):
    type: str
    input: dict


class JobRead(BaseModel):
    id: int
    type: str
    status: str
    progress: int
    current_step: Optional[str]
    output_path: Optional[str]


class FlowCreate(BaseModel):
    name: str
    steps: List[dict]


class FlowRead(BaseModel):
    id: int
    name: str
    description: Optional[str]
    steps: Optional[List[dict]]
    trigger: str


class FlowRunCreate(BaseModel):
    flow_id: int


class FlowRunRead(BaseModel):
    id: int
    flow_id: int
    status: str
    job_ids: List[int]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
