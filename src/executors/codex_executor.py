from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import Workspace
from ..models import ExecutionResult

SAFETY_PREAMBLE = (
    "You are running from DingTalk Codex Gateway. This task is read-only for external systems. "
    "Do not create, pause, activate, edit, or delete ads. Do not edit Shopline or Shoplazza products, "
    "discounts, theme, navigation, or orders. You may read data and write local analysis reports only "
    "to allowed project paths."
)


def run_complex_analysis(workspace: Workspace, task: str) -> ExecutionResult:
    prompt = f"{SAFETY_PREAMBLE}\n\nWorkspace: {workspace.path}\nTask: {task}"
    cmd = ["codex", "exec", "--sandbox", "read-only", prompt]
    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace.path,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
    except FileNotFoundError:
        return ExecutionResult(False, "complex_analysis", "本机没有找到 `codex` 命令，无法执行复杂分析。")
    except subprocess.TimeoutExpired:
        return ExecutionResult(False, "complex_analysis", "复杂分析超过 10 分钟，已超时停止。")

    output = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    ok = proc.returncode == 0
    markdown = output or "复杂分析没有输出。"
    if stderr and not ok:
        markdown += f"\n\n## stderr\n\n```text\n{stderr[-2000:]}\n```"
    return ExecutionResult(ok, "complex_analysis", markdown, data={"returncode": proc.returncode})
