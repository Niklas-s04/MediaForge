from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from .db import create_db_and_tables, get_session
from . import crud, models
from .schemas import JobCreate, JobRead, FlowCreate, FlowRead, FlowRunRead
from .celery_app import celery_app
from sqlmodel import Session
from passlib.context import CryptContext
from passlib.hash import pbkdf2_sha256
import secrets
import os
import time
import json
import shutil
import uuid
from fastapi.responses import StreamingResponse, FileResponse
import logging
from .compression_goals import (
    load_compression_goals,
    resolve_compression_family,
    get_compression_profile,
    summarize_profile_warning,
)
from .audit import audit_override


app = FastAPI(title="MediaForge API")
logger = logging.getLogger(__name__)

# Serve frontend static assets if mounted into the container at /app/static
static_dir = "/app/static"

# Main frontend route under /ui
try:
    app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="ui")
except Exception:
    # if mounting fails for any reason, continue without UI
    pass

# Vite builds assets as /assets/..., so FastAPI must expose this path too.
assets_dir = os.path.join(static_dir, "assets")
try:
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
except Exception:
    pass


security = HTTPBasic()


def get_log_dir() -> str:
    return os.environ.get("DATA_LOG_DIR") or os.environ.get("LOG_DIR") or "/data/logs"


def get_upload_dir() -> str:
    return os.environ.get("DATA_UPLOAD_DIR") or "/data/uploads"


def get_output_dir() -> str:
    return os.environ.get("DATA_OUTPUT_DIR") or "/data/output"


def get_resume_offset(request: Request) -> int:
    last_event_id = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    try:
        return int(last_event_id) if last_event_id else 0
    except Exception:
        return 0


# Helper wrappers using passlib's pbkdf2 implementation directly to avoid bcrypt/native-extension checks
def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pbkdf2_sha256.verify(password, hashed)


def verify_credentials(
    credentials: HTTPBasicCredentials = Depends(security),
    session: Session = Depends(get_session),
):
    # Check users table for username and verify hashed password
    user = crud.get_user_by_username(session, credentials.username)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    verified = verify_password(credentials.password, user.hashed_password)
    if not verified:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user.username


def safe_upload_filename(filename: str | None) -> str:
    basename = os.path.basename(filename or "upload.bin")
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in basename)
    return cleaned.strip("._") or "upload.bin"


def infer_file_name_or_ext(input_obj: dict) -> str | None:
    file_name_or_ext = input_obj.get("file_name") or input_obj.get("original_filename")
    if file_name_or_ext:
        return file_name_or_ext

    url = input_obj.get("url")
    if url:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            return os.path.basename(parsed.path)
        except Exception:
            return None

    file_path = input_obj.get("file_path") or input_obj.get("input_path")
    if file_path:
        return os.path.basename(file_path)

    return None


def validate_compression_warning(
    *,
    payload: dict,
    input_obj: dict,
    username: str,
    session: Session,
    force: bool,
    lang: str,
):
    effective_lang = input_obj.get("lang") or lang
    profile_name = input_obj.get("compression_profile")
    if not profile_name:
        return

    family = resolve_compression_family(
        mime_type=input_obj.get("mime_type"),
        file_name_or_ext=infer_file_name_or_ext(input_obj),
    )
    try:
        prof = get_compression_profile(family, profile_name)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown compression profile '{profile_name}' for family '{family}'",
        )

    warning = summarize_profile_warning(prof, lang=effective_lang)
    if warning and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "warning": warning,
                "message": "Use ?force=true to override",
            },
        )
    if warning and force:
        try:
            audit_override(
                payload=payload,
                username=username,
                profile=profile_name,
                lang=effective_lang,
            )
        except Exception:
            logger.exception("Failed to write override audit log")

        try:
            crud.create_audit_entry(
                session,
                username=username,
                profile=profile_name,
                payload=payload,
                lang=effective_lang,
            )
        except Exception:
            logger.exception("Failed to create override audit entry")


