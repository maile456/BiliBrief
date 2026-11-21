from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _optional_path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    cache_dir: Path
    cookies_from_browser: str | None = None
    cookies_file: Path | None = None
    whisper_model: str = "small"
    max_duration_seconds: int = 14_400
    max_frames: int = 24
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    @classmethod
    def from_env(cls) -> "Settings":
        default_cache = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home()))
        ) / "VidBrief" / "cache"
        return cls(
            cache_dir=_optional_path(os.environ.get("VIDBRIEF_CACHE_DIR"))
            or default_cache,
            cookies_from_browser=os.environ.get("VIDBRIEF_COOKIES_FROM_BROWSER") or None,
            cookies_file=_optional_path(os.environ.get("VIDBRIEF_COOKIES_FILE")),
            whisper_model=os.environ.get("VIDBRIEF_WHISPER_MODEL", "small"),
            max_duration_seconds=int(
                os.environ.get("VIDBRIEF_MAX_DURATION_SECONDS", "14400")
            ),
            max_frames=int(os.environ.get("VIDBRIEF_MAX_FRAMES", "24")),
            llm_base_url=os.environ.get("VIDBRIEF_LLM_BASE_URL") or None,
            llm_api_key=os.environ.get("VIDBRIEF_LLM_API_KEY") or None,
            llm_model=os.environ.get("VIDBRIEF_LLM_MODEL", "gpt-4o-mini"),
        )

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

