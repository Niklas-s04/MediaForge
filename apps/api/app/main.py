from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from .db import create_db_and_tables, engine, get_session
from . import crud, models
from .schemas import JobCreate, JobRead, FlowCreate, FlowRead, FlowRunRead
from .celery_app import celery_app
from sqlmodel import Session, select
from datetime import datetime, timedelta
from sqlalchemy import text
import os
import time
import json
import uuid
import threading
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


DOWNLOAD_FORMATS = {
    "audio": {"mp3", "m4a", "aac", "opus", "ogg", "oga", "wav", "flac", "aiff", "alac", "wma"},
    "video": {"mp4", "webm", "mkv", "mov", "m4v", "avi", "mpg", "mpeg", "flv", "wmv", "ogv", "ts", "vob"},
}
CONVERT_FORMATS = {
    "audio": {"mp3", "m4a", "aac", "opus", "ogg", "oga", "wav", "flac", "aiff", "alac", "wma"},
    "video": {"mp4", "webm", "mkv", "mov", "m4v", "avi", "mpg", "mpeg", "flv", "wmv", "ogv", "ts", "vob"},
    "image": {"webp", "jpg", "png", "avif", "gif", "bmp", "tiff", "ico", "svg"},
    "document": {"docx", "doc", "odt", "rtf", "txt", "html", "pdf"},
    "spreadsheet": {"xlsx", "xls", "ods", "csv", "html", "pdf"},
    "presentation": {"pptx", "ppt", "odp", "html", "pdf"},
    "pdf": {"pdf", "txt"},
    "text": {"txt", "html", "pdf", "docx", "odt", "rtf"},
}
FORMAT_ALIASES = {
    "image": {
        "jpeg": "jpg",
        "tif": "tiff",
    },
}
QUALITY_PRESETS = {"high", "balanced", "small"}
DOWNLOAD_QUALITIES = {"best", "1080p", "720p", "480p", "360p"}
_cleanup_thread_started = False


class DownloadInspectRequest(BaseModel):
    url: str

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


def get_log_dir() -> str:
    return os.environ.get("DATA_LOG_DIR") or os.environ.get("LOG_DIR") or "/data/logs"


def get_upload_dir() -> str:
    return os.environ.get("DATA_UPLOAD_DIR") or "/data/uploads"


def get_output_dir() -> str:
    return os.environ.get("DATA_OUTPUT_DIR") or "/data/output"


def get_max_upload_bytes() -> int:
    raw = os.environ.get("MAX_UPLOAD_BYTES", "2147483648")
    try:
        value = int(raw)
    except Exception:
        value = 2147483648
    return max(1, value)


def get_output_retention_hours() -> float:
    raw = os.environ.get("OUTPUT_RETENTION_HOURS", "24")
    try:
        value = float(raw)
    except Exception:
        value = 24.0
    return max(0.0, value)


def get_output_cleanup_interval_seconds() -> int:
    raw = os.environ.get("OUTPUT_CLEANUP_INTERVAL_SECONDS", "3600")
    try:
        value = int(raw)
    except Exception:
        value = 3600
    return max(0, value)


def calculate_expiry(finished_at: datetime | None = None) -> datetime:
    return (finished_at or datetime.utcnow()) + timedelta(hours=get_output_retention_hours())


def job_to_read(job: models.Job) -> JobRead:
    return JobRead(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        output_path=job.output_path,
        created_at=job.created_at,
        finished_at=job.finished_at,
        expires_at=job.expires_at,
    )


def is_path_inside(base_dir: str, target_path: str) -> bool:
    base = os.path.realpath(base_dir)
    target = os.path.realpath(target_path)
    return target == base or target.startswith(base + os.sep)


def remove_output_file(output_path: str | None) -> bool:
    if not output_path:
        return True
    output_dir = os.path.realpath(get_output_dir())
    real_output_path = os.path.realpath(output_path)
    if not is_path_inside(output_dir, real_output_path):
        logger.warning("Refusing to remove output outside DATA_OUTPUT_DIR: %s", output_path)
        return False
    if not os.path.exists(real_output_path):
        return True
    if not os.path.isfile(real_output_path):
        logger.warning("Refusing to remove non-file output: %s", output_path)
        return False
    try:
        os.remove(real_output_path)
        return True
    except Exception:
        logger.exception("Failed to remove output file %s", output_path)
        return False


