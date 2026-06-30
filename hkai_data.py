"""HK.AI data layer for alphasift_hkai.

Wraps skills.hk_ai.trading_api MCP calls to provide:
- candidate stock list (replaces full-market snapshot)
- K-line history per stock (replaces daily history)
- past orders (replaces local run history — state-less T+N evaluation)

HK.AI throwaway — remove after 2026-08-01.
"""
from __future__ import annotations

import logging
from typing import Any

from skills.hk_ai.trading_api import (
    get_buy_list,
    get_quote_by_symbols,
    get_stock_kline,
    list_selectable_stocks,
    get_orders_history,
    get_account_snapshot,
    get_positions,
)

logger = logging.getLogger(__name__)


def _unwrap(resp: Any, list_key: bool = False):
    """Drill into MCP response shape {success, data:{code,msg,data}}."""
    if not isinstance(resp, dict):
        return [] if list_key else {}
    if not resp.get("success"):
        return [] if list_key else {}
    data = resp.get("data")
    if isinstance(data, dict):
        inner = data.get("data")
        if inner is not None:
            return inner
        return data
    if isinstance(data, list):
        return data
    return [] if list_key else {}


def fetch_candidate_stocks(limit: int = 50) -> list[dict]:
    """Pull the competition's selectable stock list.

    Replaces alphasift's fetch_cn_snapshot / fetch_us_snapshot.
    Returns list of {stock_code, stock_name, quote:{price, change_pct, ...}}.
    """
    raw = _unwrap(list_selectable_stocks(), list_key=True)
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:limit]:
        if not isinstance(item, dict):
            continue
        code = item.get("stock_code") or item.get("code") or ""
        if not code:
            continue
        out.append({
            "code": str(code),
            "name": item.get("stock_name") or item.get("name") or "",
            "price": _extract_price(item),
            "change_pct": _extract_change_pct(item),
            "volume": _extract_volume(item),
        })
    return out


def fetch_kline(stock_code: str, days: int = 60) -> list[dict]:
    """Pull daily K-line history for a stock. Returns bars oldest→newest.

    hk_ai MCP shape: {success, data:{code,msg,data:{stock_code,period,kline:[bars]}}}
    """
    resp = get_stock_kline(stock_code, period="1d", limit=days)
    if not isinstance(resp, dict) or not resp.get("success"):
        return []

    # Drill to inner data; kline list is under "kline" key
    data = resp.get("data", {})
    if isinstance(data, dict):
        inner = data.get("data", data)
    else:
        inner = data

    kline = None
    if isinstance(inner, dict):
        kline = inner.get("kline") or inner.get("klines") or inner.get("bars")
    elif isinstance(inner, list):
        kline = inner  # some endpoints return list directly

    if not isinstance(kline, list):
        return []

    bars = []
    for b in kline:
        if not isinstance(b, dict):
            continue
        bars.append({
            "date": b.get("date") or b.get("day") or b.get("time") or "",
            "open": _f(b, ["open", "Open"]),
            "high": _f(b, ["high", "High"]),
            "low": _f(b, ["low", "Low"]),
            "close": _f(b, ["close", "Close", "price"]),
            "volume": _f(b, ["volume", "vol", "Volume"]),
        })
    return bars


def fetch_recent_orders(limit: int = 30) -> list[dict]:
    """Past executed orders — used as state-less T+N memory."""
    raw = _unwrap(get_orders_history(limit=limit), list_key=True)
    if not isinstance(raw, list):
        return []
    out = []
    for o in raw:
        if not isinstance(o, dict):
            continue
        out.append({
            "stock_code": o.get("stock_code") or o.get("code") or "",
            "side": o.get("side") or o.get("type") or "",
            "price": _f(o, ["price", "deal_price", "avg_price", "buy_price"]),
            "quantity": _f(o, ["quantity", "filled_quantity", "shares", "buy_quantity"]),
            "timestamp": (
                o.get("trade_time")
                or o.get("created_at")
                or o.get("time")
                or o.get("date")
                or ""
            ),
            "status": o.get("status") or "",
        })
    return out


