from __future__ import annotations

import re

from .config import load_workspaces
from .models import ExecutionResult, Route
from .security import REJECTION_MARKDOWN, find_dangerous_pattern, normalize_text
from .executors.codex_executor import run_complex_analysis
from .executors.script_executor import not_implemented, run_order_daily

STORE_RE = re.compile(r"store\s*=\s*(shopline|shoplazza|all)", re.IGNORECASE)


def route_text(text: str) -> Route:
    normalized = normalize_text(text)
    danger = find_dangerous_pattern(normalized)
    if danger:
        return Route("rejected_dangerous", "reject", {"pattern": danger})

    store_match = STORE_RE.search(normalized)
    store = (store_match.group(1).lower() if store_match else "all")
    day_word = "昨天" if "昨天" in normalized else "今天"

    if normalized.startswith("订单日报"):
        return Route(f"order_daily_{day_word}_{store}", "order_daily", {"day_word": day_word, "store": store})
    if normalized.startswith("广告日报"):
        return Route(f"ad_daily_{day_word}", "not_implemented", {})
    if normalized.startswith("检查漏单"):
        return Route(f"reconcile_missing_orders_{day_word}", "not_implemented", {})
    if normalized.startswith("广告状态"):
        return Route("ad_status", "not_implemented", {})
    if normalized.startswith("复杂分析"):
        task = normalized.removeprefix("复杂分析").strip()
        return Route("complex_analysis", "codex", {"task": task})

    return Route("unknown", "not_implemented", {})


def execute_route(workspace_name: str, text: str) -> ExecutionResult:
    workspaces = load_workspaces()
    workspace = workspaces.get(workspace_name)
    route = route_text(text)
    if workspace is None:
        return ExecutionResult(False, "unknown_workspace", f"未知 workspace：`{workspace_name}`")
    if route.executor == "reject":
        return ExecutionResult(False, route.command, REJECTION_MARKDOWN, data=route.args)
    if route.executor == "order_daily":
        return run_order_daily(workspace, **route.args)
    if route.executor == "codex":
        task = route.args.get("task") or ""
        if not task:
            return ExecutionResult(False, route.command, "请在 `复杂分析` 后面写清楚要分析的任务。")
        return run_complex_analysis(workspace, task)
    return not_implemented(route.command)
