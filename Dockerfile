# Stage 1: build the web client.
FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same origin as the API: the backend serves the build at "/".
ENV VITE_API_BASE=""
RUN npm run build

# Stage 2: the backend, which also serves the built client.
FROM python:3.12-slim
# ffmpeg converts browser recordings (webm/mp4) for speech-to-text servers
# that only read WAV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 poligloti
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY examples/ examples/
COPY scripts/ scripts/
COPY --from=web /web/dist frontend/dist
ENV DATA_DIR=/data \
    AUDIO_ROOT=/tmp/poligloti-audio \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data && chown poligloti /data
USER poligloti
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8100"]
