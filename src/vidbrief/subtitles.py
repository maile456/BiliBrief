from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .models import TranscriptSegment
from .settings import Settings

_TIME_RE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
)
_TRACK_FORMATS = ("srt", "vtt", "json3", "json", "ass")

def parse_timestamp(value: str | float | int) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    match = _TIME_RE.search(value.strip().replace(",", "."))
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int((match.group(4) or "0").ljust(3, "0"))
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _clean_text(text: str) -> str:
    text = re.sub(r"<\/?[^>]+>", "", text)
    text = text.replace("\\N", " ").replace("\n", " ")
    text = re.sub(r"\\{.*?}", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_vtt_or_srt(text: str, source: str) -> list[TranscriptSegment]:
    lines = [line.strip("\ufeff") for line in text.splitlines()]
    segments: list[TranscriptSegment] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        left, right = [part.strip() for part in line.split("-->", 1)]
        right = right.split(" ", 1)[0]
        start = parse_timestamp(left)
        end = parse_timestamp(right)
        index += 1
        content: list[str] = []
        while index < len(lines) and lines[index].strip():
            content.append(lines[index].strip())
            index += 1
        value = _clean_text(" ".join(content))
        if value and end >= start:
            segments.append(TranscriptSegment(start, end, value, source))
        index += 1
    return _deduplicate(segments)


def parse_ass(text: str, source: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for line in text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            continue
        start = parse_timestamp(fields[1])
        end = parse_timestamp(fields[2])
        value = _clean_text(fields[9])
        if value:
            segments.append(TranscriptSegment(start, end, value, source))
    return _deduplicate(segments)


def parse_json_subtitle(value: Any, source: str) -> list[TranscriptSegment]:
    if isinstance(value, dict) and isinstance(value.get("body"), list):
        segments = [
            TranscriptSegment(
                float(item.get("from", 0)),
                float(item.get("to", item.get("from", 0))),
                _clean_text(str(item.get("content", ""))),
                source,
            )
            for item in value["body"]
        ]
        return _deduplicate([item for item in segments if item.text])

    if isinstance(value, dict) and isinstance(value.get("events"), list):
        segments: list[TranscriptSegment] = []
        for event in value["events"]:
            parts = event.get("segs") or []
            text = _clean_text("".join(str(part.get("utf8", "")) for part in parts))
            if not text:
                continue
            start = float(event.get("tStartMs", 0)) / 1000
            end = start + float(event.get("dDurationMs", 0)) / 1000
            segments.append(TranscriptSegment(start, end, text, source))
        return _deduplicate(segments)

    return []


def parse_subtitle_file(path: Path, source: str) -> list[TranscriptSegment]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    suffix = path.suffix.lower()
    if suffix in {".vtt", ".srt"}:
        return parse_vtt_or_srt(raw, source)
    if suffix == ".ass":
        return parse_ass(raw, source)
    try:
        return parse_json_subtitle(json.loads(raw), source)
    except json.JSONDecodeError:
        return parse_vtt_or_srt(raw, source)


def _deduplicate(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    result: list[TranscriptSegment] = []
    for segment in sorted(segments, key=lambda item: (item.start, item.end)):
        if result and segment.text == result[-1].text:
            result[-1].end = max(result[-1].end, segment.end)
            continue
        result.append(segment)
    return result



def _options(settings: Settings) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True, "no_warnings": True, "noprogress": True, "logtostderr": True,
        "noplaylist": True, "skip_download": True,
        "writesubtitles": True, "writeautomaticsub": True,
        "retries": 2,
    }
    if settings.cookies_file:
        options["cookiefile"] = str(settings.cookies_file)
    if settings.cookies_from_browser:
        options["cookiesfrombrowser"] = tuple(
            p.strip() for p in settings.cookies_from_browser.split(":") if p.strip()
        )
    return options


def _tracks(info: dict[str, Any]):
    """Yield supported tracks in human Chinese, AI Chinese, then fallback order."""
    candidates = []
    for key in ("subtitles", "automatic_captions"):
        for language, formats in (info.get(key) or {}).items():
            if not isinstance(language, str) or not re.fullmatch(r"[\w-]+", language):
                continue
            tag = language.lower().replace("_", "-")
            if tag in {"danmaku", "live-chat"}:
                continue
            auto = key == "automatic_captions" or tag.startswith("ai-")
            locale = tag.removeprefix("ai-")
            chinese = locale.split("-")[0] in {"zh", "cmn", "yue"}
            preferred = locale in {"zh", "zh-hans", "zh-cn"} if chinese else locale.startswith("en")
            if not isinstance(formats, list):
                continue
            for track in formats:
                if not isinstance(track, dict):
                    continue
                ext = str(track.get("ext", "")).lower()
                if ext not in _TRACK_FORMATS or not (track.get("data") or track.get("url")):
                    continue
                priority = (not chinese, auto, not preferred, locale, not bool(track.get("data")),
                            _TRACK_FORMATS.index(ext))
                candidates.append((priority, tag, auto, ext, track))
    return sorted(candidates, key=lambda item: item[0])


def _parse_track(raw: str, ext: str, source: str) -> list[TranscriptSegment]:
    if ext == "ass":
        return parse_ass(raw, source)
    if ext in {"srt", "vtt"}:
        return parse_vtt_or_srt(raw, source)
    return parse_json_subtitle(json.loads(raw.lstrip("\ufeff")), source)


def _cache_track(path: Path, raw: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(raw)
        tmp_path.replace(path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def fetch_transcript(
    url: str,
    out_dir: Path,
    settings: Settings,
    info: dict[str, Any] | None = None,
) -> tuple[list[TranscriptSegment], str, list[str]]:
    try:
        import yt_dlp
        from yt_dlp.networking import Request
    except ImportError:
        return [], "none", ["yt-dlp is not installed"]

    warnings: list[str] = []
    if info is None:
        try:
            with yt_dlp.YoutubeDL(_options(settings)) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            return [], "none", [f"subtitle metadata lookup failed ({type(exc).__name__})"]
    candidates = _tracks(info or {})
    if not candidates:
        return [], "none", ["no usable subtitle tracks were advertised by the video"]

    # The Bilibili extractor already downloads captions into track["data"].
    # URL-only extractor versions need a request for just the selected track.
    _, language, auto, ext, track = candidates[0]
    source = "ai_subtitle" if auto else "subtitle"
    prefix = "subtitle-auto" if auto else "subtitle-human"
    path = out_dir / f"{prefix}.{language}.{ext}"
    if path.is_file():
        try:
            cached = parse_subtitle_file(path, source)
            if cached:
                return cached, source, warnings
        except (OSError, TypeError, ValueError, AttributeError):
            pass

    try:
        raw = track.get("data")
        if not raw:
            headers = {"Referer": url, **(track.get("http_headers") or {})}
            remote = track["url"]
            if remote.startswith("//"):
                remote = f"https:{remote}"
            if not remote.startswith(("https://", "http://")):
                return [], "none", ["unsupported subtitle URL"]
            with yt_dlp.YoutubeDL(_options(settings)) as ydl:
                with ydl.urlopen(Request(remote, headers=headers)) as response:
                    raw = response.read().decode("utf-8-sig")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        segments = _parse_track(raw, ext, source)
    except Exception as exc:
        return [], "none", [f"could not read {language} subtitles ({type(exc).__name__})"]
    if not segments:
        return [], "none", [f"the {language} subtitle track contains no usable cues"]
    try:
        _cache_track(path, raw)
    except OSError:
        warnings.append("subtitle parsed but its local cache could not be written")
    return segments, source, warnings
