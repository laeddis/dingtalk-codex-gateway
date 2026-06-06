from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CODEX_CONFIG = Path(os.environ.get("CODEX_CONFIG", "/root/.codex/config.toml"))


@dataclass(frozen=True)
class Workspace:
    name: str
    path: Path
    timezone: str
    allowed_write_paths: tuple[Path, ...]
    stores: tuple[str, ...]


def load_workspaces(path: Path | None = None) -> dict[str, Workspace]:
    config_path = path or PROJECT_ROOT / "config" / "workspaces.json"
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    workspaces: dict[str, Workspace] = {}
    for name, data in raw.items():
        workspaces[name] = Workspace(
            name=name,
            path=Path(data["path"]),
            timezone=data.get("timezone", "America/New_York"),
            allowed_write_paths=tuple(Path(p) for p in data.get("allowed_write_paths", [])),
            stores=tuple(data.get("stores", [])),
        )
    return workspaces


def load_codex_mcp_env(server_name: str, config_path: Path | None = None) -> dict[str, str]:
    path = config_path or DEFAULT_CODEX_CONFIG
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    server = (data.get("mcp_servers") or {}).get(server_name) or {}
    env = server.get("env") or {}
    return {str(k): str(v) for k, v in env.items()}


def public_config_snapshot() -> dict[str, Any]:
    """Return non-secret config details for /health diagnostics."""
    workspaces = load_workspaces()
    return {
        "project_root": str(PROJECT_ROOT),
        "workspaces": sorted(workspaces.keys()),
        "stores_configured": {
            "shopline": bool(load_codex_mcp_env("shopline").get("SHOPLINE_ACCESS_TOKEN")),
            "shoplazza": bool(load_codex_mcp_env("shoplazza").get("SHOPLAZZA_ACCESS_TOKEN")),
        },
    }
