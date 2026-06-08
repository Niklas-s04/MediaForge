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
    """Download with yt-dlp and convert audio to mp3 using ffmpeg.
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
            preset_name = (job.input or {}).get('preset') if job.input else None
            preset = _PRESETS.get(preset_name) if preset_name else _PRESETS.get('default', {})
            fmt = preset.get('format', 'bestaudio/best')
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

            # convert to mp3 using ffmpeg subprocess for simplicity
            outpath = os.path.join(outdir, f"job-{job_id}.mp3")
            _log(job_id, f"Converting to mp3: {outpath}")
            try:
                # allow preset to override ffmpeg options
                ff = preset.get('ffmpeg', {}) if preset else {}
                q = ff.get('quality', '2')
                codec = ff.get('codec', 'libmp3lame')
                # determine compression family/profile based on downloaded file or job input
                try:
                    family = resolve_compression_family(mime_type=None, file_name_or_ext=filename)
                    profile_name = (job.input or {}).get('compression_profile', 'balanced')
                    profile = get_compression_profile(family, profile_name)
                    _log(job_id, f"Compression decision: family={family} profile={profile_name} options={profile}")
                except Exception as _e:
                    family = None
                    profile = {}

                # build ffmpeg command using profile if audio
                if family == 'audio':
                    codec = profile.get('codec', codec)
                    if 'bitrate' in profile:
                        cmd = ['ffmpeg', '-y', '-i', filename, '-vn', '-acodec', codec, '-b:a', profile['bitrate'], outpath]
                    else:
                        cmd = ['ffmpeg', '-y', '-i', filename, '-vn', '-acodec', codec, '-q:a', str(profile.get('quality', q)), outpath]
                else:
                    cmd = ['ffmpeg', '-y', '-i', filename, '-vn', '-acodec', codec, '-q:a', str(q), outpath]
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