def expire_old_job_outputs(session: Session, now: datetime | None = None) -> int:
    retention_hours = get_output_retention_hours()
    if retention_hours <= 0:
        return 0

    current_time = now or datetime.utcnow()
    backfill_statement = select(models.Job).where(
        models.Job.status == "success",
        models.Job.output_path.is_not(None),
        models.Job.expires_at.is_(None),
        models.Job.finished_at.is_not(None),
    )
    backfilled = 0
    for job in session.exec(backfill_statement).all():
        job.expires_at = calculate_expiry(job.finished_at)
        session.add(job)
        backfilled += 1
    if backfilled:
        session.commit()

    statement = select(models.Job).where(
        models.Job.status == "success",
        models.Job.output_path.is_not(None),
        models.Job.expires_at.is_not(None),
        models.Job.expires_at <= current_time,
    )
    expired = 0
    for job in session.exec(statement).all():
        if not remove_output_file(job.output_path):
            continue

        job.status = "expired"
        job.output_path = None
        job.current_step = "Ausgabedatei nach 24h geloescht"
        job.current_step = "Ausgabedatei nach 24h gelöscht"
        job.current_step = "Ausgabedatei nach 24h geloescht"
        session.add(job)
        expired += 1

    if expired:
        session.commit()
    return expired


def ensure_job_retention_columns():
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(job)").fetchall()}
        if "expires_at" not in columns:
            connection.execute(text("ALTER TABLE job ADD COLUMN expires_at DATETIME"))
        if "deleted_at" not in columns:
            connection.execute(text("ALTER TABLE job ADD COLUMN deleted_at DATETIME"))


def _run_output_cleanup_once():
    try:
        with Session(engine) as session:
            expire_old_job_outputs(session)
    except Exception:
        logger.exception("Output cleanup failed")


def _output_cleanup_loop():
    while True:
        interval = get_output_cleanup_interval_seconds()
        if interval <= 0:
            return
        time.sleep(interval)
        _run_output_cleanup_once()


def start_output_cleanup_thread():
    global _cleanup_thread_started
    if _cleanup_thread_started or get_output_cleanup_interval_seconds() <= 0:
        return
    _cleanup_thread_started = True
    thread = threading.Thread(target=_output_cleanup_loop, name="output-cleanup", daemon=True)
    thread.start()


def get_resume_offset(request: Request) -> int:
    last_event_id = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    try:
        return int(last_event_id) if last_event_id else 0
    except Exception:
        return 0


def safe_upload_filename(filename: str | None) -> str:
    basename = os.path.basename(filename or "upload.bin")
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in basename)
    return cleaned.strip("._") or "upload.bin"


def store_upload_file(file: UploadFile, upload_dir: str, max_bytes: int) -> str:
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}-{safe_upload_filename(file.filename)}"
    upload_path = os.path.join(upload_dir, filename)
    if not is_path_inside(upload_dir, upload_path):
        raise HTTPException(status_code=400, detail="Invalid upload path")

    written = 0
    try:
        with open(upload_path, "wb") as target:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="Uploaded file is too large")
                target.write(chunk)
    except HTTPException:
        try:
            if os.path.exists(upload_path):
                os.remove(upload_path)
        except Exception:
            logger.exception("Failed to remove oversized upload")
        raise
    except Exception:
        try:
            if os.path.exists(upload_path):
                os.remove(upload_path)
        except Exception:
            logger.exception("Failed to remove partial upload")
        logger.exception("Failed to store upload")
        raise HTTPException(status_code=500, detail="Failed to store uploaded file")

    return upload_path


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


def quality_to_warning_profile(quality_preset: str | None) -> str:
    return "small" if quality_preset == "small" else "balanced"


def infer_family_from_upload(file: UploadFile, fallback: str | None = None) -> str:
    family = resolve_compression_family(
        mime_type=file.content_type,
        file_name_or_ext=file.filename,
    )
    if family in CONVERT_FORMATS:
        return family
    if fallback in CONVERT_FORMATS:
        return fallback
    raise HTTPException(status_code=400, detail="Unsupported media type")


