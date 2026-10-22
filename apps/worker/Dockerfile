FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp/mediaforge-home
ENV TMPDIR=/scratch/tmp
ENV DATA_TMP_DIR=/scratch/jobs

RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		ffmpeg \
		ca-certificates \
		libreoffice-writer \
		libreoffice-calc \
		libreoffice-impress \
		poppler-utils \
		ghostscript \
		librsvg2-bin \
		fonts-dejavu \
	&& rm -rf /var/lib/apt/lists/*

COPY apps/worker/requirements.txt ./apps/worker/requirements.txt
RUN pip install --no-cache-dir -r apps/worker/requirements.txt

COPY apps/api ./apps/api
COPY apps/worker ./apps/worker

RUN groupadd --gid 10001 mediaforge \
	&& useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mediaforge \
	&& mkdir -p /data /tmp/mediaforge-home /scratch/tmp /scratch/jobs \
	&& chmod -R a=rX /app \
	&& chown -R mediaforge:mediaforge /data /tmp/mediaforge-home /scratch

USER 10001:10001
ENTRYPOINT ["python", "-m", "apps.api.app.runtime"]
CMD ["celery", "-A", "apps.worker.worker:celery_app", "worker", "--loglevel=info", "--concurrency=1"]
