from __future__ import annotations

from math import isfinite
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .cache import CacheStore
from .links import list_parts, normalize
from .llm import make_digest
from .media import (
    convert_to_wav,
    download_audio,
    download_video,
    extract_frames,
    transcribe_audio,
)
from .models import (
    DigestResult,
    FrameEvidence,
    TranscriptSegment,
    VideoMetadata,
)
from .settings import Settings
from .subtitles import fetch_transcript


class PipelineError(RuntimeError):
    pass


def _page_url(url: str, page: int) -> str:
    if page <= 1:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["p"] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _yt_options(settings: Settings) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logtostderr": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "skip_download": True,
        "socket_timeout": 15,
        "noplaylist": True,
        "retries": 2,
    }
    if settings.cookies_file:
        options["cookiefile"] = str(settings.cookies_file)
    if settings.cookies_from_browser:
        options["cookiesfrombrowser"] = tuple(
            part.strip()
            for part in settings.cookies_from_browser.split(":")
            if part.strip()
        )
    return options


def _raw_info(url: str, settings: Settings) -> dict[str, Any]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise PipelineError("yt-dlp is not installed") from exc
    try:
        with yt_dlp.YoutubeDL(_yt_options(settings)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise PipelineError(f"B 站视频读取失败：{exc}") from exc
    if not isinstance(info, dict) or info.get("_type") in {"playlist", "multi_video"}:
        raise PipelineError("yt-dlp returned no video metadata")
    return info


def _page_list(info: dict[str, Any]) -> list[dict[str, Any]]:
    entries = info.get("entries")
    if not entries:
        return []
    pages: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        if not entry:
            continue
        pages.append(
            {
                "page": index,
                "id": entry.get("id"),
                "title": entry.get("title"),
                "duration": entry.get("duration"),
            }
        )
    return pages


def resolve_video(
    url: str,
    page: int | None,
    settings: Settings,
) -> tuple[VideoMetadata, dict[str, Any], CacheStore]:
    url, page = normalize(url, page)
    requested_url = _page_url(url, page)
    store = CacheStore(settings, url, page, "default")
    cached = store.read_json("metadata.json")
    if cached and cached.get("_raw_info", {}).get("subtitle_probe_version") == 1:
        metadata_payload = {
            key: value for key, value in cached.items() if key != "_raw_info"
        }
        metadata = VideoMetadata(**metadata_payload)
        return metadata, cached.get("_raw_info", {}), store

    info = _raw_info(requested_url, settings)
    duration = info.get("duration")
    if duration is not None and float(duration) > settings.max_duration_seconds:
        raise PipelineError(
            f"video duration exceeds VIDBRIEF_MAX_DURATION_SECONDS={settings.max_duration_seconds}"
        )

    bvid = str(info.get("id") or "").split("_p")[0]
    pages = _page_list(info) or list_parts(bvid)
    if pages and page not in {r["page"] for r in pages}:
        raise PipelineError(f"视频共有 {len(pages)} P，没有第 {page} P。")
    metadata = VideoMetadata(
        url=url.strip(),
        title=str(info.get("title") or "Untitled video"),
        video_id=bvid,
        uploader=info.get("uploader") or info.get("channel"),
        duration=float(duration) if duration is not None else None,
        description=str(info.get("description") or ""),
        page=page,
        webpage_url=requested_url,
        pages=pages,
    )
    payload = metadata.to_dict()
    payload["_raw_info"] = {
        "subtitle_probe_version": 1,
        "id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "subtitles": info.get("subtitles") or {},
        "automatic_captions": info.get("automatic_captions") or {},
    }
    store.write_json("metadata.json", payload)
    return metadata, payload["_raw_info"], store


def transcript_for(
    url: str,
    page: int,
    settings: Settings,
    metadata: VideoMetadata,
    raw_info: dict[str, Any],
    store: CacheStore,
) -> tuple[list[TranscriptSegment], str, list[str]]:
    cached = store.read_json("transcript.json")
    if (cached and cached.get("segments") and
            (cached.get("source") != "asr" or cached.get("model") == settings.whisper_model)):
        return (
            [TranscriptSegment(**item) for item in cached["segments"]],
            str(cached["source"]),
            list(cached.get("warnings", [])),
        )

    segment_dir = store.path("media")
    segments, source, warnings = fetch_transcript(
        metadata.webpage_url,
        segment_dir,
        settings,
        raw_info,
    )
    if not segments:
        audio_path, audio_warnings = download_audio(
            metadata.webpage_url,
            segment_dir,
            settings,
        )
        warnings.extend(audio_warnings)
        if audio_path:
            wav_path, conversion_warnings = convert_to_wav(audio_path, segment_dir)
            warnings.extend(conversion_warnings)
            if wav_path:
                segments, asr_warnings = transcribe_audio(wav_path, settings)
                warnings.extend(asr_warnings)
                if segments:
                    source = "asr"

    store.write_json(
        "transcript.json",
        {
            "source": source,
            "model": settings.whisper_model if source == "asr" else None,
            "segments": [segment.to_dict() for segment in segments],
            "warnings": warnings,
        },
    )
    return segments, source, warnings


def _frame_interval(duration: float | None, max_frames: int) -> float:
    if not duration or duration <= 0:
        return 15.0
    return max(10.0, duration / max(1, max_frames))


def digest_video(
    url: str,
    page: int,
    detail: str,
    visual: str,
    settings: Settings,
) -> DigestResult:
    metadata, raw_info, store = resolve_video(url, page, settings)
    segments, source, warnings = transcript_for(
        url,
        page,
        settings,
        metadata,
        raw_info,
        store,
    )

    frames: list[FrameEvidence] = []
    should_extract = visual == "always" or (
        visual == "auto" and len(segments) < 3 and metadata.duration is not None
    )
    if should_extract:
        video_path, video_warnings = download_video(
            metadata.webpage_url,
            store.path("media"),
            settings,
        )
        warnings.extend(video_warnings)
        if video_path:
            frames, frame_warnings = extract_frames(
                video_path,
                store.path("media"),
                interval=_frame_interval(metadata.duration, settings.max_frames),
                max_frames=settings.max_frames,
            )
            warnings.extend(frame_warnings)
    elif visual == "auto":
        warnings.append("visual pass skipped because a timestamped transcript was available")

    summary = make_digest(
        metadata.title,
        segments,
        source,
        frames,
        warnings,
        settings,
        detail,
        url=metadata.webpage_url,
    )
    digest_path = store.write_text("digest.md", summary)
    store.write_json(
        "timeline.json",
        {
            "metadata": metadata.to_dict(),
            "data_source": source,
            "segments": [segment.to_dict() for segment in segments],
            "frames": [frame.to_dict() for frame in frames],
            "warnings": warnings,
        },
    )
    return DigestResult(
        status="ok" if segments else "partial",
        title=metadata.title,
        url=metadata.url,
        video_id=metadata.video_id,
        page=metadata.page,
        duration=metadata.duration,
        data_source=source,
        summary_markdown=summary,
        transcript_segments=segments,
        frames=frames,
        warnings=warnings,
        artifact_dir=str(digest_path.parent.resolve()),
    )


def window_video(
    url: str,
    page: int,
    start: float,
    end: float,
    interval: float,
    settings: Settings,
) -> dict[str, Any]:
    if not all(map(isfinite, (start, end, interval))) or interval <= 0:
        raise PipelineError("时间须为有限数值，抽帧间隔须大于零。")
    if start < 0 or end <= start:
        raise PipelineError("end must be greater than start and start must be non-negative")
    metadata, raw_info, store = resolve_video(url, page, settings)
    if metadata.duration is not None:
        end = min(end, metadata.duration)
        if start >= end:
            raise PipelineError("所选时间段超出了视频时长。")
    segments, source, warnings = transcript_for(
        url,
        page,
        settings,
        metadata,
        raw_info,
        store,
    )
    selected = [
        segment for segment in segments if segment.end >= start and segment.start <= end
    ]
    video_path, video_warnings = download_video(
        metadata.webpage_url,
        store.path("media"),
        settings,
    )
    warnings.extend(video_warnings)
    frames: list[FrameEvidence] = []
    if video_path:
        frames, frame_warnings = extract_frames(
            video_path,
            store.path("media"),
            start=start,
            end=end,
            interval=interval,
            max_frames=settings.max_frames,
        )
        warnings.extend(frame_warnings)
    return {
        "status": "ok" if frames or selected else "partial",
        "title": metadata.title,
        "video_id": metadata.video_id,
        "page": metadata.page,
        "start": start,
        "end": end,
        "data_source": source,
        "segments": [segment.to_dict() for segment in selected],
        "frames": [frame.to_dict() for frame in frames],
        "warnings": warnings,
        "artifact_dir": str(store.root.resolve()),
    }


def search_video(
    url: str,
    page: int,
    query: str,
    settings: Settings,
) -> dict[str, Any]:
    if not query.strip():
        raise PipelineError("query is required")
    metadata, raw_info, store = resolve_video(url, page, settings)
    segments, source, warnings = transcript_for(
        url,
        page,
        settings,
        metadata,
        raw_info,
        store,
    )
    needle = query.casefold()
    matches = [
        segment.to_dict()
        for segment in segments
        if needle in segment.text.casefold()
    ][:50]
    return {
        "status": "ok" if segments else "partial",
        "title": metadata.title,
        "video_id": metadata.video_id,
        "page": metadata.page,
        "query": query,
        "data_source": source,
        "matches": matches,
        "warnings": warnings,
        "artifact_dir": str(store.root.resolve()),
    }


def metadata_payload(metadata: VideoMetadata) -> dict[str, Any]:
    return metadata.to_dict()

