"""HK.AI 港股模拟炒股大赛工具包。

用户代码这样用：

    from skills.hk_ai import buy_stock, get_account_snapshot

平台在 pod 启动时注入 HKAI_TOKEN 环境变量。
"""

from .trading_api import (
    list_selectable_stocks,
    get_quote_by_symbols,
    get_market_status,
    get_stock_kline,
    get_account_snapshot,
    get_positions,
    get_holdings,
    buy_stock,
    sell_stock,
    get_orders_history,
    get_buy_list,
    get_sell_list,
    get_settlement_list,
    get_balance_log,
    get_fee_log,
    get_competition_rules,
)

__all__ = [
    "list_selectable_stocks",
    "get_quote_by_symbols",
    "get_market_status",
    "get_stock_kline",
    "get_account_snapshot",
    "get_positions",
    "get_holdings",
    "buy_stock",
    "sell_stock",
    "get_orders_history",
    "get_buy_list",
    "get_sell_list",
    "get_settlement_list",
    "get_balance_log",
    "get_fee_log",
    "get_competition_rules",
]
