from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Route:
    command: str
    executor: str
    args: dict


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    command: str
    markdown: str
    report_path: Path | None = None
    data: dict | None = None
