from __future__ import annotations

import hashlib
import json
import os
from tempfile import NamedTemporaryFile
from pathlib import Path
from typing import Any

from .settings import Settings


def cache_key(url: str, page: int = 1, profile: str = "default") -> str:
    raw = f"{url.strip()}\npage={page}\nprofile={profile}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class CacheStore:
    def __init__(self, settings: Settings, url: str, page: int, profile: str):
        settings.ensure_dirs()
        self.root = settings.cache_dir / cache_key(url, page, profile)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        target = (self.root / name).resolve()
        if self.root.resolve() not in target.parents and target != self.root.resolve():
            raise ValueError("Cache artifact escapes its cache directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_json(self, name: str, value: Any) -> Path:
        return self.write_text(name, json.dumps(value, ensure_ascii=False, indent=2))

    def read_json(self, name: str) -> Any | None:
        target = self.path(name)
        if not target.exists():
            return None
        return json.loads(target.read_text(encoding="utf-8"))

    def write_text(self, name: str, value: str) -> Path:
        target = self.path(name)
        with NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
            pending = Path(tmp.name)
            try:
                tmp.write(value.encode("utf-8"))
            except OSError:
                tmp.close()
                pending.unlink(missing_ok=True)
                raise
        try:
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
        return target

    def read_text(self, name: str) -> str | None:
        target = self.path(name)
        if not target.exists():
            return None
        return target.read_text(encoding="utf-8")

