from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import FrameEvidence, TranscriptSegment
from .settings import Settings


def _browser_cookie_option(settings: Settings) -> tuple[str, ...] | None:
    if not settings.cookies_from_browser:
        return None
    return tuple(part.strip() for part in settings.cookies_from_browser.split(":") if part.strip())


def _yt_dlp_options(settings: Settings) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "noprogress": True,
        "logtostderr": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 2,
    }
    if settings.cookies_file:
        options["cookiefile"] = str(settings.cookies_file)
    browser = _browser_cookie_option(settings)
    if browser:
        options["cookiesfrombrowser"] = browser
    return options


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


_MEDIA_EXTENSIONS = {".aac", ".flac", ".m4a", ".m4v", ".mka", ".mkv", ".mov", ".mp3", ".mp4",
                     ".ogg", ".opus", ".ts", ".wav", ".webm", ".flv"}
_VIDEO_FORMAT = "bv[ext=mp4][height<=720]/b[ext=mp4][height<=720]/bv[height<=720]/b[height<=720]/worstvideo/worst"


def _cached_media(directory: Path, stem: str) -> Path | None:
    return next((p for p in sorted(directory.glob(f"{stem}.*"))
                 if p.stem == stem and p.suffix.lower() in _MEDIA_EXTENSIONS
                 and p.is_file() and p.stat().st_size > 0), None)


def _download_media(url: str, out_dir: Path, settings: Settings, stem: str,
                    format_selector: str) -> tuple[Path | None, list[str]]:
    try:
        import yt_dlp
    except ImportError:
        return None, ["yt-dlp is not installed"]

    out_dir.mkdir(parents=True, exist_ok=True)
    existing = _cached_media(out_dir, stem)
    if existing:
        return existing, []

    try:
        with tempfile.TemporaryDirectory(dir=out_dir) as work:
            options = _yt_dlp_options(settings)
            options.update(format=format_selector, outtmpl=str(Path(work) / f"{stem}.%(ext)s"))
            with yt_dlp.YoutubeDL(options) as ydl:
                if ydl.download([url]):
                    return None, [f"{stem} download failed"]
            completed = _cached_media(Path(work), stem)
            if not completed:
                return None, [f"{stem} download returned no media file"]
            target = out_dir / completed.name
            os.replace(completed, target)
            return target, []
    except Exception as exc:
        return None, [f"{stem} download failed: {exc}"]


def download_audio(url: str, out_dir: Path, settings: Settings) -> tuple[Path | None, list[str]]:
    return _download_media(url, out_dir, settings, "audio", "ba/b")


def convert_to_wav(audio_path: Path, out_dir: Path) -> tuple[Path | None, list[str]]:
    if audio_path.suffix.lower() == ".wav":
        return audio_path, []
    if not command_available("ffmpeg"):
        return audio_path, ["ffmpeg is not installed, using the original audio file"]
    wav_path = out_dir / "audio.wav"
    if wav_path.is_file() and wav_path.stat().st_size > 44:
        return wav_path, []
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_dir) as work:
        pending = Path(work) / "audio.wav"
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(audio_path),
             "-vn", "-ac", "1", "-ar", "16000", str(pending)],
            capture_output=True,
        )
        if result.returncode or not pending.exists() or pending.stat().st_size <= 44:
            detail = result.stderr[-400:].decode("utf-8", errors="replace")
            return audio_path, [f"ffmpeg audio conversion failed: {detail}"]
        os.replace(pending, wav_path)
    return wav_path, []


