"""Raw payload files under ``discovery/``: ``{"meta": {...}, "payload": ...}`` per domain.

Shared by the discovery command (which writes them) and the report command (which refreshes the
ones it needs and reads them back). Not the audit log — that is ``raw_responses`` in Phase 1.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fantrax_analytics.adapters.http import RawResponse


def save_raw(directory: Path, domain: str, raw: RawResponse) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{domain}.json"
    meta = {k: v for k, v in asdict(raw).items() if k != "payload"}
    meta["fetched_at"] = dt.datetime.now(dt.UTC).isoformat()
    path.write_text(json.dumps({"meta": meta, "payload": raw.payload}, indent=1, default=str), "utf-8")
    return path


def load_raw(directory: Path, domain: str) -> tuple[dict[str, Any], Any] | None:
    """(meta, payload) or None when the file is missing or unreadable."""
    path = directory / f"{domain}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "payload" not in data:
        return None
    raw_meta = data.get("meta")
    meta: dict[str, Any] = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    return meta, data["payload"]
