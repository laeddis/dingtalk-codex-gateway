from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CODEX_CONFIG = Path(os.environ.get("CODEX_CONFIG", "/root/.codex/config.toml"))
DEFAULT_WORKSPACES_CONFIG = PROJECT_ROOT / "config" / "workspaces.json"


@dataclass(frozen=True)
class AppSettings:
    host: str
    port: int
    api_token: str
    require_auth: bool
    environment: str
    workspaces_config: Path
    default_workspace: str


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("'\"")


def load_app_settings(env_file: Path | None = None) -> AppSettings:
    if env_file:
        load_dotenv(env_file)
    elif os.environ.get("DINGTALK_GATEWAY_ENV_FILE"):
        load_dotenv(Path(os.environ["DINGTALK_GATEWAY_ENV_FILE"]))

    host = os.environ.get("DINGTALK_GATEWAY_HOST", "127.0.0.1")
    port = parse_port(os.environ.get("DINGTALK_GATEWAY_PORT", "8787"))
    api_token = os.environ.get("DINGTALK_GATEWAY_API_TOKEN", "")
    require_auth = parse_bool(os.environ.get("DINGTALK_GATEWAY_REQUIRE_AUTH", "0"))
    environment = os.environ.get("DINGTALK_GATEWAY_ENV", "development")
    workspaces_config = Path(os.environ.get("DINGTALK_GATEWAY_WORKSPACES_CONFIG", str(DEFAULT_WORKSPACES_CONFIG)))
    default_workspace = os.environ.get("DINGTALK_GATEWAY_DEFAULT_WORKSPACE", "default")
    return AppSettings(host, port, api_token, require_auth, environment, workspaces_config, default_workspace)


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid DINGTALK_GATEWAY_PORT: {value}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid DINGTALK_GATEWAY_PORT: {value}")
    return port


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def validate_server_settings(settings: AppSettings) -> None:
    if not is_loopback_host(settings.host) and not settings.api_token and not settings.require_auth:
        raise RuntimeError(
            "Refusing to bind a non-loopback host without DINGTALK_GATEWAY_API_TOKEN "
            "or DINGTALK_GATEWAY_REQUIRE_AUTH=1."
        )
    if settings.require_auth and not settings.api_token:
        raise RuntimeError("DINGTALK_GATEWAY_REQUIRE_AUTH=1 requires DINGTALK_GATEWAY_API_TOKEN.")


@dataclass(frozen=True)
class Workspace:
    name: str
    path: Path
    timezone: str
    allowed_write_paths: tuple[Path, ...]
    stores: tuple[str, ...]


def load_workspaces(path: Path | None = None) -> dict[str, Workspace]:
    config_path = path or Path(os.environ.get("DINGTALK_GATEWAY_WORKSPACES_CONFIG", str(DEFAULT_WORKSPACES_CONFIG)))
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
    if not path.exists():
        return {}
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
