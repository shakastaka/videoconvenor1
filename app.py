from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
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


APP_VERSION = "0.8.0"
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
VIDEO_CACHE_TTL_SECONDS = int(os.getenv("VIDEO_CACHE_TTL_SECONDS", "900"))
VIDEO_CACHE_DIR = Path(tempfile.gettempdir()) / "video-toolbox-video-cache"
VIDEO_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
VIDEO_CACHE_NAMES: dict[str, str] = {}
SUPPORTED_LANGUAGES = {
    "auto", "ru", "en", "sl", "de", "fr", "es", "it", "pt", "pl", "uk",
    "cs", "hr", "sr", "bg", "ro", "tr", "ar", "hi", "zh", "ja", "ko",
}

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
    codec = str(item.get("vcodec") if video else item.get("acodec") or "").lower()
    if video:
        # AVC/H.264 plays on practically every iPhone, Android device and desktop browser.
        codec_score = 2 if ("avc1" in codec or "h264" in codec) else 0
    else:
        codec_score = 2 if ("mp4a" in codec or "aac" in codec) else 0
    return (
        within_target,
        codec_score,
        height if within_target else -height,
        extension_score,
        float(item.get("tbr") or item.get("abr") or 0),
    )


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


def _is_tiktok(info: dict[str, Any]) -> bool:
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    webpage_url = str(info.get("webpage_url") or "").lower()
    return "tiktok" in extractor or "tiktok.com" in webpage_url


def _choose_audio_source(info: dict[str, Any]) -> str:
    """Use TikTok's mixed video track, not its separate full-length music asset."""
    if _is_tiktok(info):
        embedded_audio_formats = [
            item
            for item in _usable_video_formats(info)
            if item.get("acodec") not in {None, "none"}
        ]
        if embedded_audio_formats:
            selected = max(
                embedded_audio_formats,
                key=lambda item: _format_score(item, 1080, True),
            )
            return str(selected["format_id"])
        return "bestvideo*[acodec!=none]/best[acodec!=none]/best"
    return "bestaudio/best"


def _safe_filename(title: str) -> str:
    cleaned = re.sub(r"[^\w\-. ()\[\]]+", "_", title, flags=re.UNICODE).strip(" ._")
    return f"{(cleaned or 'video')[:120]}.mp4"


def _media_codecs(path: Path) -> tuple[str, str]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = json.loads(result.stdout).get("streams") or []
    video_codec = next((str(item.get("codec_name") or "") for item in streams if item.get("codec_type") == "video"), "")
    audio_codec = next((str(item.get("codec_name") or "") for item in streams if item.get("codec_type") == "audio"), "")
    return video_codec.lower(), audio_codec.lower()


