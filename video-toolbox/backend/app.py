from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import shutil
import socket
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from starlette.background import BackgroundTask


APP_VERSION = "0.5.0"
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
MAX_FILESIZE = int(os.getenv("MAX_FILESIZE_BYTES", str(2 * 1024**3)))
MAX_DURATION_SECONDS = int(os.getenv("MAX_DURATION_SECONDS", str(2 * 60 * 60)))
MAX_TRANSCRIPTION_DURATION_SECONDS = int(os.getenv("MAX_TRANSCRIPTION_DURATION_SECONDS", str(60 * 60)))
ALLOWED_SOURCE_DOMAINS = tuple(
    item.strip().lower().lstrip(".")
    for item in os.getenv("ALLOWED_SOURCE_DOMAINS", "").split(",")
    if item.strip()
)
DEFAULT_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
ALLOWED_ORIGINS = [item.strip() for item in os.getenv("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",") if item.strip()]
DOWNLOADS = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
TRANSCRIPTIONS = asyncio.Semaphore(1)

app = FastAPI(title="Video Toolbox API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class AnalyzeRequest(BaseModel):
    url: HttpUrl


def _is_forbidden_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _validate_public_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Нужна публичная ссылка http:// или https://")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Ссылки с логином и паролем не поддерживаются")

    hostname = parsed.hostname.rstrip(".").lower()
    if ALLOWED_SOURCE_DOMAINS and not any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in ALLOWED_SOURCE_DOMAINS
    ):
        raise HTTPException(status_code=400, detail="Сейчас поддерживаются ссылки YouTube и TikTok")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as error:
        raise HTTPException(status_code=400, detail="Адрес источника не найден") from error

    if not addresses or any(_is_forbidden_ip(address) for address in addresses):
        raise HTTPException(status_code=400, detail="Локальные и служебные адреса запрещены")
    return raw_url


def _friendly_error(error: Exception) -> HTTPException:
    message = re.sub(r"\x1b\[[0-9;]*m", "", str(error)).strip()
    message = message.splitlines()[-1] if message else "Не удалось обработать источник"
    message = message.removeprefix("ERROR: ")[:500]
    lowered = message.lower()
    if "login" in lowered or "sign in" in lowered or "cookies" in lowered:
        message = "Источник требует входа или cookies. В этой версии работают только публичные видео."
    elif "drm" in lowered:
        message = "DRM-защищённые видео не поддерживаются."
    elif "unsupported url" in lowered:
        message = "Этот источник пока не поддерживается."
    return HTTPException(status_code=422, detail=message)


def _has_watermark(format_info: dict[str, Any]) -> bool:
    description = " ".join(
        str(format_info.get(key) or "")
        for key in ("format_id", "format", "format_note", "format_name", "resolution")
    ).lower()
    clean_markers = ("no watermark", "without watermark", "watermark-free")
    return "watermark" in description and not any(marker in description for marker in clean_markers)


def _usable_video_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    formats = [
        item
        for item in info.get("formats") or []
        if item.get("vcodec") not in {None, "none"} and not item.get("has_drm")
    ]
    clean = [item for item in formats if not _has_watermark(item)]
    return clean or formats


def _enforce_limits(info: dict[str, Any], max_duration_seconds: int = MAX_DURATION_SECONDS) -> None:
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > max_duration_seconds:
        limit_minutes = max_duration_seconds // 60
        raise ValueError(f"Видео длиннее допустимого лимита {limit_minutes} минут")


def _extract_metadata(raw_url: str, max_duration_seconds: int = MAX_DURATION_SECONDS) -> dict[str, Any]:
    options = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(raw_url, download=False)
    if info.get("_type") == "playlist":
        entries = [entry for entry in info.get("entries") or [] if entry]
        if not entries:
            raise ValueError("Плейлист не содержит доступных видео")
        info = entries[0]
    _enforce_limits(info, max_duration_seconds)
    return info


def _metadata_payload(raw_url: str) -> dict[str, Any]:
    info = _extract_metadata(raw_url)
    formats = _usable_video_formats(info)
    heights = sorted(
        {int(item["height"]) for item in formats if isinstance(item.get("height"), (int, float))},
        reverse=True,
    )[:5]
    if not heights:
        heights = [720]
    return {
        "title": info.get("title") or "Видео без названия",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader") or info.get("channel"),
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "webpage_url": info.get("webpage_url") or raw_url,
        "qualities": heights,
        "clean_source_policy": "preferred_when_available",
    }


def _format_score(item: dict[str, Any], target_height: int, video: bool) -> tuple[Any, ...]:
    height = int(item.get("height") or 0)
    within_target = height <= target_height if height else True
    extension_score = item.get("ext") in ({"mp4"} if video else {"m4a", "mp4"})
    return (within_target, height if within_target else -height, extension_score, float(item.get("tbr") or item.get("abr") or 0))


def _choose_format(info: dict[str, Any], target_height: int) -> str:
    formats = info.get("formats") or []
    video_formats = _usable_video_formats(info)
    if not video_formats:
        return f"best[height<={target_height}]/best"

    video_format = max(video_formats, key=lambda item: _format_score(item, target_height, True))
    if video_format.get("acodec") not in {None, "none"}:
        return str(video_format["format_id"])

    audio_formats = [
        item
        for item in formats
        if item.get("vcodec") == "none" and item.get("acodec") not in {None, "none"} and not item.get("has_drm")
    ]
    if not audio_formats:
        return str(video_format["format_id"])
    audio_format = max(audio_formats, key=lambda item: _format_score(item, target_height, False))
    return f"{video_format['format_id']}+{audio_format['format_id']}"


def _safe_filename(title: str) -> str:
    cleaned = re.sub(r"[^\w\-. ()\[\]]+", "_", title, flags=re.UNICODE).strip(" ._")
    return f"{(cleaned or 'video')[:120]}.mp4"


def _download_video(raw_url: str, target_height: int, directory: Path) -> tuple[Path, str]:
    metadata = _extract_metadata(raw_url)
    selected_format = _choose_format(metadata, target_height)
    output_template = str(directory / "video.%(ext)s")
    options = {
        "format": selected_format,
        "outtmpl": output_template,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "windowsfilenames": True,
        "restrictfilenames": True,
        "overwrites": True,
        "max_filesize": MAX_FILESIZE,
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        result = downloader.extract_info(raw_url, download=True)

    candidates = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"]
    if not candidates:
        raise ValueError("Файл был обработан, но итоговый MP4 не найден")

    output = max(candidates, key=lambda path: path.stat().st_size)
    title = result.get("title") or metadata.get("title") or "video"
    return output, _safe_filename(title)


def _download_audio(raw_url: str, bitrate: int, directory: Path) -> tuple[Path, str]:
    _extract_metadata(raw_url)
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(directory / "audio.%(ext)s"),
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "overwrites": True,
        "max_filesize": MAX_FILESIZE,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": str(bitrate),
        }],
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        result = downloader.extract_info(raw_url, download=True)

    candidates = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".mp3"]
    if not candidates:
        raise ValueError("Аудиодорожка была обработана, но итоговый MP3 не найден")
    output = max(candidates, key=lambda path: path.stat().st_size)
    return output, _safe_filename(result.get("title") or "audio").removesuffix(".mp4") + ".mp3"