def normalize_download_input(input_obj: dict) -> dict:
    normalized = dict(input_obj or {})
    output_kind = normalized.get("output_kind") or normalized.get("media_mode") or "audio"
    output_kind = str(output_kind).lower()
    if output_kind not in DOWNLOAD_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported download output kind '{output_kind}'")

    default_format = "mp3" if output_kind == "audio" else "mp4"
    output_format = str(normalized.get("output_format") or default_format).lower().lstrip(".")
    if output_format not in DOWNLOAD_FORMATS[output_kind]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {output_kind} download format '{output_format}'",
        )

    quality_preset = str(normalized.get("quality_preset") or "balanced").lower()
    if quality_preset not in QUALITY_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unsupported quality preset '{quality_preset}'")

    download_quality = str(normalized.get("download_quality") or "best").lower()
    if download_quality not in DOWNLOAD_QUALITIES:
        raise HTTPException(status_code=400, detail=f"Unsupported download quality '{download_quality}'")

    normalized["output_kind"] = output_kind
    normalized["output_format"] = output_format
    normalized["quality_preset"] = quality_preset
    normalized["download_quality"] = download_quality
    normalized["strip_metadata"] = bool(normalized.get("strip_metadata", True))
    normalized["compression_profile"] = quality_to_warning_profile(quality_preset)
    normalized["lang"] = normalized.get("lang") or "de"
    normalized["mime_type"] = f"{output_kind}/x-mediaforge"
    return normalized


def normalize_convert_options(
    *,
    file: UploadFile,
    compression_family: str | None,
    compression_profile: str | None,
    output_format: str | None,
    quality_preset: str | None,
    strip_metadata: bool,
) -> dict:
    source_family = infer_family_from_upload(file, compression_family)
    requested_family = compression_family if isinstance(compression_family, str) else None
    output_family = str(requested_family or source_family).lower()
    if source_family == "video":
        allowed_families = {"video", "audio"}
    elif source_family == "audio":
        allowed_families = {"audio"}
    elif source_family == "image":
        allowed_families = {"image", "pdf"}
    elif source_family == "document":
        allowed_families = {"document", "pdf", "text"}
    elif source_family == "spreadsheet":
        allowed_families = {"spreadsheet", "pdf", "text"}
    elif source_family == "presentation":
        allowed_families = {"presentation", "pdf"}
    elif source_family == "pdf":
        allowed_families = {"pdf", "text", "image"}
    elif source_family == "text":
        allowed_families = {"text", "document", "pdf"}
    else:
        allowed_families = {source_family}
    if output_family not in allowed_families:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot convert {source_family} to {output_family}",
        )

    requested_quality = quality_preset if isinstance(quality_preset, str) else None
    requested_profile = compression_profile if isinstance(compression_profile, str) else None
    requested_format = output_format if isinstance(output_format, str) else None
    effective_strip_metadata = strip_metadata if isinstance(strip_metadata, bool) else True
    effective_quality = str(requested_quality or requested_profile or "balanced").lower()
    if effective_quality not in QUALITY_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unsupported quality preset '{effective_quality}'")

    default_format = {
        "audio": "mp3",
        "video": "mp4",
        "image": "webp",
        "document": "docx",
        "spreadsheet": "xlsx",
        "presentation": "pptx",
        "pdf": "pdf",
        "text": "txt",
    }[output_family]
    effective_format = normalize_output_format(output_family, requested_format, default_format)
    if effective_format not in CONVERT_FORMATS[output_family]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {output_family} conversion format '{effective_format}'",
        )
    if source_family == "image" and output_family == "pdf" and effective_format != "pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image to PDF conversion format '{effective_format}'",
        )

    return {
        "source_family": source_family,
        "family": output_family,
        "output_format": effective_format,
        "quality_preset": effective_quality,
        "compression_profile": quality_to_warning_profile(effective_quality),
        "strip_metadata": effective_strip_metadata,
    }


