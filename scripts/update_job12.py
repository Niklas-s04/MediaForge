from sqlmodel import Session, create_engine, select
from apps.api.app.models import Job
import os

DB=os.environ.get('DATABASE_URL','sqlite:////data/db.sqlite3')
connect_args = {"check_same_thread": False} if DB.startswith('sqlite') else {}
engine = create_engine(DB, connect_args=connect_args)
with Session(engine) as s:
    stmt = select(Job).where(Job.id==12)
    job = s.exec(stmt).first()
    print('before:', getattr(job,'id',None), getattr(job,'input',None), getattr(job,'status',None))
    job.input = {'url':'https://archive.org/download/testmp3testfile/mpthreetest.mp3'}
    job.status = 'queued'
    s.add(job)
    s.commit()
    print('after:', job.id, job.input, job.status)

# dispatch the job via celery broker
try:
    from apps.api.app.celery_app import celery_app
    celery_app.send_task('worker.process_download_and_convert', args=[12])
    print('dispatched task for job 12')
except Exception as e:
    print('failed to dispatch:', e)
