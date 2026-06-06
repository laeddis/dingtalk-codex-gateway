from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import load_codex_mcp_env


@dataclass(frozen=True)
class DateWindow:
    label: str
    since: str
    until: str
    local_date: str
    timezone: str


def make_date_window(day_word: str, timezone: str) -> DateWindow:
    tz = ZoneInfo(timezone)
    today = datetime.now(tz).date()
    if day_word == "昨天":
        target = today - timedelta(days=1)
    else:
        target = today
    start = datetime.combine(target, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return DateWindow(
        label=day_word if day_word in {"今天", "昨天"} else "今天",
        since=start.isoformat(timespec="seconds"),
        until=end.isoformat(timespec="seconds"),
        local_date=target.isoformat(),
        timezone=timezone,
    )


class StoreApiError(RuntimeError):
    pass


class BaseStoreClient:
    store_name = "base"

    def list_orders(self, window: DateWindow) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize_order(self, order: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _get_json(self, url: str, headers: dict[str, str]) -> Any:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            raise StoreApiError(f"{self.store_name} API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise StoreApiError(f"{self.store_name} API network error: {exc.reason}") from exc
        return json.loads(raw) if raw.strip() else {}


class ShoplineClient(BaseStoreClient):
    store_name = "shopline"

    def __init__(self) -> None:
        env = load_codex_mcp_env("shopline")
        self.store_handle = required(env, "SHOPLINE_STORE_HANDLE", self.store_name)
        self.access_token = required(env, "SHOPLINE_ACCESS_TOKEN", self.store_name)
        self.api_version = env.get("SHOPLINE_API_VERSION", "v20260301")
        base = env.get("SHOPLINE_API_BASE_URL") or f"https://{self.store_handle}.myshopline.com/admin/openapi"
        self.api_base_url = base.rstrip("/")

    def list_orders(self, window: DateWindow) -> list[dict[str, Any]]:
        query = {
            "limit": "100",
            "created_at_min": window.since,
            "created_at_max": window.until,
        }
        url = f"{self.api_base_url}/{self.api_version}/orders.json?{urllib.parse.urlencode(query)}"
        payload = self._get_json(url, {"Accept": "application/json", "Authorization": f"Bearer {self.access_token}"})
        return extract_orders(payload)

    def normalize_order(self, order: dict[str, Any]) -> dict[str, Any]:
        total, total_source = first_money(order, (
            "current_total_price",
            "total_price",
            "order_total",
            "total",
            "subtotal_price",
        ))
        shipping, shipping_source = first_money(order, ("total_shipping_price", "shipping_price", "shipping_fee"))
        # Shopline current_total_price is the preferred shipping-inclusive total. If only subtotal exists, add shipping.
        if total_source == "subtotal_price" and shipping is not None:
            total = (total or Decimal("0")) + shipping
            total_source = f"{total_source}+{shipping_source}"
        return {
            "store": self.store_name,
            "order_id": clean_scalar(first_value(order, ("id", "order_id"), "unknown")),
            "order_name": clean_scalar(first_value(order, ("name", "order_number", "order_no"), "unknown")),
            "created_at": clean_scalar(first_value(order, ("created_at", "processed_at"), "unknown")),
            "financial_status": clean_scalar(first_value(order, ("financial_status", "payment_status"), "unknown")),
            "fulfillment_status": clean_scalar(first_value(order, ("fulfillment_status", "shipping_status"), "unknown")),
            "total_price_including_shipping": money_to_string(total),
            "total_field_source": total_source or "unknown",
            "currency": clean_scalar(first_value(order, ("currency", "presentment_currency"), "unknown")),
            "source_name": clean_scalar(first_value(order, ("source_name", "order_source", "source"), "unknown")),
            "landing_site": clean_scalar(first_value(order, ("landing_site", "landing_site_ref", "referring_site"), "unknown")),
            "attribution": compact_attribution(order),
        }


class ShoplazzaClient(BaseStoreClient):
    store_name = "shoplazza"

    def __init__(self) -> None:
        env = load_codex_mcp_env("shoplazza")
        self.store_subdomain = required(env, "SHOPLAZZA_STORE_SUBDOMAIN", self.store_name)
        self.access_token = required(env, "SHOPLAZZA_ACCESS_TOKEN", self.store_name)
        self.api_version = env.get("SHOPLAZZA_API_VERSION", "2025-06")
        base = env.get("SHOPLAZZA_API_BASE_URL") or f"https://{self.store_subdomain}.myshoplaza.com/openapi"
        self.api_base_url = base.rstrip("/")

    def list_orders(self, window: DateWindow) -> list[dict[str, Any]]:
        query = {
            "limit": "250",
            "created_at_min": window.since,
            "created_at_max": window.until,
        }
        url = f"{self.api_base_url}/{self.api_version}/orders?{urllib.parse.urlencode(query)}"
        payload = self._get_json(url, {"Accept": "application/json", "access-token": self.access_token})
        return extract_orders(payload)

    def normalize_order(self, order: dict[str, Any]) -> dict[str, Any]:
        total, total_source = first_money(order, (
            "current_total_price",
            "total_price",
            "total",
            "order_total",
            "amount",
            "subtotal_price",
        ))
        shipping, shipping_source = first_money(order, ("total_shipping_price", "shipping_price", "shipping_fee", "shipping_total"))
        if total_source == "subtotal_price" and shipping is not None:
            total = (total or Decimal("0")) + shipping
            total_source = f"{total_source}+{shipping_source}"
        return {
            "store": self.store_name,
            "order_id": clean_scalar(first_value(order, ("id", "order_id"), "unknown")),
            "order_name": clean_scalar(first_value(order, ("name", "order_number", "order_no"), "unknown")),
            "created_at": clean_scalar(first_value(order, ("created_at", "processed_at"), "unknown")),
            "financial_status": clean_scalar(first_value(order, ("financial_status", "payment_status"), "unknown")),
            "fulfillment_status": clean_scalar(first_value(order, ("fulfillment_status", "shipping_status"), "unknown")),
            "total_price_including_shipping": money_to_string(total),
            "total_field_source": total_source or "unknown",
            "currency": clean_scalar(first_value(order, ("currency", "presentment_currency"), "unknown")),
            "source_name": clean_scalar(first_value(order, ("source_name", "order_source", "source"), "unknown")),
            "landing_site": clean_scalar(first_value(order, ("landing_site", "landing_site_ref", "referring_site"), "unknown")),
            "attribution": compact_attribution(order),
        }


def get_store_client(store: str) -> BaseStoreClient:
    if store == "shopline":
        return ShoplineClient()
    if store == "shoplazza":
        return ShoplazzaClient()
    raise ValueError(f"Unsupported store: {store}")


def required(env: dict[str, str], key: str, store_name: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise StoreApiError(f"Missing {store_name} config key: {key}")
    return value


def extract_orders(payload: Any) -> list[dict[str, Any]]:
    candidates: Iterable[Any]
    if isinstance(payload, list):
        candidates = [payload]
    elif isinstance(payload, dict):
        candidates = (
            payload.get("orders"),
            payload.get("data", {}).get("orders") if isinstance(payload.get("data"), dict) else None,
            payload.get("data"),
            payload.get("items"),
        )
    else:
        candidates = []
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def first_value(order: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in order and order[key] not in (None, ""):
            return order[key]
    return default


def clean_scalar(value: Any) -> str:
    text = str(value)
    if text.strip().lower() in {"", "none", "null"}:
        return "unknown"
    return text


def first_money(order: dict[str, Any], keys: Iterable[str]) -> tuple[Decimal | None, str | None]:
    for key in keys:
        if key in order:
            value = parse_money(order[key])
            if value is not None:
                return value, key
    return None, None


def parse_money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        for key in ("amount", "value", "price"):
            if key in value:
                return parse_money(value[key])
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def money_to_string(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    return f"{value.quantize(Decimal('0.01'))}"


def compact_attribution(order: dict[str, Any]) -> str:
    bits: list[str] = []
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
        value = order.get(key)
        if value:
            bits.append(f"{key}={value}")
    note_attrs = order.get("note_attributes") or order.get("attributes")
    if isinstance(note_attrs, list):
        for item in note_attrs[:10]:
            if isinstance(item, dict):
                name = item.get("name") or item.get("key")
                value = item.get("value")
                if name and value and str(name).lower().startswith("utm"):
                    bits.append(f"{name}={value}")
    elif isinstance(note_attrs, dict):
        for key, value in list(note_attrs.items())[:10]:
            if value and str(key).lower().startswith("utm"):
                bits.append(f"{key}={value}")
    return "; ".join(bits) if bits else "unknown"