def optional_form_text(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def normalize_output_format(family: str, output_format: str | None, fallback: str) -> str:
    normalized = str(output_format or fallback).lower().lstrip(".")
    return FORMAT_ALIASES.get(family, {}).get(normalized, normalized)


def summarize_download_info(info: dict) -> dict:
    formats = []
    seen_heights = set()
    for item in info.get("formats") or []:
        height = item.get("height")
        if not height or height in seen_heights:
            continue
        seen_heights.add(height)
        formats.append(
            {
                "height": height,
                "ext": item.get("ext"),
                "fps": item.get("fps"),
            }
        )
    formats.sort(key=lambda value: value.get("height") or 0, reverse=True)
    return {
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url") or info.get("original_url"),
        "formats": formats[:8],
    }


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
    ensure_job_retention_columns()
    _run_output_cleanup_once()
    start_output_cleanup_thread()


@app.get("/health")
def health():
    return {"status": "ok"}


def frontend_static_file(filename: str, media_type: str):
    path = os.path.join(static_dir, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Frontend asset not found")
    return FileResponse(path, media_type=media_type)


@app.get("/logo.png", include_in_schema=False)
def full_logo():
    return frontend_static_file("logo.png", "image/png")


@app.get("/logo-mark.png", include_in_schema=False)
def logo_mark():
    return frontend_static_file("logo-mark.png", "image/png")


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
    session: Session = Depends(get_session),
):
    if req.type != "download":
        raise HTTPException(status_code=400, detail=f"Unsupported job type '{req.type}'")

    input_obj = normalize_download_input(req.input or {})
    payload = {"type": req.type, "input": input_obj}

    # Server-side validation: if a compression_profile is provided, evaluate warnings
    try:
        validate_compression_warning(
            payload=payload,
            input_obj=input_obj,
            username="local",
            session=session,
            force=force,
            lang=lang,
        )

    except HTTPException:
        raise
    except Exception:
        # non-fatal: continue to job creation if validation fails unexpectedly
        logger.exception("Unexpected compression validation error")

    job = crud.create_job(session, req.type, input_obj)

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
        created_at=job.created_at,
        finished_at=job.finished_at,
        expires_at=job.expires_at,
    )


@app.post("/api/jobs/convert-upload", response_model=JobRead)
def create_convert_upload_job(
    file: UploadFile = File(...),
    preset: str = Form("default"),
    compression_family: str = Form("audio"),
    compression_profile: str = Form("balanced"),
    output_format: str | None = Form(None),
    quality_preset: str | None = Form(None),
    strip_metadata: bool = Form(True),
    video_codec: str | None = Form(None),
    audio_codec: str | None = Form(None),
    audio_bitrate: str | None = Form(None),
    sample_rate: str | None = Form(None),
    audio_channels: str | None = Form(None),
    crf: str | None = Form(None),
    max_width: str | None = Form(None),
    max_height: str | None = Form(None),
    max_fps: str | None = Form(None),
    image_quality: str | None = Form(None),
    lang: str = Form("de"),
    force: bool = False,
    session: Session = Depends(get_session),
):
    options = normalize_convert_options(
        file=file,
        compression_family=compression_family,
        compression_profile=compression_profile,
        output_format=output_format,
        quality_preset=quality_preset,
        strip_metadata=strip_metadata,
    )
    input_obj = {
        "source": "upload",
        "preset": preset,
        "source_family": options["source_family"],
        "compression_family": options["family"],
        "compression_profile": options["compression_profile"],
        "quality_preset": options["quality_preset"],
        "output_format": options["output_format"],
        "strip_metadata": options["strip_metadata"],
        "video_codec": optional_form_text(video_codec),
        "audio_codec": optional_form_text(audio_codec),
        "audio_bitrate": optional_form_text(audio_bitrate),
        "sample_rate": optional_form_text(sample_rate),
        "audio_channels": optional_form_text(audio_channels),
        "crf": optional_form_text(crf),
        "max_width": optional_form_text(max_width),
        "max_height": optional_form_text(max_height),
        "max_fps": optional_form_text(max_fps),
        "image_quality": optional_form_text(image_quality),
        "lang": lang,
        "mime_type": file.content_type or f"{options['family']}/x-mediaforge",
        "original_filename": file.filename,
    }
    payload = {"type": "convert", "input": input_obj}

    try:
        validate_compression_warning(
            payload=payload,
            input_obj=input_obj,
            username="local",
            session=session,
            force=force,
            lang=lang,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected compression validation error")

    upload_path = store_upload_file(file, get_upload_dir(), get_max_upload_bytes())
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
        created_at=job.created_at,
        finished_at=job.finished_at,
        expires_at=job.expires_at,
    )


@app.get("/api/jobs/{job_id}")
def get_job(
    job_id: int,
    session: Session = Depends(get_session),
):
    job = crud.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: int):
    text = crud.read_job_log(job_id)
    return {"job_id": job_id, "log": text}


@app.get("/api/jobs/{job_id}/download")
def download_job_output(
    job_id: int,
    session: Session = Depends(get_session),
):
    job = crud.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"expired", "deleted"}:
        raise HTTPException(status_code=410, detail="Job output is no longer available")
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


