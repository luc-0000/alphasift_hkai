"""alphasift_hkai engine — L1 screening + L2 LLM ranking + T+N evaluation.

This is the operational core, distilled from alphasift's pipeline.py + ranker.py
+ evaluate.py into one file adapted for the HK.AI competition pod.

Layer mapping:
- L1: deterministic factor-based filter via YAML hard_filters
- L2: LLM cross-candidate ranking (platform-injected OPENAI_*)
- T+N: read get_orders_history to compute hit rate → adjust confidence

HK.AI throwaway — remove after 2026-08-01.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hkai_data import (
    fetch_account_cash,
    fetch_candidate_stocks,
    fetch_holdings,
    fetch_kline,
    fetch_recent_orders,
)
from hkai_factors import compute_factors, score_candidate

logger = logging.getLogger(__name__)

HKAI_STRATEGIES_DIR = Path(__file__).resolve().parent / "hkai_strategies"
KLINE_LOOKBACK_DAYS = 60
DEFAULT_TOP_N = 3
MIN_UNIT = 10  # HK lot size
DEFAULT_ORDER_CAP = 500_000


# ---------------------------------------------------------------------------
# Strategy YAML loader
# ---------------------------------------------------------------------------

@dataclass
class Strategy:
    name: str
    display_name: str
    description: str
    category: str
    hard_filters: dict
    factor_weights: dict[str, float]
    instructions: str = ""
    market_regimes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> "Strategy":
        return cls(
            name=raw.get("name", ""),
            display_name=raw.get("display_name", raw.get("name", "")),
            description=raw.get("description", ""),
            category=raw.get("category", ""),
            hard_filters=raw.get("hard_filters", {}) or {},
            factor_weights=raw.get("factor_weights", {}) or {},
            instructions=raw.get("instructions", ""),
            market_regimes=raw.get("market_regimes", []) or [],
        )


def load_strategies(strategies_dir: Path = HKAI_STRATEGIES_DIR) -> list[Strategy]:
    strategies: list[Strategy] = []
    if not strategies_dir.exists():
        return strategies
    for path in sorted(strategies_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                strategies.append(Strategy.from_dict(raw))
        except Exception as exc:
            logger.warning("[loader] failed to parse %s: %s", path.name, type(exc).__name__)
    return strategies


# ---------------------------------------------------------------------------
# L1 deterministic screening
# ---------------------------------------------------------------------------

def apply_hard_filters(stock: dict, filters: dict) -> bool:
    """Return True if stock passes all hard_filters based on its factors dict."""
    factors = stock.get("factors", {})

    for key, want in filters.items():
        if key in ("above_ma5", "above_ma10", "above_ma20"):
            val = factors.get(key)
            if val is None:
                return False
            if bool(val) != bool(want):
                return False
            continue

        # numeric comparisons: key like rsi_14_max, vol_ratio_min, etc.
        if key.endswith("_min"):
            field_name = key[:-4]
            val = factors.get(field_name)
            if val is None or val < want:
                return False
        elif key.endswith("_max"):
            field_name = key[:-4]
            val = factors.get(field_name)
            if val is None or val > want:
                return False

    return True


def screen_candidates(
    stocks: list[dict],
    strategy: Strategy,
    top_n: int = 10,
) -> list[dict]:
    """Apply hard_filters then score by factor_weights; return top N."""
    passed = [s for s in stocks if apply_hard_filters(s, strategy.hard_filters)]
    for s in passed:
        s["score"] = score_candidate(s.get("factors", {}), strategy.factor_weights)
    passed.sort(key=lambda s: s.get("score", 0), reverse=True)
    return passed[:top_n]


# ---------------------------------------------------------------------------
# L2 LLM ranking
# ---------------------------------------------------------------------------

async def llm_rank(
    candidates: list[dict],
    strategy: Strategy,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict]:
    """Ask the platform LLM to pick the top N candidates for this strategy.

    Uses OPENAI_* env vars injected by the hk_ai_agent platform.
    """
    if not candidates:
        return []

    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("[L2] openai SDK missing — falling back to L1 score order")
        return candidates[:top_n]

    api_key = os.getenv("OPENAI_API_KEY") or ""
    base_url = os.getenv("OPENAI_BASE_URL") or ""
    model = os.getenv("LLM_MODEL") or "deepseek-chat"
    if not api_key or not base_url:
        logger.warning("[L2] missing OPENAI_API_KEY / OPENAI_BASE_URL — using L1 order")
        return candidates[:top_n]

    snapshot = []
    for c in candidates[:15]:  # cap prompt size
        f = c.get("factors", {})
        snapshot.append({
            "code": c.get("code"),
            "name": c.get("name"),
            "price": c.get("price"),
            "change_pct": c.get("change_pct"),
            "rsi_14": f.get("rsi_14"),
            "momentum_20d": f.get("momentum_20d"),
            "vol_ratio": f.get("vol_ratio_1d_5d"),
            "dist_to_ma20_pct": f.get("dist_to_ma20_pct"),
            "factor_score": c.get("score"),
        })

    prompt = f"""你是港股模拟炒股大赛的选股专家。基于策略「{strategy.display_name}」筛选出今日最值得买入的 {top_n} 只标的。

