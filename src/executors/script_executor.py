from __future__ import annotations

import csv
import json
import subprocess
import urllib.parse
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import PROJECT_ROOT, Workspace
from ..meta_client import MetaApiError, find_meta_access_token, get_campaign_daily_insights, get_campaign_structure_status
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


def run_ad_daily(workspace: Workspace, day_word: str = "今天") -> ExecutionResult:
    window = make_date_window(day_word, workspace.timezone)
    ad_tests_dir = workspace.path / "ad_tests"
    campaigns = collect_local_campaigns(ad_tests_dir)
    if not campaigns:
        markdown = build_ad_daily_markdown(window, [], [f"没有在 `{ad_tests_dir}` 找到本地 campaign 快照。"])
        report_path = write_report("ad-daily", window.local_date, "meta", markdown)
        return ExecutionResult(False, f"ad_daily_{window.label}", markdown, report_path=report_path)

    token = find_meta_access_token()
    if not token:
        markdown = build_ad_daily_markdown(window, [], ["未找到 Meta access token；已跳过实时只读查询。"])
        report_path = write_report("ad-daily", window.local_date, "meta", markdown)
        return ExecutionResult(False, f"ad_daily_{window.label}", markdown, report_path=report_path)

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for campaign_id, campaign_name in campaigns:
        try:
            rows.append(get_campaign_daily_insights(campaign_id, campaign_name, window.local_date, token))
        except MetaApiError as exc:
            errors.append(f"{campaign_name} / {campaign_id}: {exc}")

    markdown = build_ad_daily_markdown(window, rows, errors)
    report_path = write_report("ad-daily", window.local_date, "meta", markdown)
    return ExecutionResult(
        ok=bool(rows),
        command=f"ad_daily_{window.label}",
        markdown=markdown,
        report_path=report_path,
        data={"campaigns": [{"id": cid, "name": name} for cid, name in campaigns], "errors": errors},
    )