@app.delete("/api/jobs/{job_id}", response_model=JobRead)
def delete_job_output(
    job_id: int,
    session: Session = Depends(get_session),
):
    job = crud.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Running jobs cannot be deleted")
    if not remove_output_file(job.output_path):
        raise HTTPException(status_code=403, detail="Output path is outside the download directory")

    job.status = "deleted"
    job.output_path = None
    job.current_step = "Auftrag manuell geloescht"
    job.deleted_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job_to_read(job)


@app.post("/api/jobs/{job_id}/extend", response_model=JobRead)
def extend_job_output(
    job_id: int,
    session: Session = Depends(get_session),
):
    job = crud.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"expired", "deleted"}:
        raise HTTPException(status_code=410, detail="Job output is no longer available")
    if job.status != "success" or not job.output_path:
        raise HTTPException(status_code=409, detail="Job output is not ready")

    base = job.expires_at or calculate_expiry(job.finished_at)
    if base < datetime.utcnow():
        base = datetime.utcnow()
    job.expires_at = base + timedelta(hours=24)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job_to_read(job)


@app.get("/api/jobs/{job_id}/events")
def job_events(
    job_id: int,
    request: Request,
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
                    progress = job.progress if job else 0
                    current_step = job.current_step if job else None
                    expires_at = job.expires_at.isoformat() if job and job.expires_at else None
            except Exception:
                status = "error"
                progress = 0
                current_step = None
                expires_at = None

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

            payload = {
                "status": status,
                "chunk": new_chunk,
                "progress": progress,
                "current_step": current_step,
                "expires_at": expires_at,
            }

            # include offset as event id so clients can resume using Last-Event-ID
            yield f"id: {offset}\n"
            yield f"data: {json.dumps(payload)}\n\n"

            if status in ("success", "failed", "cancelled", "expired", "deleted", "notfound"):
                break

            # heartbeat / poll interval
            time.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/jobs")
def list_jobs(
    limit: int = 50,
    include_expired: bool = False,
    session: Session = Depends(get_session),
):
    expire_old_job_outputs(session)
    jobs = crud.list_jobs(session, limit=limit, include_expired=include_expired)
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


@app.get("/api/options")
def get_media_options():
    return {
        "download": {
            "formats": {key: sorted(value) for key, value in DOWNLOAD_FORMATS.items()},
            "qualities": sorted(DOWNLOAD_QUALITIES),
            "quality_presets": sorted(QUALITY_PRESETS),
        },
        "convert": {
            "formats": {key: sorted(value) for key, value in CONVERT_FORMATS.items()},
            "quality_presets": sorted(QUALITY_PRESETS),
        },
    }


@app.post("/api/download/inspect")
def inspect_download(
    req: DownloadInspectRequest,
):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "skip_download": True,
                "noplaylist": True,
                "extract_flat": False,
            }
        ) as ydl:
            info = ydl.extract_info(url, download=False)
        if isinstance(info, dict) and "entries" in info and info["entries"]:
            info = info["entries"][0]
        if not isinstance(info, dict):
            raise ValueError("No media information returned")
        return summarize_download_info(info)
    except HTTPException:
        raise
    except Exception as e:
        logger.info("Download inspection failed for %s: %s", url, e)
        raise HTTPException(status_code=400, detail="Download analysis failed")


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
    session: Session = Depends(get_session),
):
    return crud.list_audit_entries(session, limit=limit)


@app.post("/api/flows")
def create_flow_endpoint(
    flow: FlowCreate,
    session: Session = Depends(get_session),
):
    f = crud.create_flow(session, flow.name, flow.steps, description=None)
    return {"id": f.id, "name": f.name, "steps": f.steps}


@app.get("/api/flows")
def list_flows_endpoint(
    session: Session = Depends(get_session),
):
    fs = crud.list_flows(session)
    return fs


@app.get("/api/flows/{flow_id}")
def get_flow_endpoint(
    flow_id: int,
    session: Session = Depends(get_session),
):
    f = crud.get_flow(session, flow_id)
    if not f:
        raise HTTPException(status_code=404, detail="Flow not found")
    return f


@app.post("/api/flows/{flow_id}/run")
def run_flow_endpoint(
    flow_id: int,
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
    session: Session = Depends(get_session),
):
    runs = crud.list_flow_runs(session, flow_id, limit=limit)
    return runs


@app.get("/api/runs/{run_id}")
def get_run_endpoint(
    run_id: int,
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
