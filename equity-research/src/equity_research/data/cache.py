"""Disk cache for raw downloads; remembers when each body was fetched (the 'retrieved' date)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DiskCache:
    def __init__(self, root: Path | str, now: Callable[[], datetime] = _utc_now) -> None:
        self._root = Path(root)
        self._now = now

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode()).hexdigest()
        return self._root / f"{key}.body", self._root / f"{key}.json"

    def get(self, url: str, max_age: timedelta | None) -> tuple[bytes, datetime] | None:
        body_path, meta_path = self._paths(url)
        if not body_path.exists() or not meta_path.exists():
            return None
        fetched = datetime.fromisoformat(json.loads(meta_path.read_text())["fetched"])
        if max_age is not None and self._now() - fetched > max_age:
            return None
        return body_path.read_bytes(), fetched

    def put(self, url: str, body: bytes) -> datetime:
        body_path, meta_path = self._paths(url)
        self._root.mkdir(parents=True, exist_ok=True)
        fetched = self._now()
        body_path.write_bytes(body)
        meta_path.write_text(json.dumps({"url": url, "fetched": fetched.isoformat()}))
        return fetched

    def fetch(self, url: str, download: Callable[[str], bytes], max_age: timedelta | None) -> tuple[bytes, datetime]:
        cached = self.get(url, max_age)
        if cached is not None:
            return cached
        body = download(url)
        return body, self.put(url, body)