def dispatch_job(job: models.Job):
    if job.type == "download":
        celery_app.send_task("worker.process_download_and_convert", args=[job.id])
    elif job.type == "convert":
        celery_app.send_task("worker.process_convert", args=[job.id])
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported job type '{job.type}'")


@app.on_event("startup")
def on_startup():
    create_db_and_tables()

    # Ensure admin user exists
    admin_user = os.environ.get("ADMIN_USER", "admin")
    admin_pass = os.environ.get("ADMIN_PASSWORD", "admin")

    # bcrypt has a 72-byte input limit; truncate long passwords to avoid ValueError
    try:
        b = admin_pass.encode("utf-8")
        if len(b) > 72:
            logging.warning("ADMIN_PASSWORD longer than 72 bytes; truncating before hashing")
            admin_pass = b[:72].decode("utf-8", errors="ignore")
    except Exception:
        # be conservative: ensure admin_pass is a string
        admin_pass = str(admin_pass)[:72]

    from .db import engine
    from sqlmodel import Session as SQLSession

    with SQLSession(engine) as session:
        existing = crud.get_user_by_username(session, admin_user)
        if not existing:
            hashed = hash_password(admin_pass)
            crud.create_user(session, admin_user, hashed, is_admin=True)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return RedirectResponse(url="/ui/index.html")


