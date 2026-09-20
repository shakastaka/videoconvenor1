# Backend

FastAPI API для анализа публичных источников и выдачи MP4.

- `GET /health` — состояние backend и FFmpeg;
- `POST /api/analyze` — метаданные и доступные разрешения;
- `GET /api/download/video` — скачивание и сборка MP4.
- `GET /api/download/audio` — извлечение MP3;
- `GET /api/transcribe` — локальная расшифровка TXT, SRT или VTT.

Зависимости перечислены в `requirements.txt`. Полная инструкция находится в корневом `README.md`.
