from sqlmodel import Session, create_engine, select
from apps.api.app.models import FlowRun
import os, datetime
DB=os.environ.get('DATABASE_URL','sqlite:////data/db.sqlite3')
connect_args = {"check_same_thread": False} if DB.startswith('sqlite') else {}
engine = create_engine(DB, connect_args=connect_args)
with Session(engine) as s:
    stmt = select(FlowRun).where(FlowRun.id==2)
    run = s.exec(stmt).first()
    print('before:', getattr(run,'id',None), getattr(run,'status',None), getattr(run,'finished_at',None))
    run.status = 'completed'
    run.finished_at = datetime.datetime.utcnow()
    s.add(run)
    s.commit()
    print('after:', run.id, run.status, run.finished_at)
