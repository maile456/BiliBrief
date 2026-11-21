import os
from dataclasses import dataclass
from pathlib import Path


def saved_session_path() -> Path:
    """Return the per-user cookie path used by the local QR login."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "BiliBrief" / "bilibili.cookies.txt"


@dataclass(frozen=True)
class Settings:
    cookies_file: Path | None = None
    cookies_from_browser: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        keys = ("VIDBRIEF_COOKIES_FILE", "VIDBRIEF_COOKIES_FROM_BROWSER")
        values = {key: os.environ[key] for key in keys if key in os.environ}
        dotenv = Path(__file__).resolve().parents[2] / ".env"
        if dotenv.is_file():
            for line in dotenv.read_text(encoding="utf-8-sig").splitlines():
                key, sep, value = line.partition("=")
                key = key.strip()
                if sep and key in keys:
                    values.setdefault(key, value.strip().strip("'\""))
        filename = values.get("VIDBRIEF_COOKIES_FILE")
        cookie_path = Path(filename).expanduser() if filename else saved_session_path()
        return cls(
            cookies_file=cookie_path if cookie_path.is_file() else None,
            cookies_from_browser=values.get("VIDBRIEF_COOKIES_FROM_BROWSER") or None,
        )
