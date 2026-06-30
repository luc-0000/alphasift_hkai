"""alphasift_hkai — HK.AI competition stock-screener trading agent.

Pipeline:
  1. Pull candidate stocks + 60-day K-line from hk.ai MCP
  2. Compute factors (RSI, MA, momentum, volume ratio)
  3. L1 deterministic screening per strategy
  4. L2 LLM cross-candidate ranking per strategy
  5. T+N evaluation via get_orders_history → confidence multiplier
  6. Plan buys (rounded to HK lot 10, capped) + plan exits (stop-loss)
  7. Execute via hk_ai MCP

State-less: no local persistence. History comes from hk.ai's own order history.

HK.AI throwaway — remove after 2026-08-01.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    if (ROOT / ".env").exists():
        load_dotenv(override=False)
except ImportError:
    pass

from hkai_data import (  # noqa: E402
    fetch_account_cash,
    fetch_candidate_stocks,
    fetch_holdings,
    fetch_kline,
)
from hkai_engine import (  # noqa: E402
    DEFAULT_ORDER_CAP,
    DEFAULT_TOP_N,
    KLINE_LOOKBACK_DAYS,
    evaluate_history,
    load_strategies,
    llm_rank,
    plan_buys,
    plan_exits,
    screen_candidates,
)
from skills.hk_ai.trading_api import (  # noqa: E402
    buy_stock,
    sell_stock,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("alphasift_hkai")


async def main():
    print("=== alphasift_hkai starting ===")
    print(f"[Env] LLM_MODEL={os.getenv('LLM_MODEL', '<unset>')}")
    print(f"[Env] OPENAI_BASE_URL={os.getenv('OPENAI_BASE_URL', '<unset>')}")
    print(f"[Env] HKAI_MCP_TOKEN={'<set>' if os.getenv('HKAI_MCP_TOKEN') else '<MISSING>'}")
    print(f"[Env] RUN_ID={os.getenv('RUN_ID', '<unset>')} AGENT_ID={os.getenv('AGENT_ID', '<unset>')}")

    # ----- Phase 1: Load strategies + pull candidates -----
    strategies = load_strategies()
    if not strategies:
        print("[Main] no strategies loaded — exiting")
        return
    print(f"\n=== Phase 1: loaded {len(strategies)} strategies ===")
    for s in strategies:
        print(f"  - {s.name} ({s.category}) — {s.display_name}")

    print("\n=== Phase 2: pull candidate stocks + K-line ===")
    stocks = fetch_candidate_stocks(limit=50)
    if not stocks:
        print("[Main] no candidates from list_selectable_stocks — exiting")
        return
    print(f"[Candidates] pulled {len(stocks)} stocks")

    enriched = []
    for s in stocks:
        bars = fetch_kline(s["code"], days=KLINE_LOOKBACK_DAYS)
        if len(bars) < 10:
            continue
        from hkai_factors import compute_factors
        factors = compute_factors(bars)
        if not factors:
            continue
        enriched.append({**s, "factors": factors, "bars_count": len(bars)})
    print(f"[Enriched] {len(enriched)} stocks with computed factors (skipped {len(stocks) - len(enriched)})")

    if not enriched:
        print("[Main] no enriched stocks — exiting")
        return

    # ----- Phase 3: L1 + L2 per strategy -----
    print("\n=== Phase 3: L1 screening + L2 LLM ranking per strategy ===")
    all_picks: list[dict] = []
    for strat in strategies:
        screened = screen_candidates(enriched, strat, top_n=10)
        if not screened:
            print(f"[{strat.name}] L1 filter: 0 passed — skip")
            continue
        print(f"[{strat.name}] L1 filter: {len(screened)} passed (top score {screened[0].get('score', 0):.1f})")
        ranked = await llm_rank(screened, strat, top_n=DEFAULT_TOP_N)
        for p in ranked:
            p["strategy"] = strat.name
        all_picks.extend(ranked)
        for p in ranked:
            print(f"  [{strat.name}] picked {p['code']} ({p.get('name', '')}) — {p.get('llm_reason', '')[:80]}")

    # Dedup picks across strategies — keep highest score
    seen: dict[str, dict] = {}
    for p in all_picks:
        code = p.get("code")
        if not code:
            continue
        if code not in seen or p.get("score", 0) > seen[code].get("score", 0):
            seen[code] = p
    final_picks = list(seen.values())[:DEFAULT_TOP_N]
    print(f"\n[Dedup] final {len(final_picks)} unique picks across strategies")

    if not final_picks:
        print("[Main] no picks — checking exits only")

    # ----- Phase 4: T+N evaluation -----
    print("\n=== Phase 4: T+N evaluation (via get_orders_history) ===")
    eval_result = evaluate_history(lookback_orders=30)

    # ----- Phase 5: Plan orders -----
    print("\n=== Phase 5: plan orders ===")
    available = fetch_account_cash()
    print(f"[Cash] available: HK$ {available:,.2f}")

    # Compute desired total spend: cap-per-order × N picks, scaled by confidence
    n_picks = max(len(final_picks), 1)
    desired_spend = min(available * 0.9, DEFAULT_ORDER_CAP * n_picks) * eval_result.confidence_mult
    shortfall = max(0.0, desired_spend - available)
    print(
        f"[Budget] desired=HK$ {desired_spend:,.2f} "
        f"(confidence×{eval_result.confidence_mult} × cap HK$ {DEFAULT_ORDER_CAP:,} × {n_picks} picks, "
        f"capped at cash×0.9), shortfall=HK$ {shortfall:,.2f}"
    )

    # Plan exits FIRST so we can redeploy freed cash into new picks
    holdings = fetch_holdings()
    print(f"[Holdings] {len(holdings)} open positions")
    sell_orders = plan_exits(
        holdings,
        stop_loss_pct=0.08,
        free_cash_target=shortfall,
        confidence_mult=eval_result.confidence_mult,
    )
    for o in sell_orders:
        trigger = o.get("trigger", "?")
        print(
            f"[Sell:{trigger}] {o['code']} x {o['quantity']} "
            f"(avg HK$ {o['avg_price']:,.2f} via {o.get('cost_source', '?')} → "
            f"now HK$ {o['current_price']:,.2f}, {o['loss_pct']:+.2f}%)"
        )

    # Proceeds from sells (assume instant settlement in competition sim)
    sell_proceeds = sum(s["quantity"] * s["current_price"] for s in sell_orders)
    effective_cash = available + sell_proceeds
    if sell_proceeds > 0:
        print(f"[Cash] after sells: HK$ {effective_cash:,.2f} (+HK$ {sell_proceeds:,.2f})")

    buy_orders = plan_buys(
        final_picks,
        available_cash=effective_cash,
        confidence_mult=eval_result.confidence_mult,
        top_n=DEFAULT_TOP_N,
    )
    for o in buy_orders:
        print(
            f"[Buy] {o['code']} ({o.get('name', '')}) x {o['quantity']} "
            f"@ HK$ {o['price']:,.2f} ≈ HK$ {o['order_amount']:,.2f} — {o.get('reason', '')[:80]}"
        )

    # ----- Phase 6: Execute -----
    print("\n=== Phase 6: execute via hk.ai MCP ===")
    for o in sell_orders:
        result = sell_stock(o["code"], o["quantity"])
        _print_trade_result("SELL", o["code"], result)

    for o in buy_orders:
        result = buy_stock(o["code"], o["quantity"])
        _print_trade_result("BUY", o["code"], result)

    # ----- Phase 7: Save report to log/reports/ for OSS upload -----
    print("\n=== Phase 7: write report ===")
    _write_report(
        strategies=strategies,
        candidates_count=len(stocks),
        enriched_count=len(enriched),
        picks=final_picks,
        eval_result=eval_result,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
    )

    print("\n=== done ===")


def _print_trade_result(side: str, code: str, result):
    if not isinstance(result, dict):
        print(f"[Exec] {side} {code} unknown shape: {type(result).__name__}")
        return
    if result.get("success"):
        d = result.get("data", {})
        if isinstance(d, dict):
            inner = d.get("data", d)
        else:
            inner = d
        if not isinstance(inner, dict):
            inner = {}
        print(
            f"[Exec] {side} {code} OK | order_id={inner.get('order_id', '?')} | "
            f"price={inner.get('price', '?')} | qty={inner.get('quantity', '?')} | "
            f"fee={inner.get('fee', '?')}"
        )
    else:
        # Never print raw exception (HTTPError msg leaks token in URL)
        print(f"[Exec] {side} {code} FAILED: {result.get('error')}")


def _write_report(*, strategies, candidates_count, enriched_count, picks, eval_result,
                  buy_orders, sell_orders):
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": os.getenv("RUN_ID", ""),
        "agent_id": os.getenv("AGENT_ID", ""),
        "strategies_loaded": [s.name for s in strategies],
        "candidates_pulled": candidates_count,
        "enriched_with_factors": enriched_count,
        "picks": [
            {
                "code": p.get("code"),
                "name": p.get("name"),
                "strategy": p.get("strategy"),
                "score": p.get("score"),
                "price": p.get("price"),
                "reason": p.get("llm_reason"),
            }
            for p in picks
        ],
        "t_plus_n_eval": {
            "total_past_picks": eval_result.total_picks,
            "winners": eval_result.winners,
            "losers": eval_result.losers,
            "hit_rate": round(eval_result.hit_rate, 4),
            "avg_pnl_pct": round(eval_result.avg_pnl_pct, 4),
            "confidence_mult": eval_result.confidence_mult,
        },
        "planned_buys": buy_orders,
        "planned_sells": sell_orders,
    }
    report_dir = Path("log/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / f"alphasift_run_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[Report] saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
