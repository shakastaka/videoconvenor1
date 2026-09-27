FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build


FROM node:22-bookworm-slim AS pot-build

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git

WORKDIR /app/bgutil-ytdlp-pot-provider/server
RUN npm ci && npx tsc


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WHISPER_MODEL=tiny \
    MAX_CONCURRENT_DOWNLOADS=1 \
    MAX_FILESIZE_BYTES=524288000 \
    MAX_DURATION_SECONDS=7200 \
    MAX_TRANSCRIPTION_DURATION_SECONDS=7200 \
    ALLOWED_SOURCE_DOMAINS=youtube.com,youtu.be,tiktok.com

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY --from=pot-build /app/bgutil-ytdlp-pot-provider/server /app/bgutil-server

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --no-cache-dir \
    -r /app/backend/requirements.txt \
    bgutil-ytdlp-pot-provider==2.0.0

COPY backend /app/backend
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

EXPOSE 8000

CMD ["sh", "-c", "node /app/bgutil-server/build/main.js --host 127.0.0.1 --port 4416 & exec uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
