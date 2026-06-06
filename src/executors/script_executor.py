from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import PROJECT_ROOT, Workspace
from ..models import ExecutionResult
from ..store_clients import DateWindow, StoreApiError, get_store_client, make_date_window


def run_order_daily(workspace: Workspace, day_word: str = "今天", store: str = "all") -> ExecutionResult:
    if store == "all":
        stores = list(workspace.stores or ("shopline", "shoplazza"))
    else:
        stores = [store]
    window = make_date_window(day_word, workspace.timezone)
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []

    for store_name in stores:
        try:
            client = get_store_client(store_name)
            orders = client.list_orders(window)
            normalized.extend(client.normalize_order(order) for order in orders)
        except (StoreApiError, ValueError) as exc:
            errors.append(f"{store_name}: {exc}")

    markdown = build_order_daily_markdown(window, store, normalized, errors)
    report_path = write_report("order-daily", window.local_date, store, markdown)
    return ExecutionResult(
        ok=not errors,
        command=f"order_daily_{window.label}_{store}",
        markdown=markdown,
        report_path=report_path,
        data={"orders": normalized, "errors": errors, "window": window.__dict__},
    )


def not_implemented(command: str) -> ExecutionResult:
    markdown = (
        f"`{command}` 已通过安全检查，但固定执行器还没实现。\n\n"
        "当前已实现：`订单日报 今天/昨天 store=shopline|shoplazza|all`。"
    )
    return ExecutionResult(ok=False, command=command, markdown=markdown)


def build_order_daily_markdown(window: DateWindow, requested_store: str, orders: list[dict[str, Any]], errors: list[str]) -> str:
    by_store: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in orders:
        by_store[order.get("store", "unknown")].append(order)

    total_revenue = sum_money(order.get("total_price_including_shipping") for order in orders)
    currency = first_known(order.get("currency") for order in orders)
    lines = [
        f"# 订单日报 - {window.label} ({window.local_date})",
        "",
        f"- 请求店铺：`{requested_store}`",
        f"- 时间窗口：`{window.since}` 到 `{window.until}` ({window.timezone})",
        f"- 总订单数：{len(orders)}",
        f"- 总收入（含运费，按店铺订单总额字段）：{format_money(total_revenue, currency)}",
        "",
        "## 店铺汇总",
        "",
    ]
    if by_store:
        for store_name in sorted(by_store.keys()):
            store_orders = by_store[store_name]
            store_revenue = sum_money(order.get("total_price_including_shipping") for order in store_orders)
            store_currency = first_known(order.get("currency") for order in store_orders) or currency
            field_sources = sorted({str(order.get("total_field_source", "unknown")) for order in store_orders})
            lines.append(f"- `{store_name}`：{len(store_orders)} 单，{format_money(store_revenue, store_currency)}，金额字段：{', '.join(field_sources)}")
    else:
        lines.append("- 没有查询到订单。")

    if orders:
        lines.extend(["", "## 订单明细（无客户 PII）", ""])
        lines.append("| 店铺 | 订单 | 时间 | 支付 | 发货 | 金额 | 来源/落地页 | UTM |")
        lines.append("| --- | --- | --- | --- | --- | ---: | --- | --- |")
        for order in sorted(orders, key=lambda item: item.get("created_at", ""), reverse=True):
            amount = order.get("total_price_including_shipping", "unknown")
            cur = order.get("currency", "")
            source = f"{order.get('source_name', 'unknown')} / {shorten(order.get('landing_site', 'unknown'), 48)}"
            lines.append(
                "| {store} | {name} | {created} | {financial} | {fulfillment} | {amount} {currency} | {source} | {utm} |".format(
                    store=escape_cell(order.get("store", "unknown")),
                    name=escape_cell(order.get("order_name", "unknown")),
                    created=escape_cell(shorten(order.get("created_at", "unknown"), 24)),
                    financial=escape_cell(order.get("financial_status", "unknown")),
                    fulfillment=escape_cell(order.get("fulfillment_status", "unknown")),
                    amount=escape_cell(amount),
                    currency=escape_cell(cur),
                    source=escape_cell(source),
                    utm=escape_cell(shorten(order.get("attribution", "unknown"), 80)),
                )
            )

    if errors:
        lines.extend(["", "## 查询错误", ""])
        for error in errors:
            lines.append(f"- {error}")

    lines.extend([
        "",
        "## 口径说明",
        "",
        "- 收入优先使用店铺订单总额字段；Shopline 优先 `current_total_price`，通常已含运费。",
        "- 如果只拿到 subtotal 字段，会尝试加 shipping 字段，并在金额字段里标注。",
        "- 报告不输出客户姓名、邮箱、电话、地址等 PII。",
    ])
    return "\n".join(lines)


def write_report(prefix: str, local_date: str, store: str, markdown: str) -> Path:
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%H%M%S")
    path = reports_dir / f"{local_date}-{prefix}-{store}-{stamp}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def sum_money(values) -> Decimal | None:
    total = Decimal("0")
    found = False
    for value in values:
        if value in (None, "", "unknown"):
            continue
        try:
            total += Decimal(str(value))
            found = True
        except (InvalidOperation, ValueError):
            continue
    return total if found else None


def format_money(value: Decimal | None, currency: str | None) -> str:
    if value is None:
        return "unknown"
    suffix = f" {currency}" if currency and currency != "unknown" else ""
    return f"{value.quantize(Decimal('0.01'))}{suffix}"


def first_known(values) -> str | None:
    for value in values:
        if value and value != "unknown":
            return str(value)
    return None


def escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def shorten(value: Any, length: int) -> str:
    text = str(value)
    return text if len(text) <= length else text[: length - 1] + "…"
