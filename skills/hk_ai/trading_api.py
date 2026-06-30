#!/usr/bin/env python3
"""
港股模拟炒股大赛 MCP API 封装脚本

提供命令行接口调用 MCP 服务的所有工具

授权方式: ApiKey
环境变量: HKAI_MCP_TOKEN
"""

import argparse
import json
import os
import sys

try:
    from coze_workload_identity import requests
except ImportError:
    import requests


# MCP 服务基础端点
MCP_BASE_URL = "https://www.hk.ai/mcp/http"

# 请求 ID 计数器
_request_id = 0


def get_mcp_endpoint() -> str:
    """
    获取 MCP 服务端点（包含用户 Token）

    Returns:
        完整的 MCP 端点 URL
    """
    # 从环境变量获取用户的 Token
    token = os.getenv("HKAI_MCP_TOKEN")

    if not token:
        raise ValueError(
            "缺少必要的凭证配置。请在平台设置页粘贴 HK.AI Token，"
            "或手动设置环境变量 HKAI_MCP_TOKEN。"
        )

    return f"{MCP_BASE_URL}?token={token}"


def call_mcp_tool(tool_name: str, arguments: dict = None) -> dict:
    """
    调用 MCP 工具
    
    Args:
        tool_name: 工具名称
        arguments: 工具参数
        
    Returns:
        API 响应结果
    """
    global _request_id
    _request_id += 1
    
    try:
        endpoint = get_mcp_endpoint()
    except ValueError as e:
        return {"success": False, "error": str(e)}
    
    payload = {
        "jsonrpc": "2.0",
        "id": _request_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments or {}
        }
    }
    
    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        
        # 检查 JSON-RPC 错误
        if "error" in result:
            return {"success": False, "error": result["error"]}

        # 提取工具返回内容
        content = result.get("result", {}).get("content", [])
        if content and len(content) > 0:
            text_content = content[0].get("text", "{}")
            try:
                parsed = json.loads(text_content)
            except json.JSONDecodeError:
                return {"success": True, "data": text_content}
        else:
            parsed = result.get("result", {})

        # MCP 业务层错误：返回 payload shape 是 {"code": 0/1, "msg": "...", "data": ...}
        # code != 0 表示业务被拒（如休市、余额不足），必须报 success=False 让 LLM 知道
        if isinstance(parsed, dict) and parsed.get("code") not in (None, 0):
            return {
                "success": False,
                "error": parsed.get("msg") or f"MCP code {parsed.get('code')}",
                "code": parsed.get("code"),
                "raw": parsed,
            }

        return {"success": True, "data": parsed}
        
    except requests.exceptions.RequestException as e:
        # 不打 str(e) —— HTTPError message 含完整 URL（含 ?token=xxx）会泄漏 HKAI_MCP_TOKEN
        code = getattr(e, "response", None) and getattr(e.response, "status_code", None)
        return {"success": False, "error": f"网络请求失败 ({type(e).__name__}{f' HTTP {code}' if code else ''})"}
    except Exception as e:
        return {"success": False, "error": f"未知错误: {type(e).__name__}"}


# ==================== 行情查询 ====================

def list_selectable_stocks():
    """查询可选股票列表及最新行情"""
    return call_mcp_tool("list_selectable_stocks")


def get_quote_by_symbols(symbols):
    """
    批量查询指定股票代码的最新行情
    
    Args:
        symbols: 股票代码数组或逗号分隔的字符串
    """
    # 处理输入格式
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",")]
    return call_mcp_tool("get_quote_by_symbols", {"symbols": symbols})


def get_market_status():
    """获取市场状态"""
    return call_mcp_tool("get_market_status")


def get_stock_kline(stock_code: str, period: str = "1d", limit: int = 60):
    """
    查询指定股票的K线走势数据（日K或分钟K）

    Args:
        stock_code: 股票代码，如 00700.HK
        period: 周期，1d=日K，1m=分钟K，默认 1d
        limit: 返回K线根数，日K默认60，分钟K默认120，最大500
    """
    return call_mcp_tool(
        "get_stock_kline",
        {"stock_code": stock_code, "period": period, "limit": min(limit, 500)},
    )


# ==================== 账户查询 ====================

def get_account_snapshot():
    """获取账户快照"""
    return call_mcp_tool("get_account_snapshot")


def get_positions():
    """查询当前持仓列表及浮动盈亏"""
    return call_mcp_tool("get_positions")


def get_holdings():
    """持股明细"""
    return call_mcp_tool("get_holdings")


# ==================== 交易操作 ====================

def buy_stock(stock_code: str, quantity: int):
    """
    买入股票
    
    Args:
        stock_code: 股票代码，如 00700.HK
        quantity: 买入数量（股），最小 10 股
    """
    return call_mcp_tool("buy_stock", {"stock_code": stock_code, "quantity": quantity})


def sell_stock(stock_code: str, quantity: int):
    """
    卖出股票
    
    Args:
        stock_code: 股票代码，如 00700.HK
        quantity: 卖出数量（股），最小 10 股
    """
    return call_mcp_tool("sell_stock", {"stock_code": stock_code, "quantity": quantity})


# ==================== 历史记录 ====================

