# Build from tts-bench/: docker build -f runner/Dockerfile -t <repo>/runner:<tag> .
# .env (with ELEVENLABS_API_KEY) is baked in: treat the image as secret and keep the registry private.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY runner/requirements.txt runner/requirements.txt
RUN pip install --no-cache-dir -r runner/requirements.txt

COPY runner/ runner/
COPY config/ config/
COPY --chown=app:app .env .env
RUN chmod 400 .env

ENV PYTHONUNBUFFERED=1 \
    PROVIDER_CONFIG_PATH=/app/config/providers.yaml
USER app
ENTRYPOINT ["python", "-m", "runner.main"]