def run_missing_order_reconciliation(workspace: Workspace, day_word: str = "今天") -> ExecutionResult:
    window = make_date_window(day_word, workspace.timezone)
    script_path = workspace.path / "scripts" / "reconcile_shopline_meta_purchases.py"
    if not script_path.exists():
        return ExecutionResult(False, f"reconcile_missing_orders_{window.label}", f"未找到对账脚本：`{script_path}`")

    out_dir = workspace.path / "ad_tests" / f"purchase_reconciliation_{window.local_date}"
    cmd = [
        "python3",
        str(script_path),
        "--since",
        window.since,
        "--until",
        window.until,
        "--meta-since",
        window.local_date,
        "--meta-until",
        window.local_date,
        "--out-dir",
        str(out_dir),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace.path,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(False, f"reconcile_missing_orders_{window.label}", "检查漏单超过 3 分钟，已超时停止。")

    md_path = out_dir / "reconciliation.md"
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    if markdown:
        markdown += "\n"
    markdown += (
        "\n## 网关说明\n\n"
        f"- 时间窗口：`{window.since}` 到 `{window.until}` ({window.timezone})\n"
        "- 当前固定对账脚本只覆盖 Shopline + Meta campaign；Shoplazza 订单未纳入漏单判断。\n"
        "- 该命令只读外部系统，写入本地 `ad_tests/purchase_reconciliation_*` 报告。\n"
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        markdown = (
            f"`检查漏单 {window.label}` 执行失败。\n\n"
            f"- returncode: `{proc.returncode}`\n"
            f"- stdout: `{shorten(stdout, 2000)}`\n"
            f"- stderr: `{shorten(stderr, 2000)}`\n\n"
            + markdown
        )
    report_path = write_report("missing-order-reconciliation", window.local_date, "shopline-meta", markdown)
    return ExecutionResult(
        ok=proc.returncode == 0,
        command=f"reconcile_missing_orders_{window.label}",
        markdown=markdown,
        report_path=report_path,
        data={"out_dir": str(out_dir), "source_report": str(md_path) if md_path.exists() else None, "returncode": proc.returncode},
    )


def run_ad_status(workspace: Workspace) -> ExecutionResult:
    ad_tests_dir = workspace.path / "ad_tests"
    local_snapshots = collect_ad_status_snapshots(ad_tests_dir)
    snapshots = local_snapshots
    errors: list[str] = []
    token = find_meta_access_token()
    campaigns = collect_local_campaigns(ad_tests_dir)
    if token and campaigns:
        live_snapshots: list[dict[str, Any]] = []
        for campaign_id, campaign_name in campaigns:
            try:
                live_snapshots.append(get_campaign_structure_status(campaign_id, campaign_name, token))
            except MetaApiError as exc:
                errors.append(f"{campaign_name} / {campaign_id}: {exc}")
        if live_snapshots:
            snapshots = live_snapshots
    elif campaigns:
        errors.append("未找到 Meta access token；已回退到本地广告快照。")

    is_live = any(snapshot.get("source") == "meta_live" for snapshot in snapshots)
    markdown = build_ad_status_markdown(ad_tests_dir, snapshots, errors)
    report_path = write_report("ad-status", datetime.now(ZoneInfo(workspace.timezone)).date().isoformat(), "meta-live" if is_live else "local-snapshots", markdown)
    return ExecutionResult(
        ok=bool(snapshots),
        command="ad_status",
        markdown=markdown,
        report_path=report_path,
        data={"snapshot_count": len(snapshots), "local_snapshot_count": len(local_snapshots), "errors": errors, "ad_tests_dir": str(ad_tests_dir)},
    )


def not_implemented(command: str) -> ExecutionResult:
    markdown = (
        f"`{command}` 已通过安全检查，但固定执行器还没实现。\n\n"
        "当前已实现：`订单日报 今天/昨天 store=shopline|shoplazza|all`、`广告日报 今天/昨天`、`检查漏单 今天/昨天`、`广告状态`。"
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


def build_ad_daily_markdown(window: DateWindow, campaigns: list[dict[str, Any]], errors: list[str]) -> str:
    spend = sum_money(row.get("spend") for row in campaigns) or Decimal("0")
    purchases = sum_money(row.get("purchases") for row in campaigns) or Decimal("0")
    purchase_value = sum_money(row.get("purchase_value") for row in campaigns) or Decimal("0")
    roas = (purchase_value / spend).quantize(Decimal("0.01")) if spend else Decimal("0")
    cpa = (spend / purchases).quantize(Decimal("0.01")) if purchases else Decimal("0")
    lines = [
        f"# 广告日报 - {window.label} ({window.local_date})",
        "",
        f"- 时间窗口：Meta account timezone date `{window.local_date}`；网关本地窗口 `{window.since}` 到 `{window.until}` ({window.timezone})",
        f"- Campaign 数：{len(campaigns)}",
        f"- 总花费：${spend.quantize(Decimal('0.01'))}",
        f"- Purchase：{purchases.quantize(Decimal('0.01'))}",
        f"- Purchase Value：${purchase_value.quantize(Decimal('0.01'))}",
        f"- CPA：${cpa}",
        f"- ROAS：{roas}",
        "",
    ]
    if campaigns:
        lines.extend([
            "## Campaign 明细",
            "",
            "| Campaign | 状态 | 花费 | 展示 | 点击 | Link Click | Purchase | Value | CPA | ROAS |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for row in sorted(campaigns, key=lambda item: Decimal(str(item.get("spend", "0"))), reverse=True):
            lines.append(
                "| {name} | `{status}`/`{effective}` | ${spend} | {impressions} | {clicks} | {link_clicks} | {purchases} | ${value} | ${cpa} | {roas} |".format(
                    name=escape_cell(row.get("campaign_name", "unknown")),
                    status=escape_cell(row.get("status", "unknown")),
                    effective=escape_cell(row.get("effective_status", "unknown")),
                    spend=escape_cell(row.get("spend", "0.00")),
                    impressions=escape_cell(row.get("impressions", "0.00")),
                    clicks=escape_cell(row.get("clicks", "0.00")),
                    link_clicks=escape_cell(row.get("link_clicks", "0.00")),
                    purchases=escape_cell(row.get("purchases", "0.00")),
                    value=escape_cell(row.get("purchase_value", "0.00")),
                    cpa=escape_cell(row.get("cpa", "0.00")),
                    roas=escape_cell(row.get("roas", "0.00")),
                )
            )
    else:
        lines.append("没有拿到 Meta campaign 数据。")

    if errors:
        lines.extend(["", "## 查询错误", ""])
        for error in errors:
            lines.append(f"- {error}")

    lines.extend([
        "",
        "## 判断提醒",
        "",
        "- 这是只读 Meta campaign-level 日报，不按单日 breakdown 直接建议关停国家、版位或人群。",
        "- Purchase 可能有归因延迟；最终判断应结合 `检查漏单` 的 Shopline 对账结果。",
        "- DingTalk MVP 不执行启停、预算、创建或修改广告。",
    ])
    return "\n".join(lines)


def write_report(prefix: str, local_date: str, store: str, markdown: str) -> Path:
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%H%M%S")
    path = reports_dir / f"{local_date}-{prefix}-{store}-{stamp}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def collect_ad_status_snapshots(ad_tests_dir: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    csv_path = ad_tests_dir / "dog_breed_shopline_meta_launch_results.csv"
    if csv_path.exists():
        snapshots.extend(snapshot_from_launch_csv(csv_path))
    for path in sorted(ad_tests_dir.glob("*.json")):
        snapshots.extend(snapshot_from_json(path))
    return snapshots


def collect_local_campaigns(ad_tests_dir: Path) -> list[tuple[str, str]]:
    campaigns: dict[str, str] = {}
    for snapshot in collect_ad_status_snapshots(ad_tests_dir):
        campaign_id = str(snapshot.get("campaign_id") or "")
        if not campaign_id or campaign_id == "unknown":
            continue
        name = str(snapshot.get("campaign_name") or "unknown")
        # Later local snapshots often contain renamed campaign labels; keep the latest usable name.
        if name != "unknown" or campaign_id not in campaigns:
            campaigns[campaign_id] = name
    return sorted(campaigns.items(), key=lambda item: item[1])


def snapshot_from_launch_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        campaign_id = row.get("campaign_id") or "unknown"
        item = grouped.setdefault(campaign_id, {
            "source": path.name,
            "campaign_id": campaign_id,
            "campaign_name": row.get("campaign_name") or "unknown",
            "campaign_status": row.get("campaign_status") or "unknown",
            "adsets": {},
            "ads": [],
        })
        adset_id = row.get("adset_id") or "unknown"
        item["adsets"].setdefault(adset_id, {
            "adset_id": adset_id,
            "adset_name": row.get("adset_name") or "unknown",
            "status": row.get("adset_status") or "unknown",
        })
        item["ads"].append({
            "ad_id": row.get("ad_id") or "unknown",
            "ad_name": row.get("title") or row.get("ad_id") or "unknown",
            "status": row.get("ad_status") or "unknown",
            "adset_id": adset_id,
        })
    return list(grouped.values())


def snapshot_from_json(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []

    snapshots: list[dict[str, Any]] = []
    if isinstance(data.get("items"), list):
        return snapshot_from_rows(path.name, list_of_dicts(data.get("items")), "json_items")

    campaign = first_dict(data, "campaign_after", "campaign_before", "meta_created_then_paused")
    adsets = list_of_dicts(data.get("adsets_after") or data.get("adset_counts") or [])
    ads = list_of_dicts(data.get("ads_after") or data.get("ads") or [])
    updated_ads = list_of_dicts(data.get("updated")) if isinstance(data.get("updated"), list) else []
    if not campaign and not adsets and updated_ads:
        return snapshot_from_rows(path.name, updated_ads, "updated")
    if not ads:
        ads = updated_ads
    if campaign or adsets or ads:
        campaign_id = str((campaign or {}).get("id") or (campaign or {}).get("campaign_id") or data.get("campaign_id") or "unknown")
        snapshots.append({
            "source": path.name,
            "campaign_id": campaign_id,
            "campaign_name": str((campaign or {}).get("name") or (campaign or {}).get("campaign_name") or data.get("campaign_name") or "unknown"),
            "campaign_status": str((campaign or {}).get("effective_status") or (campaign or {}).get("status") or data.get("final_status") or "unknown"),
            "adsets": {
                str(item.get("id") or item.get("adset_id") or "unknown"): {
                    "adset_id": str(item.get("id") or item.get("adset_id") or "unknown"),
                    "adset_name": str(item.get("name") or item.get("adset_name") or "unknown"),
                    "status": str(item.get("effective_status") or item.get("status") or item.get("adset_status") or "unknown"),
                }
                for item in adsets
            },
            "ads": [
                {
                    "ad_id": str(item.get("id") or item.get("ad_id") or "unknown"),
                    "ad_name": str(item.get("name") or item.get("ad_name") or "unknown"),
                    "status": str(item.get("effective_status") or item.get("status") or item.get("ad_status") or "unknown"),
                    "adset_id": str(item.get("adset_id") or "unknown"),
                }
                for item in ads
            ],
        })
    return snapshots


def snapshot_from_rows(source: str, rows: list[dict[str, Any]], source_type: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        url_tags = parse_url_tags(row.get("url_tags"))
        campaign_id = str(row.get("campaign_id") or url_tags.get("utm_id") or "unknown")
        item = grouped.setdefault(campaign_id, {
            "source": f"{source}:{source_type}",
            "campaign_id": campaign_id,
            "campaign_name": str(row.get("campaign_name") or url_tags.get("utm_campaign") or "unknown"),
            "campaign_status": str(row.get("campaign_status") or row.get("status") or "unknown"),
            "adsets": {},
            "ads": [],
        })
        adset_id = str(row.get("adset_id") or "unknown")
        if adset_id != "unknown":
            item["adsets"].setdefault(adset_id, {
                "adset_id": adset_id,
                "adset_name": str(row.get("adset_name") or url_tags.get("utm_adset") or "unknown"),
                "status": str(row.get("adset_status") or "unknown"),
            })
        ad_id = str(row.get("ad_id") or row.get("id") or "unknown")
        if ad_id != "unknown":
            item["ads"].append({
                "ad_id": ad_id,
                "ad_name": str(row.get("title") or row.get("ad_name") or row.get("name") or ad_id),
                "status": str(row.get("ad_status") or row.get("effective_status") or row.get("status") or "unknown"),
                "adset_id": adset_id,
            })
    return list(grouped.values())


def parse_url_tags(value: Any) -> dict[str, str]:
    if not value:
        return {}
    pairs = urllib.parse.parse_qsl(str(value), keep_blank_values=False)
    return {key: val for key, val in pairs}


def build_ad_status_markdown(ad_tests_dir: Path, snapshots: list[dict[str, Any]], errors: list[str] | None = None) -> str:
    errors = errors or []
    is_live = any(snapshot.get("source") == "meta_live" for snapshot in snapshots)
    lines = [
        "# 广告状态 - Meta 实时状态" if is_live else "# 广告状态 - 本地快照",
        "",
        f"- 数据目录：`{ad_tests_dir}`",
        f"- 快照数量：{len(snapshots)}",
        "- 口径：通过只读 Meta Graph API 查询 campaign/ad set/ad 状态。" if is_live else "- 口径：读取 workspace 本地 `ad_tests` 里的创建/修复结果文件；不是实时 Meta API 状态。",
        "",
    ]
    if not snapshots:
        lines.append("没有找到可读取的本地广告状态快照。")
        if errors:
            lines.extend(["", "## 查询错误", ""])
            for error in errors:
                lines.append(f"- {error}")
        return "\n".join(lines)

    for snapshot in snapshots:
        adsets = list(snapshot.get("adsets", {}).values())
        ads = snapshot.get("ads", [])
        ad_status_counts = count_by_status(item.get("status", "unknown") for item in ads)
        adset_status_counts = count_by_status(item.get("status", "unknown") for item in adsets)
        lines.extend([
            f"## {snapshot.get('campaign_name', 'unknown')}",
            "",
            f"- 来源文件：`{snapshot.get('source', 'unknown')}`",
            f"- Campaign ID：`{snapshot.get('campaign_id', 'unknown')}`",
            f"- Campaign 状态：`{snapshot.get('campaign_status', 'unknown')}`",
            f"- Ad set：{len(adsets)} 个（{format_status_counts(adset_status_counts)}）",
            f"- Ads：{len(ads)} 条（{format_status_counts(ad_status_counts)}）",
            "",
        ])
        if adsets:
            lines.append("| Ad set | 状态 | Ads |")
            lines.append("| --- | --- | ---: |")
            ads_by_adset = defaultdict(list)
            for ad in ads:
                ads_by_adset[ad.get("adset_id", "unknown")].append(ad)
            for adset in sorted(adsets, key=lambda item: item.get("adset_name", "")):
                lines.append(
                    "| {name} | `{status}` | {count} |".format(
                        name=escape_cell(adset.get("adset_name", "unknown")),
                        status=escape_cell(adset.get("status", "unknown")),
                        count=len(ads_by_adset.get(adset.get("adset_id", "unknown"), [])),
                    )
                )
            lines.append("")
    lines.extend([
        "## 安全说明",
        "",
        "- 这个命令不会启停、创建、修改或删除广告。",
        "- 如 Meta token 不可用或查询失败，会回退到本地快照并展示查询错误。",
    ])
    if errors:
        lines.extend(["", "## 查询错误", ""])
        for error in errors:
            lines.append(f"- {error}")
    return "\n".join(lines)


def first_dict(data: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return None


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def count_by_status(statuses) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for status in statuses:
        counts[str(status or "unknown")] += 1
    return dict(counts)


def format_status_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"`{key}` {value}" for key, value in sorted(counts.items()))


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
