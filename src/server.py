from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .audit import append_audit
from .config import AppSettings, load_app_settings, public_config_snapshot, validate_server_settings
from .router import execute_route, route_text

HOST = "127.0.0.1"
PORT = 8787


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "DingTalkCodexGateway/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            settings = self.get_settings()
            self.write_json({"ok": True, "environment": settings.environment, **public_config_snapshot()})
            return
        self.write_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/local/message":
            self.write_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        if not self.is_authorized():
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            payload = self.read_json()
            workspace = str(payload.get("workspace") or "cuticlub")
            sender = str(payload.get("sender") or "local-user")
            text = str(payload.get("text") or "")
            if not text.strip():
                self.write_json({"ok": False, "error": "empty_text"}, HTTPStatus.BAD_REQUEST)
                return

            route = route_text(text)
            result = execute_route(workspace, text)
            response: dict[str, Any] = {
                "ok": result.ok,
                "command": result.command,
                "executor": route.executor,
                "markdown": result.markdown,
            }
            if result.report_path:
                response["report_path"] = str(result.report_path)
            append_audit({
                "source": "local_test",
                "workspace": workspace,
                "sender": sender,
                "raw_text": text,
                "normalized_command": result.command,
                "executor": route.executor,
                "status": "success" if result.ok else "failed_or_rejected",
                "report_path": str(result.report_path) if result.report_path else None,
            })
            self.write_json(response)
        except Exception as exc:  # Keep local gateway alive and return sanitized errors.
            append_audit({"source": "local_test", "status": "error", "error": str(exc)})
            self.write_json({"ok": False, "error": type(exc).__name__, "message": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def get_settings(self) -> AppSettings:
        return getattr(self.server, "settings", load_app_settings())

    def is_authorized(self) -> bool:
        settings = self.get_settings()
        if not settings.api_token and not settings.require_auth:
            return True
        auth_header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return auth_header.startswith(prefix) and auth_header[len(prefix) :] == settings.api_token

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    args = parse_args()
    settings = load_app_settings(Path(args.env_file) if args.env_file else None)
    if args.host:
        settings = AppSettings(args.host, settings.port, settings.api_token, settings.require_auth, settings.environment, settings.workspaces_config)
    if args.port:
        settings = AppSettings(settings.host, args.port, settings.api_token, settings.require_auth, settings.environment, settings.workspaces_config)
    validate_server_settings(settings)

    server = ThreadingHTTPServer((settings.host, settings.port), GatewayHandler)
    server.settings = settings  # type: ignore[attr-defined]
    print(f"DingTalk Codex Gateway listening on http://{settings.host}:{settings.port}")
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the DingTalk Codex Gateway HTTP service.")
    parser.add_argument("--host", default=None, help=f"Bind host. Defaults to env DINGTALK_GATEWAY_HOST or {HOST}.")
    parser.add_argument("--port", type=int, default=None, help=f"Bind port. Defaults to env DINGTALK_GATEWAY_PORT or {PORT}.")
    parser.add_argument("--env-file", default=None, help="Optional dotenv file to load before reading settings.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