def _download_audio_for_transcription(raw_url: str, directory: Path) -> tuple[Path, str]:
    _extract_metadata(raw_url, MAX_TRANSCRIPTION_DURATION_SECONDS)
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(directory / "speech.%(ext)s"),
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "overwrites": True,
        "max_filesize": MAX_FILESIZE,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        result = downloader.extract_info(raw_url, download=True)
    candidates = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".wav"]
    if not candidates:
        raise ValueError("Не удалось подготовить аудио для распознавания")
    return max(candidates, key=lambda path: path.stat().st_size), result.get("title") or "transcript"


@lru_cache(maxsize=1)
def _whisper_model():
    from faster_whisper import WhisperModel

    model_name = os.getenv("WHISPER_MODEL", "small")
    return WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=max(1, (os.cpu_count() or 2) - 1))


def _timestamp(seconds: float, separator: str = ",") -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"


def _render_transcript(segments: list[Any], output_format: str) -> str:
    if output_format == "txt":
        return "\n".join(segment.text.strip() for segment in segments if segment.text.strip()) + "\n"
    if output_format == "vtt":
        blocks = ["WEBVTT", ""]
        for segment in segments:
            text = segment.text.strip()
            if text:
                blocks.extend([f"{_timestamp(segment.start, '.')} --> {_timestamp(segment.end, '.')}", text, ""])
        return "\n".join(blocks)

    blocks = []
    for index, segment in enumerate(segments, start=1):
        text = segment.text.strip()
        if text:
            blocks.extend([str(index), f"{_timestamp(segment.start)} --> {_timestamp(segment.end)}", text, ""])
    return "\n".join(blocks)


