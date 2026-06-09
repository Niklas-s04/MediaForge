from sqlmodel import select
from .models import Job, Flow, FlowRun


def create_job(session, job_type: str, input_obj: dict) -> Job:
    job = Job(type=job_type, input=input_obj)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job(session, job_id: int) -> Job | None:
    statement = select(Job).where(Job.id == job_id)
    result = session.exec(statement).first()
    return result


def list_jobs(session, limit: int = 50, include_expired: bool = False):
    statement = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if not include_expired:
        statement = (
            select(Job)
            .where(Job.status.notin_(["expired", "deleted"]))
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
    return session.exec(statement).all()


def update_job_status(session, job: Job, status: str, progress: int | None = None):
    job.status = status
    if progress is not None:
        job.progress = progress
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def append_job_log(job_id: int, text: str):
    import os
    logdir = os.environ.get('DATA_LOG_DIR', os.path.join(os.getcwd(), 'data', 'logs'))
    os.makedirs(logdir, exist_ok=True)
    path = os.path.join(logdir, f"job-{job_id}.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def read_job_log(job_id: int, max_lines: int = 200):
    import os
    logdir = os.environ.get('DATA_LOG_DIR', os.path.join(os.getcwd(), 'data', 'logs'))
    path = os.path.join(logdir, f"job-{job_id}.log")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[-max_lines:])


def append_flow_log(flow_id: int, text: str):
    import os
    logdir = os.environ.get('DATA_LOG_DIR', os.path.join(os.getcwd(), 'data', 'logs'))
    os.makedirs(logdir, exist_ok=True)
    path = os.path.join(logdir, f"flow-{flow_id}.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def read_flow_log(flow_id: int, max_lines: int = 500):
    import os
    logdir = os.environ.get('DATA_LOG_DIR', os.path.join(os.getcwd(), 'data', 'logs'))
    path = os.path.join(logdir, f"flow-{flow_id}.log")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[-max_lines:])


def create_flow(session, name: str, steps: list, description: str | None = None):
    flow = Flow(name=name, steps=steps, description=description)
    session.add(flow)
    session.commit()
    session.refresh(flow)
    return flow


def get_flow(session, flow_id: int):
    statement = select(Flow).where(Flow.id == flow_id)
    return session.exec(statement).first()


def list_flows(session, limit: int = 50):
    statement = select(Flow).order_by(Flow.created_at.desc()).limit(limit)
    return session.exec(statement).all()


def create_flow_run(session, flow_id: int):
    from datetime import datetime
    run = FlowRun(flow_id=flow_id, status='running', job_ids=[] , started_at=datetime.utcnow())
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_flow_run(session, run_id: int):
    statement = select(FlowRun).where(FlowRun.id == run_id)
    return session.exec(statement).first()


def list_flow_runs(session, flow_id: int, limit: int = 50):
    statement = select(FlowRun).where(FlowRun.flow_id == flow_id).order_by(FlowRun.started_at.desc()).limit(limit)
    return session.exec(statement).all()


def append_job_to_run(session, run_id: int, job_id: int):
    run = get_flow_run(session, run_id)
    if not run:
        return None
    if not run.job_ids:
        run.job_ids = []
    run.job_ids.append(job_id)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def update_flow_run_status(session, run_id: int, status: str, finished_at=None):
    run = get_flow_run(session, run_id)
    if not run:
        return None
    run.status = status
    if finished_at:
        run.finished_at = finished_at
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def create_audit_entry(session, username: str | None, profile: str | None, payload: dict | None, lang: str = 'de'):
    from datetime import datetime
    from .models import AuditEntry

    entry = AuditEntry(username=username, profile=profile, lang=lang, payload=payload, ts=datetime.utcnow())
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_audit_entries(session, limit: int = 100):
    from .models import AuditEntry
    statement = select(AuditEntry).order_by(AuditEntry.ts.desc()).limit(limit)
    return session.exec(statement).all()
