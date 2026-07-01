# alphasift_hkai

HK.AI competition variant of the alphasift stock-screener. Daily automated trading agent: pull candidate pool → factor screening → LLM ranking → execute via hk_ai MCP.

## What it does

```
pod 启动
  ↓
Phase 1: list_selectable_stocks → 20-50 candidates
Phase 2: get_stock_kline(60 days) × N stocks → compute factors
Phase 3: per strategy:
           L1 hard_filters → top 10 by factor score
           L2 LLM cross-candidate rank → top 3
Phase 4: T+N eval via get_orders_history → confidence_mult
Phase 5: plan buys (cap, lot-rounded) + plan exits (stop-loss)
Phase 6: execute buy_stock / sell_stock via hk_ai MCP
Phase 7: write log/reports/*.json → entrypoint bundles to OSS
```

**State-less**: no local persistence. History comes from hk.ai's own order history API.

## Files

```
alphasift_hkai/
├── main.py                   ← 7-phase entry point
├── hkai_data.py              ← hk_ai MCP wrappers (candidates/kline/orders/account)
├── hkai_factors.py           ← RSI / MA / momentum / vol ratio + scoring
├── hkai_engine.py            ← strategy loader + L1 filter + L2 LLM rank + T+N eval
├── hkai_strategies/          ← 3 HK-specific YAML strategies
│   ├── momentum_quality_hk.yaml
│   ├── oversold_reversal_hk.yaml
│   └── breakout_hk.yaml
├── skills/hk_ai/             ← official MCP wrapper (do not modify)
├── Dockerfile
├── requirements.txt          ← minimal (pandas + openai + pyyaml + requests)
└── alphasift/                ← original alphasift source (kept for reference, NOT installed)
```

## HK Strategies (3 to start)

| Strategy | Category | Logic |
|---|---|---|
| `hk_momentum_quality` | trend | 20d momentum +, vol ratio 1-4, RSI 40-70, above MA20 |
| `hk_oversold_reversal` | reversal | RSI <35, vol ratio >1.2, near MA20 (-8% to +5%) |
| `hk_breakout` | trend | above all MAs + low vol ratio (<1.5, compressing) + RSI 45-70 |

Add more by dropping YAMLs into `hkai_strategies/`.

## Platform Env Vars (hk_ai_agent category)

| Var | Used for |
|---|---|
| `HKAI_MCP_TOKEN` | MCP auth |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LLM_MODEL` / `LLM_API_PARAMS` | L2 LLM ranking |
| `OSS_POD_*` | log upload (handled by entrypoint.sh) |
| `AGENT_ID` / `RUN_ID` | report metadata |

## T+N Evaluation (state-less)

Instead of alphasift's local JSON history, this variant reads `get_orders_history(limit=30)` from hk.ai MCP:

```
past 30 orders → filter to "buy" side → fetch current price for each
              → compute pnl_pct per pick
              → hit_rate = winners / total
              → confidence_mult:
                  hit_rate >= 0.6 → 1.2 (boost position 20%)
                  hit_rate >= 0.5 → 1.0
                  hit_rate >= 0.4 → 0.8
                  hit_rate <  0.4 → 0.6 (defensive)
```

**Trade-off**: no per-strategy attribution (hk.ai doesn't know which strategy recommended each order). Confidence scales the whole agent's position sizing.

## Run Locally

```bash
pip install -r requirements.txt
export HKAI_MCP_TOKEN=...
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=...
export LLM_MODEL=...
python main.py
```

## Limits / Known Issues

- **Candidate pool size**: 20-50 stocks (competition whitelist), not full HK market. alphasift's "全市场扫描" doesn't apply.
- **No fundamental factors**: hk_ai MCP gives K-line + quotes only. No PE/PB/market_cap. All factors are price/volume-derived.
- **No per-strategy attribution in T+N**: confidence scales overall position size, not individual strategy weights.
- **Stop-loss only exit logic**: simplification — no take-profit or trailing stop. Add to `plan_exits()` if needed.
- **Single LLM call per strategy per day**: prompt size capped at 15 candidates. For larger pools, batch.

## Throwaway

HK.AI competition code — remove after 2026-08-01.

## 出处

本项目 fork 自 [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift)，原项目采用 Apache-2.0 协议。