策略目标：
{strategy.instructions or strategy.description}

候选股（按 L1 因子分排序，前 {len(snapshot)} 只）：
{json.dumps(snapshot, ensure_ascii=False, indent=2)}

要求：
- 优先考虑因子组合最匹配策略目标的标的
- 回避当日已大涨（>5%）或已大跌（<-5%）的标的（除非策略明确抓反转）
- 输出严格 JSON：{{"picks": [{{"stock_code": "...", "reason": "一句话理由"}}]}}
- 只输出 JSON，不要解释"""

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        msg = resp.choices[0].message
        content = msg.content or ""
        if not content:
            reasoning = getattr(msg, "reasoning_content", None) or ""
            if reasoning:
                print(f"[L2] content empty, using reasoning_content ({len(reasoning)} chars)")
                content = reasoning
        finish = resp.choices[0].finish_reason
        print(f"[L2] {strategy.name} finish_reason={finish} content_len={len(content)}")
    except Exception as exc:
        code = getattr(exc, "response", None) and getattr(exc.response, "status_code", None)
        print(f"[L2] {strategy.name} request failed: {type(exc).__name__}{f' HTTP {code}' if code else ''}")
        return candidates[:top_n]

    return _parse_picks(content, candidates, top_n)


def _parse_picks(content: str, candidates: list[dict], top_n: int) -> list[dict]:
    if not content:
        return candidates[:top_n]
    try:
        text = content.strip().strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        parsed = json.loads(text)
        picks = parsed.get("picks", []) if isinstance(parsed, dict) else []

        code_to_stock = {c["code"]: c for c in candidates if c.get("code")}
        out = []
        for p in picks[:top_n]:
            if not isinstance(p, dict):
                continue
            code = p.get("stock_code") or p.get("code") or ""
            stock = code_to_stock.get(code)
            if stock:
                stock = dict(stock)
                stock["llm_reason"] = p.get("reason", "")
                out.append(stock)
        return out
    except (json.JSONDecodeError, AttributeError) as exc:
        print(f"[L2] parse failed: {type(exc).__name__} — falling back to L1 order")
        return candidates[:top_n]


# ---------------------------------------------------------------------------
# T+N evaluation — state-less via get_orders_history
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    total_picks: int
    winners: int
    losers: int
    hit_rate: float
    avg_pnl_pct: float
    confidence_mult: float  # multiplier for position sizing


def evaluate_history(lookback_orders: int = 30) -> EvalResult:
    """Read past orders via hk_ai MCP, compute T+N hit rate, derive confidence.

    hit_rate → confidence_mult mapping:
      hit_rate >= 0.6 → 1.2 (boost position by 20%)
      hit_rate >= 0.5 → 1.0
      hit_rate >= 0.4 → 0.8
      hit_rate <  0.4 → 0.6 (defensive)
    """
    orders = fetch_recent_orders(limit=lookback_orders)
    buys = [o for o in orders if str(o.get("side", "")).lower() == "buy" and o.get("stock_code")]

    if not buys:
        print(f"[T+N] no past buy orders — using neutral confidence (1.0)")
        return EvalResult(0, 0, 0, 0.0, 0.0, 1.0)

    # Compute P&L per past buy vs current price (state-less)
    pnls: list[float] = []
    from hkai_data import fetch_current_price
    for o in buys[-20:]:  # cap calls
        entry = o.get("price") or 0
        if not entry:
            continue
        cur = fetch_current_price(o["stock_code"])
        if cur > 0:
            pnls.append((cur - entry) / entry * 100)

    if not pnls:
        print(f"[T+N] could not price past {len(buys)} buys — neutral confidence")
        return EvalResult(len(buys), 0, 0, 0.0, 0.0, 1.0)

    winners = sum(1 for p in pnls if p > 1.0)   # +1% threshold
    losers = sum(1 for p in pnls if p < -1.0)
    hit_rate = winners / len(pnls)
    avg_pnl = sum(pnls) / len(pnls)

    if hit_rate >= 0.6:
        mult = 1.2
    elif hit_rate >= 0.5:
        mult = 1.0
    elif hit_rate >= 0.4:
        mult = 0.8
    else:
        mult = 0.6

    print(
        f"[T+N] past {len(pnls)} buys: {winners} winners, {losers} losers, "
        f"hit_rate={hit_rate:.1%}, avg_pnl={avg_pnl:+.2f}%, confidence_mult={mult}"
    )

    return EvalResult(
        total_picks=len(buys),
        winners=winners,
        losers=losers,
        hit_rate=hit_rate,
        avg_pnl_pct=avg_pnl,
        confidence_mult=mult,
    )


# ---------------------------------------------------------------------------
# Position sizing + execution
# ---------------------------------------------------------------------------

def plan_buys(
    picks: list[dict],
    available_cash: float,
    confidence_mult: float,
    cap_per_order: float = DEFAULT_ORDER_CAP,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict]:
    """Compute buy orders: cap budget per pick, round to HK lot size (10)."""
    if not picks or available_cash <= 0:
        return []

    picks = picks[:top_n]
    cash_pool = min(available_cash * 0.9, cap_per_order * len(picks)) * confidence_mult
    budget_per_pick = cash_pool / len(picks)

    orders = []
    for p in picks:
        price = p.get("price") or 0
        if not price:
            continue
        raw_qty = int(budget_per_pick / price)
        qty = (raw_qty // MIN_UNIT) * MIN_UNIT
        if qty < MIN_UNIT:
            print(f"[Plan] {p['code']} skip — min lot HK$ {price * MIN_UNIT:,.2f} > budget HK$ {budget_per_pick:,.2f}")
            continue
        orders.append({
            "code": p["code"],
            "name": p.get("name", ""),
            "price": price,
            "quantity": qty,
            "order_amount": qty * price,
            "reason": p.get("llm_reason", ""),
        })
    return orders


def plan_exits(holdings: list[dict], stop_loss_pct: float = 0.08) -> list[dict]:
    """Sell existing positions where current price has fallen > stop_loss_pct
    below average cost. Simplified — no take-profit logic."""
    from hkai_data import fetch_current_price

    sells = []
    for h in holdings:
        code = h.get("code")
        avg = h.get("avg_price") or 0
        qty = h.get("quantity") or 0
        if not code or not avg or qty < MIN_UNIT:
            continue
        cur = fetch_current_price(code)
        if cur <= 0:
            continue
        change = (cur - avg) / avg
        if change < -stop_loss_pct:
            sell_qty = (int(qty) // MIN_UNIT) * MIN_UNIT
            if sell_qty >= MIN_UNIT:
                sells.append({
                    "code": code,
                    "quantity": sell_qty,
                    "avg_price": avg,
                    "current_price": cur,
                    "loss_pct": change * 100,
                })
    return sells