def fetch_account_cash() -> float:
    """Available cash from account snapshot.

    hk_ai shape: data.data.current_balance (string), frozen_balance separate.
    """
    acct = _unwrap(get_account_snapshot())
    # hk_ai uses current_balance; tolerate aliases for other platforms
    available = (
        acct.get("current_balance")
        or acct.get("available")
        or acct.get("cash")
        or acct.get("balance")
        or 0
    )
    try:
        return float(available)
    except (TypeError, ValueError):
        return 0.0


def fetch_holdings() -> list[dict]:
    """Current OPEN positions (status=0, holding_quantity > 0).

    hk_ai shape: data.data[].{stock_code, holding_quantity, latest_price, status}
    Note: hk.ai positions have no avg_price field — cost basis must come from
    get_orders_history. We leave avg_price=0 here; downstream code that needs
    cost basis should fetch_orders_history separately.
    """
    raw = _unwrap(get_positions(), list_key=True)
    if not isinstance(raw, list):
        return []
    out = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        code = p.get("stock_code") or p.get("code") or ""
        if not code:
            continue
        # status: 0 = open, 1 = closed; holding_quantity may be 0 for closed
        status = p.get("status")
        qty = _f(p, ["holding_quantity", "quantity", "shares", "volume"])
        if status == 1 or qty <= 0:
            continue
        out.append({
            "code": str(code),
            "quantity": qty,
            "latest_price": _f(p, ["latest_price", "price"]),
            "avg_price": _f(p, ["avg_price", "cost_price", "open_price"]),
        })
    return out


def fetch_current_price(stock_code: str) -> float:
    """Quick single-stock price lookup."""
    raw = _unwrap(get_quote_by_symbols([stock_code]), list_key=True)
    if isinstance(raw, list) and raw:
        first = raw[0] if isinstance(raw[0], dict) else {}
        return _extract_price(first)
    return 0.0


def fetch_buy_prices(limit: int = 50) -> dict[str, float]:
    """Latest buy price per stock_code from get_buy_list.

    Replaces missing avg_price in get_positions (hk.ai MCP doesn't return
    cost basis). Returns {stock_code: most_recent_buy_price}.
    """
    resp = get_buy_list(page=1, limit=limit)
    if not isinstance(resp, dict) or not resp.get("success"):
        return {}
    data = resp.get("data", {})
    if isinstance(data, dict):
        inner = data.get("data", data)
    else:
        inner = data
    # buy_list shape: {list: [...], total, page, limit}
    items = (
        inner.get("list") if isinstance(inner, dict) else None
    ) or (inner if isinstance(inner, list) else [])
    if not isinstance(items, list):
        return {}
    out: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("stock_code") or item.get("code") or ""
        if not code:
            continue
        price = _f(item, ["buy_price", "price", "deal_price"])
        if price > 0:
            # keep the most recent (first occurrence; buy_list is desc by time)
            out.setdefault(str(code), price)
    return out


# ---------------------------------------------------------------------------
# Helpers — tolerate field name variance from MCP
# ---------------------------------------------------------------------------

def _f(d: dict, keys: list[str]) -> float:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _extract_price(item: dict) -> float:
    """Tolerate flat (latest_price) and nested (quote.price) shapes."""
    for k in ["latest_price", "price", "last", "current_price"]:
        v = item.get(k)
        if v in (None, "", 0):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    quote = item.get("quote") if isinstance(item.get("quote"), dict) else {}
    for k in ["price", "last", "current_price"]:
        v = quote.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _extract_change_pct(item: dict) -> float:
    """hk_ai returns changeRate as string ('+' / '-' / ''), tolerate it."""
    for k in ["changeRate", "change_rate", "change_pct", "pct_chg", "change_percent"]:
        v = item.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    quote = item.get("quote") if isinstance(item.get("quote"), dict) else {}
    for k in ["change_pct", "pct_chg"]:
        v = quote.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _extract_volume(item: dict) -> float:
    for k in ["volume", "vol", "turnover"]:
        v = item.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    quote = item.get("quote") if isinstance(item.get("quote"), dict) else {}
    for k in ["volume", "vol"]:
        v = quote.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0
