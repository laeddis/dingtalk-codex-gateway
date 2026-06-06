from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .audit import append_audit
from .config import AppSettings, load_app_settings, public_config_snapshot, validate_server_settings
from .dingtalk import extract_sender_from_callback, extract_text_from_callback
from .dingtalk_client import DingTalkClient, DingTalkSendError
from .job_store import JobStore
from .router import execute_route, route_text

HOST = "127.0.0.1"
PORT = 8787


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "DingTalkCodexGateway/0.2"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            settings = self.get_settings()
            self.write_json({"ok": True, "environment": settings.environment, **public_config_snapshot()})
            return
        self.write_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/local/message":
            self.handle_local_message()
            return
        if path == "/dingtalk/callback":
            self.handle_dingtalk_callback()
            return
        if path == "/agent/poll":
            self.handle_agent_poll()
            return
        if path.startswith("/agent/jobs/") and path.endswith("/events"):
            self.handle_agent_event(path.split("/")[3])
            return
        if path.startswith("/agent/jobs/") and path.endswith("/complete"):
            self.handle_agent_complete(path.split("/")[3])
            return
        self.write_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)

    def handle_local_message(self) -> None:
        if not self.is_authorized():
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            payload = self.read_json()
            workspace = str(payload.get("workspace") or self.get_settings().default_workspace)
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

    def handle_dingtalk_callback(self) -> None:
        if not self.is_dingtalk_callback_authorized():
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            payload = self.read_json()
            text = extract_text_from_callback(payload)
            if not text:
                self.write_json({"ok": False, "error": "empty_text"}, HTTPStatus.BAD_REQUEST)
                return
            workspace = str(payload.get("workspace") or self.get_settings().default_workspace)
            sender = extract_sender_from_callback(payload)
            route = route_text(text)
            if route.executor == "reject":
                message = "⚠️ 命令已被安全策略拦截。请回到 Codex CLI 主会话手动确认高风险操作。"
                self.notify_dingtalk("命令已拦截", message)
                self.write_json({"ok": False, "executor": "reject", "markdown": message})
                return
            if route.executor != "codex":
                message = "当前 PC Agent MVP 只支持 `复杂分析 <任务>` 通过个人 PC 执行 Codex。"
                self.notify_dingtalk("命令未入队", message)
                self.write_json({"ok": False, "error": "unsupported_remote_command", "markdown": message}, HTTPStatus.BAD_REQUEST)
                return
            task = str(route.args.get("task") or "").strip()
            if not task:
                self.write_json({"ok": False, "error": "empty_task"}, HTTPStatus.BAD_REQUEST)
                return

            job = self.get_job_store().create_job(workspace, sender, text, task, "codex")
            markdown = f"已创建 Codex 任务。\n\n- Job ID：`{job['id']}`\n- Workspace：`{workspace}`\n- 状态：`queued`"
            self.notify_dingtalk("Codex 任务已创建", markdown)
            append_audit({"source": "dingtalk_callback", "workspace": workspace, "sender": sender, "raw_text": text, "job_id": job["id"], "status": "queued"})
            self.write_json({"ok": True, "job_id": job["id"], "status": "queued", "markdown": markdown})
        except Exception as exc:
            append_audit({"source": "dingtalk_callback", "status": "error", "error": str(exc)})
            self.write_json({"ok": False, "error": type(exc).__name__, "message": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_agent_poll(self) -> None:
        if not self.is_agent_authorized():
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        payload = self.read_json()
        agent_id = str(payload.get("agent_id") or "unknown-agent")
        job = self.get_job_store().claim_next_job(agent_id)
        if not job:
            self.write_json({"ok": True, "job": None})
            return
        self.notify_dingtalk("Codex 任务开始执行", f"Job `{job['id']}` 已由 PC Agent `{agent_id}` 接收。")
        self.write_json({"ok": True, "job": public_job(job)})

    def handle_agent_event(self, job_id: str) -> None:
        if not self.is_agent_authorized():
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        payload = self.read_json()
        event_type = str(payload.get("event_type") or "log")[:40]
        message = shorten(str(payload.get("message") or ""), 3500)
        job = self.get_job_store().add_event(job_id, event_type, message)
        if not job:
            self.write_json({"ok": False, "error": "job_not_found"}, HTTPStatus.NOT_FOUND)
            return
        if event_type in {"started", "progress", "error"} and message:
            self.notify_dingtalk(f"Codex 任务进度 {job_id[:8]}", f"Job `{job_id}`\n\n```text\n{message}\n```")
        self.write_json({"ok": True, "job_id": job_id})

    def handle_agent_complete(self, job_id: str) -> None:
        if not self.is_agent_authorized():
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        payload = self.read_json()
        ok = bool(payload.get("ok"))
        markdown = shorten(str(payload.get("markdown") or ""), 12000)
        error = shorten(str(payload.get("error") or ""), 2000)
        returncode = payload.get("returncode")
        job = self.get_job_store().complete_job(job_id, ok, markdown, int(returncode) if isinstance(returncode, int) else None, error)
        if not job:
            self.write_json({"ok": False, "error": "job_not_found"}, HTTPStatus.NOT_FOUND)
            return
        status_label = "完成" if ok else "失败"
        body = f"Job `{job_id}` {status_label}。\n\n{markdown or error or '没有输出。'}"
        self.notify_dingtalk(f"Codex 任务{status_label}", body)
        self.write_json({"ok": True, "job_id": job_id, "status": job["status"]})

    def get_settings(self) -> AppSettings:
        return getattr(self.server, "settings", load_app_settings())

    def get_job_store(self) -> JobStore:
        store = getattr(self.server, "job_store", None)
        if store is None:
            store = JobStore(self.get_settings().job_db_path)
            self.server.job_store = store  # type: ignore[attr-defined]
        return store

    def get_dingtalk_client(self) -> DingTalkClient:
        settings = self.get_settings()
        return DingTalkClient(settings.dingtalk_outgoing_webhook, settings.dingtalk_outgoing_secret)

    def notify_dingtalk(self, title: str, markdown: str) -> None:
        try:
            self.get_dingtalk_client().send_markdown(title, markdown)
        except DingTalkSendError as exc:
            append_audit({"source": "dingtalk_notify", "status": "error", "error": str(exc)})
        except Exception as exc:
            append_audit({"source": "dingtalk_notify", "status": "error", "error": str(exc)})

    def is_authorized(self) -> bool:
        settings = self.get_settings()
        if not settings.api_token and not settings.require_auth:
            return True
        return bearer_token(self.headers.get("Authorization", "")) == settings.api_token

    def is_agent_authorized(self) -> bool:
        settings = self.get_settings()
        return bool(settings.agent_token) and bearer_token(self.headers.get("Authorization", "")) == settings.agent_token

    def is_dingtalk_callback_authorized(self) -> bool:
        token = self.get_settings().dingtalk_callback_token
        if not token:
            return True
        parsed = urlparse(self.path)
        query_token = (parse_qs(parsed.query).get("token") or [""])[0]
        header_token = self.headers.get("X-DingTalk-Token", "")
        return token in {query_token, header_token}

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


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "workspace": job["workspace"],
        "executor": job["executor"],
        "task": job["task"],
        "status": job["status"],
        "created_at": job["created_at"],
    }


def bearer_token(auth_header: str) -> str:
    prefix = "Bearer "
    return auth_header[len(prefix) :] if auth_header.startswith(prefix) else ""


def shorten(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"


def main() -> None:
    args = parse_args()
    settings = load_app_settings(Path(args.env_file) if args.env_file else None)
    if args.host:
        settings = AppSettings(
            args.host,
            settings.port,
            settings.api_token,
            settings.require_auth,
            settings.environment,
            settings.workspaces_config,
            settings.default_workspace,
            settings.agent_token,
            settings.dingtalk_callback_token,
            settings.dingtalk_outgoing_webhook,
            settings.dingtalk_outgoing_secret,
            settings.job_db_path,
        )
    if args.port:
        settings = AppSettings(
            settings.host,
            args.port,
            settings.api_token,
            settings.require_auth,
            settings.environment,
            settings.workspaces_config,
            settings.default_workspace,
            settings.agent_token,
            settings.dingtalk_callback_token,
            settings.dingtalk_outgoing_webhook,
            settings.dingtalk_outgoing_secret,
            settings.job_db_path,
        )
    validate_server_settings(settings)

    server = ThreadingHTTPServer((settings.host, settings.port), GatewayHandler)
    server.settings = settings  # type: ignore[attr-defined]
    server.job_store = JobStore(settings.job_db_path)  # type: ignore[attr-defined]
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
