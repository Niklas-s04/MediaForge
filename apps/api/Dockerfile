FROM node:20-alpine AS frontend-build
WORKDIR /src

COPY apps/frontend/package*.json ./apps/frontend/
WORKDIR /src/apps/frontend
RUN npm ci

COPY apps/frontend ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp/mediaforge-home

COPY apps/api/requirements.txt ./apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

COPY apps/api ./apps/api
COPY docs ./docs
COPY --from=frontend-build /src/apps/frontend/dist ./static

RUN groupadd --gid 10001 mediaforge \
	&& useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mediaforge \
	&& mkdir -p /data /tmp/mediaforge-home \
	&& chmod -R a=rX /app \
	&& chown -R mediaforge:mediaforge /data /tmp/mediaforge-home

USER 10001:10001
EXPOSE 8787
CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8787"]
