from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import PROJECT_ROOT

LOG_PATH = PROJECT_ROOT / "logs" / "commands.jsonl"

SECRETISH_KEYS = {"token", "access_token", "authorization", "secret", "password"}


def append_audit(record: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe = _sanitize(record)
    safe.setdefault("timestamp", datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds"))
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(safe, ensure_ascii=False, sort_keys=True) + "\n")


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in SECRETISH_KEYS):
                out[key] = "[REDACTED]"
            else:
                out[key] = _sanitize(item)
        return out
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "...[truncated]"
    return value
