from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .audit import append_audit
from .config import public_config_snapshot
from .router import execute_route, route_text

HOST = "127.0.0.1"
PORT = 8787


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "DingTalkCodexGateway/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.write_json({"ok": True, **public_config_snapshot()})
            return
        self.write_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/local/message":
            self.write_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
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
    server = ThreadingHTTPServer((HOST, PORT), GatewayHandler)
    print(f"DingTalk Codex Gateway listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
