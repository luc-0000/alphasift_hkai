# alphasift_hkai

HK.AI competition trading agent. Pulls the candidate pool from the hk_ai MCP,
runs factor + LLM screening across 3 strategies, then executes buys/sells via MCP.

Job mode — pod runs `python main.py` once and exits. No server, no local state;
history comes from hk.ai's own order API.

## Run

```bash
pip install -r requirements.txt
export HKAI_MCP_TOKEN=...
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=...
export LLM_MODEL=...
python main.py
```

## Files

| File | Purpose |
|---|---|
| `main.py` | Entry point — 7-phase pipeline |
| `hkai_data.py` | hk_ai MCP wrappers (candidates / kline / orders / account) |
| `hkai_factors.py` | RSI / MA / momentum / volume ratio + scoring |
| `hkai_engine.py` | Strategy loader, L1 factor filter, L2 LLM rank, T+N confidence |
| `hkai_strategies/*.yaml` | 3 HK strategies (momentum_quality / oversold_reversal / breakout) |
| `skills/hk_ai/` | Official MCP toolkit (do not modify) |
| `alphasift/` | Original alphasift source (kept for reference, not installed) |

## Env vars

- `HKAI_MCP_TOKEN` — MCP auth
- `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LLM_MODEL` / `LLM_API_PARAMS` — L2 LLM ranking
- `OSS_POD_*` / `AGENT_ID` / `RUN_ID` — auto-injected on the platform

Add more strategies by dropping YAMLs into `hkai_strategies/`.

Throwaway — remove after 2026-08-01.

## Attribution

Forked from [ZhuLinsen/alphasift](https://github.com/ZhuLinsen/alphasift), licensed under Apache-2.0.
