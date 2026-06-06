from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .executors.codex_executor import SAFETY_PREAMBLE


class AgentError(RuntimeError):
    pass


class GatewayClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[:1000]
            raise AgentError(f"Gateway HTTP {exc.code}: {message}") from exc
        return json.loads(raw or "{}")

    def poll(self, agent_id: str) -> dict[str, Any] | None:
        payload = self.post("/agent/poll", {"agent_id": agent_id})
        return payload.get("job") if payload.get("ok") else None

    def event(self, job_id: str, event_type: str, message: str) -> None:
        self.post(f"/agent/jobs/{job_id}/events", {"event_type": event_type, "message": message})

    def complete(self, job_id: str, ok: bool, markdown: str, returncode: int | None = None, error: str = "") -> None:
        self.post(f"/agent/jobs/{job_id}/complete", {"ok": ok, "markdown": markdown, "returncode": returncode, "error": error})


def main() -> None:
    base_url = required_env("GATEWAY_URL")
    token = required_env("AGENT_TOKEN")
    agent_id = os.environ.get("AGENT_ID", "personal-pc")
    workspace_path = Path(os.environ.get("AGENT_WORKSPACE_PATH") or os.environ.get("WORKSPACE_PATH") or ".").expanduser()
    poll_interval = float(os.environ.get("AGENT_POLL_INTERVAL", "3"))
    timeout_seconds = int(os.environ.get("AGENT_JOB_TIMEOUT", "600"))
    client = GatewayClient(base_url, token)

    print(f"PC agent {agent_id} polling {base_url}; workspace={workspace_path}", flush=True)
    while True:
        try:
            job = client.poll(agent_id)
            if job:
                run_job(client, agent_id, workspace_path, job, timeout_seconds)
            else:
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"agent error: {exc}", flush=True)
            time.sleep(poll_interval)


def cli_main() -> None:
    try:
        main()
    except AgentError as exc:
        raise SystemExit(str(exc)) from exc


def run_job(client: GatewayClient, agent_id: str, workspace_path: Path, job: dict[str, Any], timeout_seconds: int) -> None:
    job_id = str(job["id"])
    task = str(job.get("task") or "")
    if not workspace_path.exists():
        message = f"Workspace path does not exist on agent {agent_id}: {workspace_path}"
        client.complete(job_id, False, "", error=message)
        return

    prompt = f"{SAFETY_PREAMBLE}\n\nWorkspace: {workspace_path}\nTask: {task}"
    cmd = ["codex", "exec", "--sandbox", "read-only", prompt]
    client.event(job_id, "started", f"agent={agent_id}\nworkspace={workspace_path}\ncommand=codex exec --sandbox read-only")

    output_parts: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=workspace_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        client.complete(job_id, False, "", error="PC 上没有找到 `codex` 命令。")
        return

    last_flush = time.time()
    pending: list[str] = []
    deadline = time.time() + timeout_seconds
    assert proc.stdout is not None
    while True:
        if time.time() > deadline:
            proc.kill()
            message = f"Codex job timed out after {timeout_seconds} seconds."
            client.event(job_id, "error", message)
            client.complete(job_id, False, tail("\n".join(output_parts), 12000), error=message)
            return
        line = proc.stdout.readline()
        if line:
            output_parts.append(line)
            pending.append(line)
        if pending and (len(pending) >= 12 or time.time() - last_flush >= 5):
            client.event(job_id, "progress", tail("".join(pending), 3500))
            pending.clear()
            last_flush = time.time()
        if line == "" and proc.poll() is not None:
            break
        if not line:
            time.sleep(0.1)

    if pending:
        client.event(job_id, "progress", tail("".join(pending), 3500))
    returncode = proc.returncode
    output = "".join(output_parts).strip()
    ok = returncode == 0
    client.complete(job_id, ok, tail(output or "Codex 没有输出。", 12000), returncode=returncode, error="" if ok else f"codex exited with {returncode}")


def required_env(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise AgentError(f"Missing required env: {key}")
    return value


def tail(text: str, length: int) -> str:
    return text if len(text) <= length else text[-length:]


if __name__ == "__main__":
    cli_main()