def get_orders_history(limit: int = 50):
    """查询买卖交易历史记录"""
    return call_mcp_tool("get_orders_history", {"limit": min(limit, 200)})


def get_buy_list(page: int = 1, limit: int = 50):
    """查询买入历史"""
    return call_mcp_tool("get_buy_list", {"page": page, "limit": min(limit, 200)})


def get_sell_list(page: int = 1, limit: int = 50):
    """查询卖出历史"""
    return call_mcp_tool("get_sell_list", {"page": page, "limit": min(limit, 200)})


def get_settlement_list(page: int = 1, limit: int = 50):
    """查询结算记录"""
    return call_mcp_tool("get_settlement_list", {"page": page, "limit": min(limit, 200)})


def get_balance_log(page: int = 1, limit: int = 50):
    """查询余额变动流水"""
    return call_mcp_tool("get_balance_log", {"page": page, "limit": min(limit, 200)})


def get_fee_log(page: int = 1, limit: int = 50):
    """查询手续费记录"""
    return call_mcp_tool("get_fee_log", {"page": page, "limit": min(limit, 200)})


# ==================== 规则查询 ====================

def get_competition_rules():
    """获取比赛规则"""
    return call_mcp_tool("get_competition_rules")


# ==================== 命令行接口 ====================

def main():
    parser = argparse.ArgumentParser(
        description="港股模拟炒股大赛 MCP API 客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 行情查询
  python trading_api.py --action list_stocks
  python trading_api.py --action get_quote --symbols "00700.HK,00388.HK"
  python trading_api.py --action market_status
  python trading_api.py --action kline --stock-code 00700.HK --period 1d --limit 60

  # 账户查询
  python trading_api.py --action account
  python trading_api.py --action positions
  python trading_api.py --action holdings

  # 交易操作
  python trading_api.py --action buy --stock-code 00700.HK --quantity 100
  python trading_api.py --action sell --stock-code 00700.HK --quantity 100

  # 历史记录
  python trading_api.py --action orders_history --limit 50
  python trading_api.py --action buy_list --page 1 --limit 50
  python trading_api.py --action sell_list --page 1 --limit 50

  # 规则查询
  python trading_api.py --action rules

注意:
  需要先配置 HK.AI Token，在平台设置页粘贴，或通过环境变量 HKAI_MCP_TOKEN 设置
        """
    )
    
    parser.add_argument(
        "--action",
        required=True,
        choices=[
            # 行情
            "list_stocks", "get_quote", "market_status", "kline",
            # 账户
            "account", "positions", "holdings",
            # 交易
            "buy", "sell",
            # 历史
            "orders_history", "buy_list", "sell_list",
            "settlement_list", "balance_log", "fee_log",
            # 规则
            "rules"
        ],
        help="操作类型"
    )
    
    parser.add_argument("--symbols", help="股票代码，逗号分隔")
    parser.add_argument("--stock-code", help="股票代码")
    parser.add_argument("--quantity", type=int, help="交易数量")
    parser.add_argument("--page", type=int, default=1, help="页码")
    parser.add_argument("--limit", type=int, default=50, help="返回条数")
    parser.add_argument("--period", default="1d", choices=["1d", "1m"], help="K线周期：1d=日K，1m=分钟K")
    
    args = parser.parse_args()
    
    # 执行对应操作
    result = None
    
    if args.action == "list_stocks":
        result = list_selectable_stocks()
    elif args.action == "get_quote":
        if not args.symbols:
            result = {"success": False, "error": "缺少 --symbols 参数"}
        else:
            result = get_quote_by_symbols(args.symbols)
    elif args.action == "market_status":
        result = get_market_status()
    elif args.action == "kline":
        if not args.stock_code:
            result = {"success": False, "error": "缺少 --stock-code 参数"}
        else:
            limit = args.limit if args.limit != 50 else (120 if args.period == "1m" else 60)
            result = get_stock_kline(args.stock_code, args.period, limit)
    elif args.action == "account":
        result = get_account_snapshot()
    elif args.action == "positions":
        result = get_positions()
    elif args.action == "holdings":
        result = get_holdings()
    elif args.action == "buy":
        if not args.stock_code or not args.quantity:
            result = {"success": False, "error": "缺少 --stock-code 或 --quantity 参数"}
        else:
            result = buy_stock(args.stock_code, args.quantity)
    elif args.action == "sell":
        if not args.stock_code or not args.quantity:
            result = {"success": False, "error": "缺少 --stock-code 或 --quantity 参数"}
        else:
            result = sell_stock(args.stock_code, args.quantity)
    elif args.action == "orders_history":
        result = get_orders_history(args.limit)
    elif args.action == "buy_list":
        result = get_buy_list(args.page, args.limit)
    elif args.action == "sell_list":
        result = get_sell_list(args.page, args.limit)
    elif args.action == "settlement_list":
        result = get_settlement_list(args.page, args.limit)
    elif args.action == "balance_log":
        result = get_balance_log(args.page, args.limit)
    elif args.action == "fee_log":
        result = get_fee_log(args.page, args.limit)
    elif args.action == "rules":
        result = get_competition_rules()
    
    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    # 返回状态码
    sys.exit(0 if result and result.get("success") else 1)


if __name__ == "__main__":
    main()