@lru_cache(maxsize=2)
def _load_whisper_model(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    try:
        return WhisperModel(model_name, device=device, compute_type=compute_type, local_files_only=True)
    except FileNotFoundError:
        return WhisperModel(model_name, device=device, compute_type=compute_type)
    except OSError as exc:
        # Hub uses LocalEntryNotFoundError for a cold model cache.
        if type(exc).__name__ != "LocalEntryNotFoundError":
            raise
        return WhisperModel(model_name, device=device, compute_type=compute_type)


def transcribe_audio(
    audio_path: Path,
    settings: Settings,
) -> tuple[list[TranscriptSegment], list[str]]:
    warnings: list[str] = []
    try:
        import torch
        use_cuda = bool(torch.cuda.is_available())
    except ImportError:
        use_cuda = False

    device = os.environ.get("VIDBRIEF_WHISPER_DEVICE")
    if not device:
        device = "cuda" if use_cuda else "cpu"
    compute_type = os.environ.get(
        "VIDBRIEF_WHISPER_COMPUTE_TYPE",
        "float16" if device == "cuda" else "int8",
    )
    try:
        model = _load_whisper_model(settings.whisper_model, device, compute_type)
        segments, _info = model.transcribe(
            str(audio_path),
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
        )
        result = [
            TranscriptSegment(
                start=float(segment.start),
                end=float(segment.end),
                text=str(segment.text).strip(),
                source="asr",
            )
            for segment in segments
            if str(segment.text).strip()
        ]
        return result, warnings
    except ImportError:
        return [], ["faster-whisper is not installed"]
    except Exception as exc:
        return [], [f"local ASR failed: {exc}"]


def download_video(url: str, out_dir: Path, settings: Settings) -> tuple[Path | None, list[str]]:
    # Frames need only the video stream. Bilibili often exposes DASH as separate tracks.
    return _download_media(url, out_dir, settings, "video", _VIDEO_FORMAT)


_FRAME_PTS = re.compile(rb"\bn:\s*0\s+pts:\s*-?\d+\s+pts_time:(\S+)")


def _frame_at(video_path: Path, frame_dir: Path, target: float) -> tuple[FrameEvidence | None, str | None]:
    # Cache both the requested seek and the PTS of the frame actually selected.
    prefix = f"at_{target:.9f}_pts_"
    for cached in frame_dir.glob(f"{prefix}*.jpg"):
        if cached.is_file() and cached.stat().st_size:
            try:
                return FrameEvidence(float(cached.stem[len(prefix):]), str(cached.resolve())), None
            except ValueError:
                continue

    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info", "-nostats",
         "-copyts", "-start_at_zero", "-ss", f"{target:.9f}", "-i", str(video_path),
         "-map", "0:v:0", "-an", "-vf", "scale=w='min(1024,iw)':h=-2,showinfo",
         "-frames:v", "1", "-fps_mode", "passthrough", "-q:v", "3",
         "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
        capture_output=True,
    )
    pts = _FRAME_PTS.search(completed.stderr)
    log = completed.stderr.lower()
    if not completed.stdout and (completed.returncode == 0 or b"could not open encoder before eof" in log):
        return None, None
    if completed.returncode or not pts or not completed.stdout.endswith(b"\xff\xd9"):
        detail = completed.stderr[-500:].decode("utf-8", errors="replace")
        return None, f"ffmpeg frame extraction failed: {detail}"
    timestamp = float(pts[1])
    target_file = frame_dir / f"{prefix}{timestamp:.9f}.jpg"
    with tempfile.NamedTemporaryFile(dir=frame_dir, suffix=".tmp", delete=False) as output:
        pending = Path(output.name)
        try:
            output.write(completed.stdout)
        except Exception:
            output.close()
            pending.unlink(missing_ok=True)
            raise
    try:
        os.replace(pending, target_file)
    finally:
        pending.unlink(missing_ok=True)
    return FrameEvidence(timestamp, str(target_file.resolve())), None


def extract_frames(
    video_path: Path,
    out_dir: Path,
    start: float = 0.0,
    end: float | None = None,
    interval: float = 15.0,
    max_frames: int = 24,
) -> tuple[list[FrameEvidence], list[str]]:
    if not command_available("ffmpeg"):
        return [], ["ffmpeg is not installed, frame extraction is unavailable"]
    if not math.isfinite(start) or start < 0 or not math.isfinite(interval) or interval <= 0:
        return [], ["frame start and interval must be finite, with start >= 0 and interval > 0"]
    if end is not None and (not math.isfinite(end) or end <= start):
        return [], ["frame end must be finite and greater than start"]
    if max_frames < 1:
        return [], ["max_frames must be positive"]

    frames: list[FrameEvidence] = []
    try:
        stat = video_path.stat()
        identity = f"{video_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        frame_dir = out_dir / "frames" / key
        frame_dir.mkdir(parents=True, exist_ok=True)
        for index in range(max_frames):
            target = start + index * interval
            if end is not None and target >= end:
                break
            frame, error = _frame_at(video_path, frame_dir, target)
            if error:
                return frames, [error]
            if frame is None or (end is not None and frame.timestamp >= end):
                break
            if not frames or frame.timestamp != frames[-1].timestamp:
                frames.append(frame)
    except (OSError, ValueError) as exc:
        return frames, [f"frame extraction failed: {exc}"]
    return frames, [] if frames else ["no video frames in the requested range"]
