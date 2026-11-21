from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrameEvidence:
    timestamp: float
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VideoMetadata:
    url: str
    title: str
    video_id: str
    uploader: str | None
    duration: float | None
    description: str
    page: int
    webpage_url: str
    pages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DigestResult:
    status: str
    title: str
    url: str
    video_id: str
    page: int
    duration: float | None
    data_source: str
    summary_markdown: str
    transcript_segments: list[TranscriptSegment] = field(default_factory=list)
    frames: list[FrameEvidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["transcript_segments"] = [
            segment.to_dict() for segment in self.transcript_segments
        ]
        result["frames"] = [frame.to_dict() for frame in self.frames]
        return result

