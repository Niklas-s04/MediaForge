from celery import Celery
import os
import time
import shutil
import datetime
import logging
from sqlmodel import Session, create_engine, select
from typing import Optional
import yt_dlp
import subprocess
import glob
import json
from apps.api.app.compression_goals import resolve_compression_family, get_compression_profile
from apps.api.app.models import Flow, FlowRun, Job

redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("worker", broker=redis_url, backend=redis_url)


DEFAULT_FORMATS = {
    "audio": "mp3",
    "video": "mp4",
    "image": "webp",
}
FORMAT_CODECS = {
    "audio": {
        "mp3": {"codec": "libmp3lame", "bitrate": {"high": "256k", "balanced": "160k", "small": "96k"}},
        "m4a": {"codec": "aac", "bitrate": {"high": "256k", "balanced": "160k", "small": "96k"}},
        "opus": {"codec": "libopus", "bitrate": {"high": "192k", "balanced": "128k", "small": "80k"}},
        "wav": {"codec": "pcm_s16le"},
        "flac": {"codec": "flac"},
    },
    "video": {
        "mp4": {"video_codec": "libx264", "audio_codec": "aac"},
        "webm": {"video_codec": "libvpx-vp9", "audio_codec": "libopus"},
        "mkv": {"video_codec": "libx264", "audio_codec": "aac"},
    },
}
VIDEO_QUALITY = {
    "high": {"crf": 20, "max_width": None, "max_fps": None},
    "balanced": {"crf": 24, "max_width": 1920, "max_fps": 30},
    "small": {"crf": 30, "max_width": 1280, "max_fps": 24},
}
IMAGE_QUALITY = {
    "high": {"quality": 92, "jpeg_q": 2, "png_level": 3, "max_width": None},
    "balanced": {"quality": 82, "jpeg_q": 4, "png_level": 6, "max_width": 1920},
    "small": {"quality": 70, "jpeg_q": 8, "png_level": 9, "max_width": 1280},
}


@celery_app.task(bind=True, name="worker.echo")
def echo(self, message: str):
    return {"echo": message}


@celery_app.task(bind=True, name="worker.convert_placeholder")
def convert_placeholder(self, input_path: str, output_path: str):
    # Very small placeholder task that simulates work
    for i in range(3):
        time.sleep(1)
    # ensure work dir exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("converted placeholder")
    return {"output": output_path}


def _log(job_id: int, text: str):
    logdir = os.environ.get('DATA_LOG_DIR', '/data/logs')
    os.makedirs(logdir, exist_ok=True)
    path = os.path.join(logdir, f"job-{job_id}.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.utcnow().isoformat()}] {text}\n")


def _log_flow(flow_id: int, text: str):
    logdir = os.environ.get('DATA_LOG_DIR', '/data/logs')
    os.makedirs(logdir, exist_ok=True)
    path = os.path.join(logdir, f"flow-{flow_id}.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.utcnow().isoformat()}] {text}\n")


def _get_engine():
    db_url = os.environ.get('DATABASE_URL', 'sqlite:////data/db.sqlite3')
    connect_args = {"check_same_thread": False} if db_url.startswith('sqlite') else {}
    return create_engine(db_url, connect_args=connect_args)


def _get_upload_dir() -> str:
    return os.environ.get("DATA_UPLOAD_DIR", "/data/uploads")


def _is_path_inside(base_dir: str, target_path: str) -> bool:
    base = os.path.realpath(base_dir)
    target = os.path.realpath(target_path)
    return target == base or target.startswith(base + os.sep)


def _remove_upload_source(path: str | None):
    if not path:
        return
    if not _is_path_inside(_get_upload_dir(), path):
        return
    try:
        if os.path.exists(path) and os.path.isfile(path):
            os.remove(path)
    except Exception:
        logging.exception("Failed to remove uploaded source file %s", path)


def _safe_stem(path: str | None, fallback: str) -> str:
    stem = os.path.splitext(os.path.basename(path or ""))[0] or fallback
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)
    return cleaned.strip("._") or fallback


def _profile_output_ext(family: str | None, profile: dict) -> str:
    if family == "image":
        return str(profile.get("format") or "webp").lstrip(".")
    return str(profile.get("container") or "mp3").lstrip(".")


