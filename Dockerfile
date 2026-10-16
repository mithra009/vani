
# Stage 1: Obtain standalone FFmpeg binaries
FROM mwader/static-ffmpeg:8.1.2 AS ffmpeg

# Stage 2: Your Python application
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

# Copy FFmpeg binaries instead of installing via apt
COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
COPY media_service/requirements.txt media_service/requirements.txt
COPY editor_service/requirements.txt editor_service/requirements.txt

RUN pip install --retries 20 \
    -r backend/requirements.txt \
    -r media_service/requirements.txt \
    -r editor_service/requirements.txt

COPY backend backend
COPY media_service media_service
COPY editor_service editor_service

RUN useradd --create-home --uid 10001 vani \
    && mkdir -p /app/storage \
    && chown -R vani /app/storage

USER vani

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8010"]
