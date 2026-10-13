# One image for every Python process: backend (:8010), media API (:8020) + worker,
# editor API (:8030) + worker. docker-compose.yml picks the command per service.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg/ffprobe for every pipeline, libsndfile for soundfile.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
COPY media_service/requirements.txt media_service/requirements.txt
COPY editor_service/requirements.txt editor_service/requirements.txt
RUN pip install -r backend/requirements.txt -r media_service/requirements.txt -r editor_service/requirements.txt

COPY backend backend
COPY media_service media_service
COPY editor_service editor_service

RUN useradd --create-home --uid 10001 vani \
 && mkdir -p /app/storage && chown -R vani /app/storage
USER vani

# Secrets come from env_file at runtime, never baked into the image.
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8010"]
