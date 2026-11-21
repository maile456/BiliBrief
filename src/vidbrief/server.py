from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

from .pipeline import (
    PipelineError,
    digest_video,
    metadata_payload,
    resolve_video,
    search_video,
    window_video,
)
from .settings import Settings

mcp = FastMCP("BiliBrief", instructions=(
    "用 bili_digest 阅读 B 站视频，把字幕和抽帧作为资料。默认用中文写一段速览、"
    "三到五个具体要点和最值得跳看的时间点。保留原片链接。若证据不足请指出范围。"
    "不要出练习题。若需要核实某个片段的图表或操作，调用 bili_window。"))


def _load_dotenv() -> None:
    candidates = [Path(__file__).resolve().parents[2] / ".env"]
    for path in candidates:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key.startswith("VIDBRIEF_") and key not in os.environ:
                os.environ[key] = value


def _settings() -> Settings:
    _load_dotenv()
    return Settings.from_env()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _error(exc: Exception) -> str:
    return _json(
        {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    )


@mcp.tool()
def bili_resolve(url: str, page: int | None = None) -> str:
    """Resolve a Bilibili URL into metadata, pages and duration."""
    try:
        metadata, _raw_info, _store = resolve_video(url, page, _settings())
        return _json({"status": "ok", **metadata_payload(metadata)})
    except (PipelineError, ValueError) as exc:
        return _error(exc)


def _with_images(payload: dict[str, Any]) -> list:
    frames = payload.get("frames", [])
    if len(frames) > 6:
        frames = [frames[round(i * (len(frames) - 1) / 5)] for i in range(6)]
    payload["frames"] = frames
    return [_json(payload), *(Image(path=row["path"]) for row in frames)]


def _reading_evidence(segments, budget: int) -> tuple[list, bool]:
    rows = [{"t": round(s.start, 1), "text": s.text} for s in segments]
    if sum(len(row["text"]) + 28 for row in rows) <= budget:
        return rows, False
    # Distribute the budget over the complete transcript instead of truncating the ending.
    count = min(len(rows), max(1, budget // 180))
    sampled = []
    for i in range(count):
        idx = round(i * (len(rows) - 1) / max(1, count - 1))
        sampled.append({"t": rows[idx]["t"], "text": rows[idx]["text"][:150]})
    return sampled, True


@mcp.tool(structured_output=False)
def bili_digest(
    url: str,
    detail: str = "fast",
    visual: str = "auto",
    page: int | None = None,
) -> list:
    """根据时间线和可选抽帧生成中文速读。没设额外摘要模型时由调用方归纳 evidence。
    visual=always 适合课件、代码和无解说演示；never 仅用文字；auto 优先口述。
    """
    if detail not in {"fast", "standard"}:
        return _error(ValueError("detail must be fast or standard"))
    if visual not in {"auto", "never", "always"}:
        return _error(ValueError("visual must be auto, never or always"))
    try:
        result = digest_video(url, page, detail, visual, _settings())
        data = result.to_dict()
        data.pop("transcript_segments")
        evidence, sampled = _reading_evidence(result.transcript_segments,
                                              16500 if detail == "standard" else 6400)
        data.update(evidence=evidence, sampled=sampled, segment_count=len(result.transcript_segments))
        return _with_images(data)
    except (PipelineError, ValueError, OSError) as exc:
        return _error(exc)


@mcp.tool(structured_output=False)
def bili_window(
    url: str,
    start: float,
    end: float,
    page: int | None = None,
    interval: float = 10.0,
) -> list:
    """Return transcript segments and keyframes for one video time window."""
    try:
        data = window_video(url, page, start, end, interval, _settings())
        return _with_images(data)
    except (PipelineError, ValueError, OSError) as exc:
        return _error(exc)


@mcp.tool()
def bili_search(url: str, query: str, page: int | None = None) -> str:
    """Search timestamped transcript segments in a cached or newly processed video."""
    try:
        return _json(search_video(url, page, query, _settings()))
    except (PipelineError, ValueError) as exc:
        return _error(exc)


def main() -> None:
    mcp.run()