@app.post("/api/jobs", response_model=JobRead)
def create_job(
    req: JobCreate,
    force: bool = False,
    lang: str = "de",
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    # Server-side validation: if a compression_profile is provided, evaluate warnings
    try:
        input_obj = req.input or {}
        validate_compression_warning(
            payload=req.dict(),
            input_obj=input_obj,
            username=username,
            session=session,
            force=force,
            lang=lang,
        )

    except HTTPException:
        raise
    except Exception:
        # non-fatal: continue to job creation if validation fails unexpectedly
        logger.exception("Unexpected compression validation error")

    if req.type not in ("download", "convert"):
        raise HTTPException(status_code=400, detail=f"Unsupported job type '{req.type}'")

    job = crud.create_job(session, req.type, req.input)

    # Dispatch worker task to process this job
    try:
        dispatch_job(job)
    except HTTPException:
        raise
    except Exception:
        # If dispatch fails, keep job in queued state
        logger.exception("Failed to dispatch worker task for job %s", job.id)

    return JobRead(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        output_path=job.output_path,
    )


@app.post("/api/jobs/convert-upload", response_model=JobRead)
def create_convert_upload_job(
    file: UploadFile = File(...),
    preset: str = Form("default"),
    compression_family: str = Form("audio"),
    compression_profile: str = Form("balanced"),
    lang: str = Form("de"),
    force: bool = False,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    input_obj = {
        "source": "upload",
        "preset": preset,
        "compression_profile": compression_profile,
        "lang": lang,
        "mime_type": file.content_type or f"{compression_family}/x-mediaforge",
        "original_filename": file.filename,
    }
    payload = {"type": "convert", "input": input_obj}

    try:
        validate_compression_warning(
            payload=payload,
            input_obj=input_obj,
            username=username,
            session=session,
            force=force,
            lang=lang,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected compression validation error")

    upload_dir = get_upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}-{safe_upload_filename(file.filename)}"
    upload_path = os.path.join(upload_dir, filename)

    try:
        with open(upload_path, "wb") as target:
            shutil.copyfileobj(file.file, target)
    except Exception:
        logger.exception("Failed to store upload")
        raise HTTPException(status_code=500, detail="Failed to store uploaded file")

    input_obj["file_path"] = upload_path
    job = crud.create_job(session, "convert", input_obj)

    try:
        dispatch_job(job)
    except Exception:
        logger.exception("Failed to dispatch worker task for job %s", job.id)

    return JobRead(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        output_path=job.output_path,
    )


@app.get("/api/jobs/{job_id}")
def get_job(
    job_id: int,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    job = crud.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: int, username: str = Depends(verify_credentials)):
    text = crud.read_job_log(job_id)
    return {"job_id": job_id, "log": text}


@app.get("/api/jobs/{job_id}/download")
def download_job_output(
    job_id: int,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    job = crud.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "success" or not job.output_path:
        raise HTTPException(status_code=409, detail="Job output is not ready")

    output_dir = os.path.realpath(get_output_dir())
    output_path = os.path.realpath(job.output_path)
    if output_path != output_dir and not output_path.startswith(output_dir + os.sep):
        raise HTTPException(status_code=403, detail="Output path is outside the download directory")
    if not os.path.exists(output_path) or not os.path.isfile(output_path):
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        output_path,
        media_type="application/octet-stream",
        filename=os.path.basename(output_path),
    )


@app.get("/api/jobs/{job_id}/events")
def job_events(
    job_id: int,
    request: Request,
    username: str = Depends(verify_credentials),
):
    # Server-Sent Events streaming job status by polling DB and log
    def event_generator():
        # stateless generator: always stream only new bytes and include byte-offset as id
        log_dir = get_log_dir()
        log_path = os.path.join(log_dir, f"job-{job_id}.log")
        offset = get_resume_offset(request)

        while True:
            try:
                with next(get_session()) as session:
                    job = crud.get_job(session, job_id)
                    status = job.status if job else "notfound"
            except Exception:
                status = "error"

            # read appended data from log file
            new_chunk = ""
            try:
                if os.path.exists(log_path):
                    with open(log_path, "rb") as f:
                        f.seek(offset)
                        data = f.read()
                        if data:
                            new_chunk = data.decode("utf-8", errors="replace")
                            offset = f.tell()
            except Exception:
                new_chunk = ""

            payload = {"status": status, "chunk": new_chunk}

            # include offset as event id so clients can resume using Last-Event-ID
            yield f"id: {offset}\n"
            yield f"data: {json.dumps(payload)}\n\n"

            if status in ("success", "failed", "cancelled", "notfound"):
                break

            # heartbeat / poll interval
            time.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/jobs")
def list_jobs(
    limit: int = 50,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    jobs = crud.list_jobs(session, limit=limit)
    return jobs


@app.get("/api/presets")
def get_presets():
    try:
        path = os.path.join(os.path.dirname(__file__), "presets.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return {}


@app.get("/api/compression/goals")
def api_get_compression_goals():
    return load_compression_goals()


@app.get("/api/compression/resolve")
def api_resolve_family(mime: str | None = None, ext: str | None = None):
    try:
        fam = resolve_compression_family(mime_type=mime, file_name_or_ext=ext)
        return {"family": fam}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/compression/profile")
def api_get_profile(
    family: str | None = None,
    profile: str = "balanced",
    lang: str = "de",
):
    try:
        p = get_compression_profile(family, profile)
        warning = summarize_profile_warning(p, lang=lang)
        if warning:
            p = dict(p)
            p["warning"] = warning
        return p
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/audit")
def api_list_audit(
    limit: int = 100,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    # only admin users may list audit entries
    user = crud.get_user_by_username(session, username)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    return crud.list_audit_entries(session, limit=limit)


@app.post("/api/flows")
def create_flow_endpoint(
    flow: FlowCreate,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    f = crud.create_flow(session, flow.name, flow.steps, description=None)
    return {"id": f.id, "name": f.name, "steps": f.steps}


@app.get("/api/flows")
def list_flows_endpoint(
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    fs = crud.list_flows(session)
    return fs


@app.get("/api/flows/{flow_id}")
def get_flow_endpoint(
    flow_id: int,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    f = crud.get_flow(session, flow_id)
    if not f:
        raise HTTPException(status_code=404, detail="Flow not found")
    return f


@app.post("/api/flows/{flow_id}/run")
def run_flow_endpoint(
    flow_id: int,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    flow = crud.get_flow(session, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    try:
        # create a FlowRun record to track this execution
        run = crud.create_flow_run(session, flow_id)

        # dispatch worker with flow_id and run_id
        celery_app.send_task("worker.run_flow", args=[flow_id, run.id])

        return {"flow_id": flow_id, "run_id": run.id, "status": "started"}
    except Exception:
        logger.exception("Failed to dispatch flow %s", flow_id)
        try:
            if "run" in locals() and run.id:
                crud.update_flow_run_status(session, run.id, "failed")
        except Exception:
            logger.exception("Failed to mark flow run dispatch failure")
        raise HTTPException(status_code=500, detail="Failed to dispatch flow")


@app.get("/api/flows/{flow_id}/runs")
def list_flow_runs_endpoint(
    flow_id: int,
    limit: int = 50,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    runs = crud.list_flow_runs(session, flow_id, limit=limit)
    return runs


@app.get("/api/runs/{run_id}")
def get_run_endpoint(
    run_id: int,
    username: str = Depends(verify_credentials),
    session: Session = Depends(get_session),
):
    run = crud.get_flow_run(session, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/api/runs/{run_id}/events")
def run_events(
    run_id: int,
    request: Request,
    username: str = Depends(verify_credentials),
):
    # SSE streaming for a specific run: filter flow log lines for this run
    def event_generator():
        # Use byte-offset resume via Last-Event-ID; send only appended lines matching this run
        log_dir = get_log_dir()

        # interpret Last-Event-ID as byte offset
        offset = get_resume_offset(request)

        while True:
            try:
                with next(get_session()) as session:
                    run = crud.get_flow_run(session, run_id)
                    if not run:
                        status = "notfound"
                        flow_id = None
                    else:
                        status = run.status
                        flow_id = run.flow_id
            except Exception:
                status = "error"
                flow_id = None

            chunk = ""
            if flow_id:
                flow_log_path = os.path.join(log_dir, f"flow-{flow_id}.log")
                try:
                    if os.path.exists(flow_log_path):
                        with open(flow_log_path, "rb") as f:
                            f.seek(offset)
                            data = f.read()
                            if data:
                                text = data.decode("utf-8", errors="replace")

                                # filter lines referencing this run
                                needle = f"(run {run_id})"
                                lines = [line for line in text.splitlines() if needle in line]
                                if lines:
                                    chunk = "\n".join(lines)

                            offset = f.tell()
                except Exception:
                    chunk = ""

            payload = {"status": status, "run_log": chunk}

            yield f"id: {offset}\n"
            yield f"data: {json.dumps(payload)}\n\n"

            if status in ("completed", "failed", "cancelled", "notfound"):
                break

            time.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/flows/{flow_id}/events")
def flow_events(
    flow_id: int,
    request: Request,
    username: str = Depends(verify_credentials),
):
    # SSE streaming for flow-level logs and status
    def event_generator():
        # Use byte-offset resume via Last-Event-ID and stream appended flow log
        log_dir = get_log_dir()
        offset = get_resume_offset(request)

        flow_log_path = os.path.join(log_dir, f"flow-{flow_id}.log")

        while True:
            try:
                with next(get_session()) as session:
                    f = crud.get_flow(session, flow_id)
                    status = "unknown" if not f else "enabled" if f.enabled else "disabled"
            except Exception:
                status = "error"

            new_chunk = ""
            try:
                if os.path.exists(flow_log_path):
                    with open(flow_log_path, "rb") as fh:
                        fh.seek(offset)
                        data = fh.read()
                        if data:
                            new_chunk = data.decode("utf-8", errors="replace")
                            offset = fh.tell()
            except Exception:
                new_chunk = ""

            payload = {"status": status, "chunk": new_chunk}

            yield f"id: {offset}\n"
            yield f"data: {json.dumps(payload)}\n\n"

            if "completed" in new_chunk or "unexpected error" in new_chunk or status == "disabled":
                break

            time.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8787)),
    )
