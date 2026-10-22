from celery import Celery
import os

redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("api", broker=redis_url)
celery_app.conf.task_ignore_result = True