def _clean_choice(value: str | None, allowed: set[str], fallback: str) -> str:
    cleaned = str(value or fallback).lower().lstrip(".")
    return cleaned if cleaned in allowed else fallback


def _quality_preset(input_obj: dict) -> str:
    return _clean_choice(
        input_obj.get("quality_preset") or input_obj.get("compression_profile"),
        {"high", "balanced", "small"},
        "balanced",
    )


def _int_option(value, default=None, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except Exception:
        return default
    if minimum is not None and parsed < minimum:
        return default
    if maximum is not None and parsed > maximum:
        return default
    return parsed


def _choice_option(value, allowed: set[str], default: str):
    cleaned = str(value or "").lower()
    return cleaned if cleaned in allowed else default


def _download_format_selector(kind: str, download_quality: str | None) -> str:
    if kind == "audio":
        return "bestaudio/best"

    quality = _clean_choice(download_quality, {"best", "1080p", "720p", "480p", "360p"}, "best")
    if quality == "best":
        return "bestvideo+bestaudio/best"
    max_height = quality.removesuffix("p")
    return f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"


def _image_filter(quality: str) -> list[str]:
    settings = IMAGE_QUALITY[quality]
    max_width = settings.get("max_width")
    if not max_width:
        return []
    return [
        "-vf",
        f"scale=w='min({int(max_width)},iw)':h='min({int(max_width)},ih)':force_original_aspect_ratio=decrease",
    ]


def _build_media_command(
    input_path: str,
    output_path: str,
    family: str,
    output_format: str,
    quality: str,
    strip_metadata: bool,
    options: dict | None = None,
):
    options = options or {}
    cmd = ["ffmpeg", "-y", "-i", input_path]

    if family == "audio":
        format_config = FORMAT_CODECS["audio"].get(output_format) or FORMAT_CODECS["audio"]["mp3"]
        codec = _choice_option(
            options.get("audio_codec"),
            {"libmp3lame", "aac", "libopus", "pcm_s16le", "flac"},
            str(format_config["codec"]),
        )
        cmd += ["-vn", "-acodec", codec]
        bitrate = options.get("audio_bitrate") or (format_config.get("bitrate") or {}).get(quality)
        if bitrate:
            cmd += ["-b:a", str(bitrate)]
        sample_rate = _int_option(options.get("sample_rate"), minimum=8000, maximum=192000)
        if sample_rate:
            cmd += ["-ar", str(sample_rate)]
        channels = _int_option(options.get("audio_channels"), minimum=1, maximum=8)
        if channels:
            cmd += ["-ac", str(channels)]
    elif family == "video":
        format_config = FORMAT_CODECS["video"].get(output_format) or FORMAT_CODECS["video"]["mp4"]
        settings = VIDEO_QUALITY[quality]
        video_codec = _choice_option(
            options.get("video_codec"),
            {"libx264", "libx265", "libvpx-vp9"},
            str(format_config["video_codec"]),
        )
        audio_codec = _choice_option(
            options.get("audio_codec"),
            {"aac", "libopus", "libmp3lame"},
            str(format_config["audio_codec"]),
        )
        crf = _int_option(options.get("crf"), settings["crf"], minimum=0, maximum=51)
        cmd += [
            "-c:v",
            video_codec,
            "-c:a",
            audio_codec,
            "-crf",
            str(crf),
        ]
        if output_format == "webm":
            cmd += ["-b:v", "0"]
        else:
            cmd += ["-preset", "medium"]
            if output_format == "mp4":
                cmd += ["-movflags", "+faststart"]
        filters = []
        max_width = _int_option(options.get("max_width"), settings.get("max_width"), minimum=16, maximum=7680)
        max_height = _int_option(options.get("max_height"), None, minimum=16, maximum=4320)
        max_fps = _int_option(options.get("max_fps"), settings.get("max_fps"), minimum=1, maximum=240)
        if max_width:
            target_height = max_height or -2
            filters.append(f"scale=w='min({int(max_width)},iw)':h={target_height}:force_original_aspect_ratio=decrease")
        if max_fps:
            filters.append(f"fps={int(max_fps)}")
        if filters:
            cmd += ["-vf", ",".join(filters)]
    elif family == "image":
        settings = IMAGE_QUALITY[quality]
        cmd += ["-frames:v", "1"]
        max_width = _int_option(options.get("max_width"), settings.get("max_width"), minimum=16, maximum=20000)
        max_height = _int_option(options.get("max_height"), max_width, minimum=16, maximum=20000) if max_width else None
        if max_width and max_height:
            cmd += [
                "-vf",
                f"scale=w='min({int(max_width)},iw)':h='min({int(max_height)},ih)':force_original_aspect_ratio=decrease",
            ]
        else:
            cmd += _image_filter(quality)
        image_quality = _int_option(options.get("image_quality"), settings["quality"], minimum=1, maximum=100)
        if output_format == "webp":
            cmd += ["-quality", str(image_quality)]
        elif output_format == "jpg":
            jpeg_q = max(2, min(31, round((100 - image_quality) / 3.3) + 2))
            cmd += ["-q:v", str(jpeg_q)]
        elif output_format == "png":
            cmd += ["-compression_level", str(settings["png_level"])]
    else:
        cmd += ["-c", "copy"]

    if strip_metadata:
        cmd += ["-map_metadata", "-1"]

    cmd.append(output_path)
    return cmd


def _build_convert_command(input_path: str, output_path: str, family: str | None, profile: dict):
    strip_metadata = bool(profile.get("strip_metadata", True))
    cmd = ["ffmpeg", "-y", "-i", input_path]

    if family == "audio":
        codec = profile.get("codec", "libmp3lame")
        cmd += ["-vn", "-acodec", str(codec)]
        if "bitrate" in profile:
            cmd += ["-b:a", str(profile["bitrate"])]
        else:
            cmd += ["-q:a", str(profile.get("quality", 4))]
    elif family == "video":
        cmd += [
            "-c:v",
            str(profile.get("video_codec", "libx264")),
            "-c:a",
            str(profile.get("audio_codec", "aac")),
            "-crf",
            str(profile.get("crf", 28)),
            "-movflags",
            "+faststart",
        ]
        filters = []
        max_width = profile.get("max_width")
        max_height = profile.get("max_height")
        max_fps = profile.get("max_fps")
        if max_width and max_height:
            filters.append(
                f"scale=w='min({int(max_width)},iw)':h='min({int(max_height)},ih)':force_original_aspect_ratio=decrease"
            )
        if max_fps:
            filters.append(f"fps={int(max_fps)}")
        if filters:
            cmd += ["-vf", ",".join(filters)]
    elif family == "image":
        fmt = str(profile.get("format", "webp"))
        cmd += ["-frames:v", "1"]
        max_width = profile.get("max_width")
        max_height = profile.get("max_height")
        if max_width and max_height:
            cmd += [
                "-vf",
                f"scale=w='min({int(max_width)},iw)':h='min({int(max_height)},ih)':force_original_aspect_ratio=decrease",
            ]
        if fmt == "webp":
            cmd += ["-quality", str(profile.get("quality", 82))]
        else:
            cmd += ["-q:v", str(profile.get("quality", 82))]
    else:
        cmd += ["-c", "copy"]

    if strip_metadata:
        cmd += ["-map_metadata", "-1"]

    cmd.append(output_path)
    return cmd


# load presets from local file if available
_PRESETS = {}
try:
    preset_path = os.path.join(os.path.dirname(__file__), 'presets.json')
    if os.path.exists(preset_path):
        with open(preset_path, 'r', encoding='utf-8') as pf:
            _PRESETS = json.load(pf)
except Exception:
    _PRESETS = {}


@celery_app.task(bind=True, name="worker.process_download_and_convert")
def process_download_and_convert(self, job_id: int):
    """Download with yt-dlp and convert to the requested media output.
    Updates job status in the SQLite DB and writes logs to /data/logs/job-{id}.log.
    """
    engine = _get_engine()
    try:
        with Session(engine) as session:
            stmt = select(Job).where(Job.id == job_id)
            job = session.exec(stmt).first()
            if not job:
                _log(job_id, "Job not found in DB")
                return
            # mark started
            job.status = 'running'
            job.started_at = datetime.datetime.utcnow()
            job.progress = 5
            session.add(job)
            session.commit()

            input_url = job.input.get('url') if job.input else None
            if not input_url:
                _log(job_id, "No input URL provided")
                job.status = 'failed'
                session.add(job)
                session.commit()
                return

            tmp_root = os.environ.get('DATA_TMP_DIR', '/data/tmp')
            outdir = os.environ.get('DATA_OUTPUT_DIR', '/data/output')
            tmpdir = os.path.join(tmp_root, f"job-{job_id}")
            os.makedirs(tmpdir, exist_ok=True)
            os.makedirs(outdir, exist_ok=True)

            _log(job_id, f"Starting download: {input_url}")
            input_obj = job.input or {}
            preset_name = (job.input or {}).get('preset') if job.input else None
            preset = _PRESETS.get(preset_name) if preset_name else _PRESETS.get('default', {})
            output_kind = _clean_choice(input_obj.get("output_kind"), {"audio", "video"}, "audio")
            output_format = _clean_choice(
                input_obj.get("output_format"),
                set(FORMAT_CODECS[output_kind].keys()),
                DEFAULT_FORMATS[output_kind],
            )
            quality = _quality_preset(input_obj)
            strip_metadata = bool(input_obj.get("strip_metadata", True))
            fmt = _download_format_selector(output_kind, input_obj.get("download_quality"))
            download_timeout = preset.get('download_timeout', 300)
            retries = int(preset.get('retries', 3))
            backoff = float(preset.get('backoff', 2))

            outtmpl = os.path.join(tmpdir, '%(id)s.%(ext)s')
            download_cmd = ['yt-dlp', '-f', fmt, '-o', outtmpl, input_url]

            filename = None
            attempt = 0
            while attempt < retries:
                attempt += 1
                _log(job_id, f"Download attempt {attempt}/{retries} cmd={' '.join(download_cmd)} timeout={download_timeout}s")
                try:
                    subprocess.run(download_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=download_timeout)
                    # find the downloaded file in tmpdir
                    files = glob.glob(os.path.join(tmpdir, '*'))
                    if files:
                        # choose the largest file
                        files.sort(key=lambda p: os.path.getsize(p), reverse=True)
                        filename = files[0]
                    if filename:
                        break
                except subprocess.TimeoutExpired as te:
                    _log(job_id, f"Download timed out (attempt {attempt}): {te}")
                except subprocess.CalledProcessError as ce:
                    _log(job_id, f"yt-dlp failed (attempt {attempt}): {ce}")
                except Exception as e:
                    _log(job_id, f"Download exception (attempt {attempt}): {e}")

                # backoff before next try
                time.sleep(backoff ** attempt)

            if not filename:
                _log(job_id, f"Download failed after {retries} attempts")
                job.status = 'failed'
                job.error_message = 'download_failed'
                session.add(job)
                session.commit()
                return

            _log(job_id, f"Downloaded to {filename}")
            job.progress = 40
            session.add(job)
            session.commit()

            outpath = os.path.join(outdir, f"job-{job_id}.{output_format}")
            _log(job_id, f"Converting to {output_format}: {outpath}")
            try:
                _log(job_id, f"Output decision: kind={output_kind} format={output_format} quality={quality}")
                cmd = _build_media_command(
                    filename,
                    outpath,
                    output_kind,
                    output_format,
                    quality,
                    strip_metadata,
                    input_obj,
                )
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                _log(job_id, f"Conversion failed: {e}")
                job.status = 'failed'
                job.error_message = str(e)
                session.add(job)
                session.commit()
                return

            _log(job_id, f"Conversion finished: {outpath}")
            job.progress = 100
            job.status = 'success'
            job.output_path = outpath
            job.finished_at = datetime.datetime.utcnow()
            session.add(job)
            session.commit()
            # cleanup tmp
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass
            return {'output': outpath}
    except Exception as e:
        logging.exception('Unexpected worker error')
        _log(job_id, f"Unexpected error: {e}")
        # best-effort DB update
        try:
            engine2 = _get_engine()
            with Session(engine2) as session2:
                stmt2 = select(Job).where(Job.id == job_id)
                job2 = session2.exec(stmt2).first()
                if job2:
                    job2.status = 'failed'
                    job2.error_message = str(e)
                    session2.add(job2)
                    session2.commit()
        except Exception:
            pass


@celery_app.task(bind=True, name="worker.process_convert")
def process_convert(self, job_id: int):
    """Convert a local uploaded file using the selected compression profile."""
    engine = _get_engine()
    upload_source_to_cleanup = None
    try:
        with Session(engine) as session:
            stmt = select(Job).where(Job.id == job_id)
            job = session.exec(stmt).first()
            if not job:
                _log(job_id, "Job not found in DB")
                return

            job.status = "running"
            job.started_at = datetime.datetime.utcnow()
            job.progress = 5
            job.current_step = "Datei vorbereiten"
            session.add(job)
            session.commit()

            input_obj = job.input or {}
            input_path = input_obj.get("file_path") or input_obj.get("input_path")
            if input_obj.get("source") != "upload" or not input_path or not _is_path_inside(_get_upload_dir(), input_path):
                _log(job_id, "Invalid upload source")
                job.status = "failed"
                job.error_message = "invalid_upload_source"
                job.finished_at = datetime.datetime.utcnow()
                session.add(job)
                session.commit()
                return
            upload_source_to_cleanup = input_path
            if not input_path or not os.path.exists(input_path):
                _log(job_id, "Input file not found")
                job.status = "failed"
                job.error_message = "input_file_not_found"
                job.finished_at = datetime.datetime.utcnow()
                session.add(job)
                session.commit()
                return

            outdir = os.environ.get("DATA_OUTPUT_DIR", "/data/output")
            os.makedirs(outdir, exist_ok=True)

            original_name = input_obj.get("original_filename") or input_path
            quality = _quality_preset(input_obj)
            try:
                source_family = resolve_compression_family(
                    mime_type=input_obj.get("mime_type"),
                    file_name_or_ext=original_name,
                )
            except Exception as e:
                _log(job_id, f"Media family resolution failed: {e}")
                job.status = "failed"
                job.error_message = str(e)
                job.finished_at = datetime.datetime.utcnow()
                session.add(job)
                session.commit()
                return
            if source_family == "video":
                allowed_output_families = {"video", "audio"}
            elif source_family == "audio":
                allowed_output_families = {"audio"}
            elif source_family == "image":
                allowed_output_families = {"image"}
            else:
                allowed_output_families = {source_family}
            requested_family = str(input_obj.get("compression_family") or input_obj.get("output_family") or source_family).lower()
            family = requested_family if requested_family in allowed_output_families else source_family
            output_format = _clean_choice(
                input_obj.get("output_format"),
                set(FORMAT_CODECS.get(family, {}).keys()) if family != "image" else {"webp", "jpg", "png"},
                DEFAULT_FORMATS.get(family, "mp3"),
            )
            strip_metadata = bool(input_obj.get("strip_metadata", True))

            stem = _safe_stem(original_name, f"job-{job_id}")
            outpath = os.path.join(outdir, f"job-{job_id}-{stem}.{output_format}")
            cmd = _build_media_command(input_path, outpath, family, output_format, quality, strip_metadata, input_obj)

            _log(job_id, f"Starting local conversion: {input_path}")
            _log(job_id, f"Output decision: source_family={source_family} family={family} format={output_format} quality={quality}")
            job.progress = 35
            job.current_step = "Konvertierung läuft"
            session.add(job)
            session.commit()

            try:
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                _log(job_id, f"Conversion failed: {e}")
                job.status = "failed"
                job.error_message = str(e)
                job.finished_at = datetime.datetime.utcnow()
                session.add(job)
                session.commit()
                return

            _log(job_id, f"Conversion finished: {outpath}")
            job.progress = 100
            job.status = "success"
            job.current_step = "Fertig"
            job.output_path = outpath
            job.finished_at = datetime.datetime.utcnow()
            session.add(job)
            session.commit()
            return {"output": outpath}
    except Exception as e:
        logging.exception("Unexpected local conversion worker error")
        _log(job_id, f"Unexpected error: {e}")
        try:
            with Session(engine) as session2:
                stmt2 = select(Job).where(Job.id == job_id)
                job2 = session2.exec(stmt2).first()
                if job2:
                    job2.status = "failed"
                    job2.error_message = str(e)
                    job2.finished_at = datetime.datetime.utcnow()
                    session2.add(job2)
                    session2.commit()
        except Exception:
            pass
    finally:
        _remove_upload_source(upload_source_to_cleanup)


@celery_app.task(bind=True, name="worker.run_flow")
def run_flow(self, flow_id: int, run_id: Optional[int] = None):
    engine = _get_engine()
    try:
        with Session(engine) as session:
            # load flow
            stmt = select(Flow).where(Flow.id == flow_id)
            flow = session.exec(stmt).first()
            if not flow:
                _log_flow(flow_id, "Flow not found in DB")
                return

            # ensure we have a FlowRun record
            run = None
            if run_id:
                stmtr = select(FlowRun).where(FlowRun.id == run_id)
                run = session.exec(stmtr).first()
            if not run:
                run = FlowRun(flow_id=flow_id, status='running', job_ids=[], started_at=datetime.datetime.utcnow())
                session.add(run)
                session.commit()
                session.refresh(run)

            steps = flow.steps or []
            _log_flow(flow_id, f"Starting flow {flow_id} with {len(steps)} steps (run {run.id})")
            run_failed = False

            for idx, step in enumerate(steps):
                action = step.get('action')
                input_obj = step.get('input', {})

                # create a job for this step (ensure created_at set)
                job = Job(type=action, input=input_obj, status='queued', created_at=datetime.datetime.utcnow())
                session.add(job)
                session.commit()
                session.refresh(job)
                _log_flow(flow_id, f"Flow step {idx}: created job {job.id} action={action}")

                # attach job id to run
                run.job_ids = (run.job_ids or []) + [job.id]
                session.add(run)
                session.commit()

                if action == 'download':
                    # dispatch download task and wait for completion by polling job row
                    celery_app.send_task('worker.process_download_and_convert', args=[job.id])
                    waited = 0
                    timeout = int(step.get('timeout', 3600))
                    # Use a fresh short-lived Session for each poll so we observe
                    # updates made by the worker process (avoid identity-map caching).
                    while waited < timeout:
                        try:
                            with Session(engine) as poll_sess:
                                stmtj = select(Job).where(Job.id == job.id)
                                cur = poll_sess.exec(stmtj).first()
                                if cur and cur.status in ('success', 'failed', 'cancelled'):
                                    _log_flow(flow_id, f"Job {job.id} finished with status {cur.status}")
                                    if cur.status != 'success':
                                        run_failed = True
                                    break
                        except Exception as e:
                            _log_flow(flow_id, f"Error polling job {job.id}: {e}")
                        time.sleep(1)
                        waited += 1
                    else:
                        _log_flow(flow_id, f"Job {job.id} timed out after {timeout}s")
                        run_failed = True
                        try:
                            with Session(engine) as timeout_sess:
                                stmtj = select(Job).where(Job.id == job.id)
                                timed_out_job = timeout_sess.exec(stmtj).first()
                                if timed_out_job:
                                    timed_out_job.status = 'failed'
                                    timed_out_job.error_message = 'flow_step_timeout'
                                    timed_out_job.finished_at = datetime.datetime.utcnow()
                                    timeout_sess.add(timed_out_job)
                                    timeout_sess.commit()
                        except Exception as e:
                            _log_flow(flow_id, f"Error marking job {job.id} timed out: {e}")

                else:
                    run_failed = True
                    job.status = 'failed'
                    job.error_message = f"unknown_action:{action}"
                    job.finished_at = datetime.datetime.utcnow()
                    session.add(job)
                    session.commit()
                    _log_flow(flow_id, f"Unknown action '{action}' - failing run")

            # finalize run
            run.status = 'failed' if run_failed else 'completed'
            run.finished_at = datetime.datetime.utcnow()
            session.add(run)
            session.commit()

            _log_flow(flow_id, f"Flow {flow_id} {run.status} (run {run.id})")
            return {'flow': flow_id, 'run': run.id, 'status': run.status}

    except Exception as e:
        logging.exception('Flow runner error')
        _log_flow(flow_id, f"Flow runner unexpected error: {e}")
        try:
            with Session(engine) as session:
                target_run = None
                if run_id:
                    target_run = session.exec(select(FlowRun).where(FlowRun.id == run_id)).first()
                if target_run:
                    target_run.status = 'failed'
                    target_run.finished_at = datetime.datetime.utcnow()
                    session.add(target_run)
                    session.commit()
        except Exception:
            logging.exception('Failed to mark flow run failed')
        return
