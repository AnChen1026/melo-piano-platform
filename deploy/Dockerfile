FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libsndfile1 ffmpeg tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN pip install --no-cache-dir basic-pitch==0.4.0 --no-deps
COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY deploy/start.sh /app/deploy/start.sh
COPY --from=frontend /build/dist/ /app/frontend/dist/
RUN useradd --create-home appuser && mkdir -p /app/uploads && chown -R appuser:appuser /app
USER appuser
EXPOSE 10000
CMD ["sh", "/app/deploy/start.sh"]