def _transcribe(raw_url: str, language: str, output_format: str, directory: Path) -> tuple[Path, str, str]:
    audio, title = _download_audio_for_transcription(raw_url, directory)
    model = _whisper_model()
    selected_language = None if language == "auto" else language
    segment_stream, info = model.transcribe(
        str(audio),
        language=selected_language,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    segments = list(segment_stream)
    transcript = _render_transcript(segments, output_format)
    output = directory / f"transcript.{output_format}"
    output.write_text(transcript, encoding="utf-8")
    filename = _safe_filename(title).removesuffix(".mp4") + f".{output_format}"
    return output, filename, info.language


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
        "max_duration_seconds": MAX_DURATION_SECONDS,
    }


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    raw_url = _validate_public_url(str(request.url))
    try:
        return await asyncio.to_thread(_metadata_payload, raw_url)
    except HTTPException:
        raise
    except Exception as error:
        raise _friendly_error(error) from error


@app.get("/api/download/video", response_class=FileResponse)
async def download_video(
    url: str = Query(min_length=10, max_length=4096),
    quality: int = Query(default=1080, ge=144, le=4320),
) -> FileResponse:
    raw_url = _validate_public_url(url)
    if shutil.which("ffmpeg") is None:
        raise HTTPException(status_code=503, detail="FFmpeg не установлен или не добавлен в PATH")

    directory = Path(tempfile.mkdtemp(prefix="video-toolbox-"))
    try:
        async with DOWNLOADS:
            output, filename = await asyncio.to_thread(_download_video, raw_url, quality, directory)
        return FileResponse(
            path=output,
            media_type="video/mp4",
            filename=filename,
            background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
        )
    except Exception as error:
        shutil.rmtree(directory, ignore_errors=True)
        if isinstance(error, HTTPException):
            raise
        raise _friendly_error(error) from error


@app.get("/api/download/audio", response_class=FileResponse)
async def download_audio(
    url: str = Query(min_length=10, max_length=4096),
    bitrate: int = Query(default=192),
) -> FileResponse:
    raw_url = _validate_public_url(url)
    if bitrate not in {128, 192, 320}:
        raise HTTPException(status_code=400, detail="Доступный битрейт: 128, 192 или 320 kbps")
    if shutil.which("ffmpeg") is None:
        raise HTTPException(status_code=503, detail="FFmpeg не установлен или не добавлен в PATH")

    directory = Path(tempfile.mkdtemp(prefix="video-toolbox-audio-"))
    try:
        async with DOWNLOADS:
            output, filename = await asyncio.to_thread(_download_audio, raw_url, bitrate, directory)
        return FileResponse(
            path=output,
            media_type="audio/mpeg",
            filename=filename,
            background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
        )
    except Exception as error:
        shutil.rmtree(directory, ignore_errors=True)
        if isinstance(error, HTTPException):
            raise
        raise _friendly_error(error) from error


@app.get("/api/transcribe", response_class=FileResponse)
async def transcribe_video(
    url: str = Query(min_length=10, max_length=4096),
    language: str = Query(default="auto", pattern="^(auto|ru|en|sl)$"),
    output_format: str = Query(default="txt", pattern="^(txt|srt|vtt)$"),
) -> FileResponse:
    raw_url = _validate_public_url(url)
    if shutil.which("ffmpeg") is None:
        raise HTTPException(status_code=503, detail="FFmpeg не установлен или не добавлен в PATH")

    directory = Path(tempfile.mkdtemp(prefix="video-toolbox-transcript-"))
    try:
        async with TRANSCRIPTIONS:
            output, filename, detected_language = await asyncio.to_thread(
                _transcribe, raw_url, language, output_format, directory
            )
        return FileResponse(
            path=output,
            media_type="text/plain; charset=utf-8",
            filename=filename,
            headers={"X-Detected-Language": detected_language},
            background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
        )
    except Exception as error:
        shutil.rmtree(directory, ignore_errors=True)
        if isinstance(error, HTTPException):
            raise
        raise _friendly_error(error) from error


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
