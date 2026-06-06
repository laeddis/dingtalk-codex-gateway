from __future__ import annotations

import json
import os
import shlex
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

GRAPH_VERSION = "v24.0"
META_ENV_PATH = Path("/root/.config/meta-ads-mcp/env")
TOKEN_KEYS = ("META_ACCESS_TOKEN", "FACEBOOK_ACCESS_TOKEN", "FB_ACCESS_TOKEN")


class MetaApiError(RuntimeError):
    pass


def find_meta_access_token() -> str | None:
    for key in TOKEN_KEYS:
        value = os.environ.get(key)
        if value:
            return value
    env = read_shell_env_file(META_ENV_PATH)
    for key in TOKEN_KEYS:
        value = env.get(key)
        if value:
            return value
    for env_path in Path("/proc").glob("*/environ"):
        if not env_path.parent.name.isdigit():
            continue
        try:
            parts = env_path.read_bytes().split(b"\0")
        except OSError:
            continue
        for item in parts:
            for key in TOKEN_KEYS:
                prefix = f"{key}=".encode()
                if item.startswith(prefix):
                    token = item.split(b"=", 1)[1].decode("utf-8", "ignore")
                    if token:
                        return token
    return None


def read_shell_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        try:
            parsed = shlex.split(value)
        except ValueError:
            parsed = [value.strip("'\"")]
        env[key] = parsed[0] if parsed else ""
    return env


def graph_get(path: str, params: dict[str, Any], token: str) -> dict[str, Any]:
    query = {key: value for key, value in params.items() if value is not None}
    query["access_token"] = token
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1200]
            raise MetaApiError(f"Graph GET {path} -> HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt == 2:
                raise MetaApiError(f"Graph GET {path} network error: {exc.reason}") from exc
            time.sleep(1 + attempt)
    return json.loads(raw) if raw.strip() else {}


def get_campaign_daily_insights(campaign_id: str, campaign_name: str, local_date: str, token: str) -> dict[str, Any]:
    details = get_campaign_details(campaign_id, token)
    fields = ",".join([
        "spend",
        "impressions",
        "clicks",
        "cpm",
        "cpc",
        "ctr",
        "actions",
        "action_values",
        "campaign_id",
        "campaign_name",
    ])
    payload = graph_get(f"{campaign_id}/insights", {
        "time_range": json.dumps({"since": local_date, "until": local_date}),
        "fields": fields,
        "level": "campaign",
        "limit": 10,
        "action_attribution_windows": json.dumps(["1d_click", "7d_click", "1d_view"]),
    }, token)
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        rows = []
    spend = sum((money(row.get("spend")) for row in rows if isinstance(row, dict)), Decimal("0"))
    purchases = action_total(rows, "purchase")
    purchase_value = action_value_total(rows, "purchase")
    link_clicks = action_total(rows, "link_click")
    impressions = sum((money(row.get("impressions")) for row in rows if isinstance(row, dict)), Decimal("0"))
    clicks = sum((money(row.get("clicks")) for row in rows if isinstance(row, dict)), Decimal("0"))
    return {
        "campaign_id": campaign_id,
        "campaign_name": details.get("name") or campaign_name,
        "status": details.get("status") or "unknown",
        "effective_status": details.get("effective_status") or "unknown",
        "configured_status": details.get("configured_status") or "unknown",
        "spend": dec_str(spend),
        "impressions": dec_str(impressions),
        "clicks": dec_str(clicks),
        "link_clicks": dec_str(link_clicks),
        "purchases": dec_str(purchases),
        "purchase_value": dec_str(purchase_value),
        "cpa": dec_str(spend / purchases) if purchases else "0.00",
        "roas": dec_str(purchase_value / spend) if spend else "0.00",
        "rows": rows,
    }


def get_campaign_structure_status(campaign_id: str, campaign_name: str, token: str) -> dict[str, Any]:
    details = get_campaign_details(campaign_id, token)
    adsets = graph_get_all(f"{campaign_id}/adsets", {
        "fields": "id,name,status,effective_status,configured_status,daily_budget,lifetime_budget",
        "limit": 100,
    }, token)
    ads = graph_get_all(f"{campaign_id}/ads", {
        "fields": "id,name,status,effective_status,configured_status,adset_id,creative{id,name}",
        "limit": 200,
    }, token)
    return {
        "source": "meta_live",
        "campaign_id": campaign_id,
        "campaign_name": details.get("name") or campaign_name,
        "campaign_status": details.get("effective_status") or details.get("status") or "unknown",
        "campaign_configured_status": details.get("configured_status") or "unknown",
        "adsets": {
            str(item.get("id") or "unknown"): {
                "adset_id": str(item.get("id") or "unknown"),
                "adset_name": str(item.get("name") or "unknown"),
                "status": str(item.get("effective_status") or item.get("status") or "unknown"),
                "configured_status": str(item.get("configured_status") or "unknown"),
                "daily_budget": str(item.get("daily_budget") or ""),
                "lifetime_budget": str(item.get("lifetime_budget") or ""),
            }
            for item in adsets
            if isinstance(item, dict)
        },
        "ads": [
            {
                "ad_id": str(item.get("id") or "unknown"),
                "ad_name": str(item.get("name") or "unknown"),
                "status": str(item.get("effective_status") or item.get("status") or "unknown"),
                "configured_status": str(item.get("configured_status") or "unknown"),
                "adset_id": str(item.get("adset_id") or "unknown"),
            }
            for item in ads
            if isinstance(item, dict)
        ],
    }


def get_campaign_details(campaign_id: str, token: str) -> dict[str, Any]:
    try:
        payload = graph_get(campaign_id, {
            "fields": "id,name,status,effective_status,configured_status",
        }, token)
    except MetaApiError:
        return {"id": campaign_id}
    return payload if isinstance(payload, dict) else {"id": campaign_id}


def graph_get_all(path: str, params: dict[str, Any], token: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    payload = graph_get(path, params, token)
    while True:
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            rows.extend(item for item in data if isinstance(item, dict))
        next_url = ((payload.get("paging") or {}).get("next") if isinstance(payload, dict) else None)
        if not next_url:
            break
        payload = graph_get_url(next_url)
    return rows


def graph_get_url(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1200]
            raise MetaApiError(f"Graph GET page -> HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt == 2:
                raise MetaApiError(f"Graph GET page network error: {exc.reason}") from exc
            time.sleep(1 + attempt)
    return json.loads(raw) if raw.strip() else {}


def action_total(rows: list[Any], action_type: str) -> Decimal:
    total = Decimal("0")
    for row in rows:
        if not isinstance(row, dict):
            continue
        for item in row.get("actions") or []:
            if isinstance(item, dict) and item.get("action_type") == action_type:
                total += money(item.get("value"))
    return total


def action_value_total(rows: list[Any], action_type: str) -> Decimal:
    total = Decimal("0")
    for row in rows:
        if not isinstance(row, dict):
            continue
        for item in row.get("action_values") or []:
            if isinstance(item, dict) and item.get("action_type") == action_type:
                total += money(item.get("value"))
    return total


def money(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def dec_str(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"
