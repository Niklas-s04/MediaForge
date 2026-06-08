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

COPY apps/api/requirements.txt ./apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

COPY apps/api ./apps/api
COPY docs ./docs
COPY --from=frontend-build /src/apps/frontend/dist ./static

EXPOSE 8787
CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8787"]