def _make_browser_compatible_mp4(source: Path, directory: Path) -> Path:
    """Create an H.264/AAC MP4 with its index at the beginning for mobile Safari."""
    video_codec, audio_codec = _media_codecs(source)
    output = directory / "browser-compatible.mp4"
    command = [
        "ffmpeg", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
    ]
    if video_codec == "h264":
        command.extend(["-c:v", "copy"])
    else:
        command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"])
    if not audio_codec:
        command.extend(["-an"])
    elif audio_codec == "aac":
        command.extend(["-c:a", "copy"])
    else:
        command.extend(["-c:a", "aac", "-b:a", "192k"])
    command.extend(["-movflags", "+faststart", "-max_muxing_queue_size", "4096", str(output)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    if not output.is_file() or output.stat().st_size == 0:
        raise ValueError("Не удалось подготовить совместимый MP4")
    return output


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
    output = _make_browser_compatible_mp4(output, directory)
    title = result.get("title") or metadata.get("title") or "video"
    return output, _safe_filename(title)


def _video_cache_key(raw_url: str, quality: int) -> str:
    return hashlib.sha256(f"{raw_url}\n{quality}".encode("utf-8")).hexdigest()


def _cleanup_video_cache() -> None:
    VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - VIDEO_CACHE_TTL_SECONDS
    for path in VIDEO_CACHE_DIR.glob("*.mp4"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                VIDEO_CACHE_NAMES.pop(path.stem, None)
        except OSError:
            continue


async def _cached_video(raw_url: str, quality: int) -> tuple[Path, str]:
    """Reuse one generated file for Safari's repeated HTTP Range requests."""
    key = _video_cache_key(raw_url, quality)
    VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = VIDEO_CACHE_DIR / f"{key}.mp4"
    lock = VIDEO_CACHE_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        _cleanup_video_cache()
        if cached.is_file() and cached.stat().st_size > 0:
            cached.touch()
            return cached, VIDEO_CACHE_NAMES.get(key, "video.mp4")

        directory = Path(tempfile.mkdtemp(prefix="video-toolbox-build-"))
        temporary = VIDEO_CACHE_DIR / f"{key}.part"
        try:
            output, filename = await asyncio.to_thread(_download_video, raw_url, quality, directory)
            shutil.copyfile(output, temporary)
            temporary.replace(cached)
            VIDEO_CACHE_NAMES[key] = filename
            return cached, filename
        finally:
            temporary.unlink(missing_ok=True)
            shutil.rmtree(directory, ignore_errors=True)


def _download_audio(raw_url: str, bitrate: int, directory: Path) -> tuple[Path, str]:
    metadata = _extract_metadata(raw_url)
    options = {
        "format": _choose_audio_source(metadata),
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
    metadata = _extract_metadata(raw_url, MAX_TRANSCRIPTION_DURATION_SECONDS)
    options = {
        "format": _choose_audio_source(metadata),
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
        beam_size=8,
        patience=1.2,
        temperature=0.0,
        repetition_penalty=1.08,
        no_repeat_ngram_size=3,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 250},
        condition_on_previous_text=True,
        multilingual=selected_language is None,
        language_detection_segments=3,
    )
    segments = [segment for segment in segment_stream if segment.text.strip()]
    if not segments:
        segment_stream, info = model.transcribe(
            str(audio),
            language=selected_language,
            beam_size=8,
            patience=1.2,
            temperature=0.0,
            repetition_penalty=1.08,
            no_repeat_ngram_size=3,
            vad_filter=False,
            condition_on_previous_text=True,
            multilingual=selected_language is None,
            language_detection_segments=3,
        )
        segments = [segment for segment in segment_stream if segment.text.strip()]
    if not segments:
        raise ValueError(
            "В аудиодорожке не удалось распознать речь. Проверьте, что в ролике есть слышимая речь, "
            "или выберите язык вручную."
        )
    transcript = _render_transcript(segments, output_format)
    output = directory / f"transcript.{output_format}"
    # BOM помогает iOS, Windows и простым просмотрщикам всегда распознавать кириллицу как UTF-8.
    output.write_text(transcript, encoding="utf-8-sig")
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

    try:
        async with DOWNLOADS:
            output, filename = await _cached_video(raw_url, quality)
        return FileResponse(
            path=output,
            media_type="video/mp4",
            filename=filename,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Accept-Ranges": "bytes",
            },
        )
    except Exception as error:
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
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
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
    language: str = Query(default="auto", min_length=2, max_length=4),
    output_format: str = Query(default="txt", pattern="^(txt|srt|vtt)$"),
) -> FileResponse:
    raw_url = _validate_public_url(url)
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Выбранный язык пока не поддерживается")
    if shutil.which("ffmpeg") is None:
        raise HTTPException(status_code=503, detail="FFmpeg не установлен или не добавлен в PATH")

    directory = Path(tempfile.mkdtemp(prefix="video-toolbox-transcript-"))
    try:
        async with TRANSCRIPTIONS:
            output, filename, detected_language = await asyncio.to_thread(
                _transcribe, raw_url, language, output_format, directory
            )
        transcript_media_types = {
            "txt": "text/plain; charset=utf-8",
            "srt": "application/x-subrip; charset=utf-8",
            "vtt": "text/vtt; charset=utf-8",
        }
        return FileResponse(
            path=output,
            media_type=transcript_media_types[output_format],
            filename=filename,
            headers={
                "X-Detected-Language": detected_language,
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
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
