FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
	&& apt-get install -y --no-install-recommends ffmpeg git ca-certificates \
	&& rm -rf /var/lib/apt/lists/*

COPY apps/worker/requirements.txt ./apps/worker/requirements.txt
RUN pip install --no-cache-dir -r apps/worker/requirements.txt

COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY docs ./docs

CMD ["celery", "-A", "apps.worker.worker:celery_app", "worker", "--loglevel=info"]
