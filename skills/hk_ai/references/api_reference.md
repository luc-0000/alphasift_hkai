# 港股模拟炒股大赛 API 参考

## 目录

1. [概览](#概览)
2. [行情查询 API](#行情查询-api)
3. [账户查询 API](#账户查询-api)
4. [交易操作 API](#交易操作-api)
5. [历史记录 API](#历史记录-api)
6. [规则查询 API](#规则查询-api)
7. [交易规则说明](#交易规则说明)

---

## 概览

本文档描述港股模拟炒股大赛 MCP 服务的所有 API 接口。

**服务端点**: `https://www.hk.ai/mcp/http`

**调用方式**: JSON-RPC 2.0 over HTTP POST

**基础请求格式**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "工具名称",
    "arguments": { 参数对象 }
  }
}
```

---

## 行情查询 API

### list_selectable_stocks

查询可选股票列表及最新行情。

**参数**: 无

**返回示例**:
```json
{
  "success": true,
  "data": [
    {
      "symbol": "00700.HK",
      "name": "腾讯控股",
      "price": 380.00,
      "change": 5.20,
      "change_percent": 1.38
    }
  ]
}
```

### get_quote_by_symbols

批量查询指定股票代码的最新行情。

**参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| symbols | array/string | 是 | 股票代码数组或逗号分隔字符串 |

**调用示例**:
```bash
python trading_api.py --action get_quote --symbols "00700.HK,00388.HK"
```

**返回示例**:
```json
{
  "success": true,
  "data": [
    {
      "symbol": "00700.HK",
      "name": "腾讯控股",
      "price": 380.00,
      "volume": 12500000
    }
  ]
}
```

### get_stock_kline

查询指定股票的 K 线走势数据（基于行情缓存，可绘日K/分钟K）。

**参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| stock_code | string | 是 | 股票代码，如 00700.HK |
| period | string | 否 | 周期：1d=日K，1m=分钟K，默认 1d |
| limit | integer | 否 | 返回K线根数，日K默认 60，分钟K默认 120，最大 500 |

**调用示例**:
```bash
# 日K线
python trading_api.py --action kline --stock-code 00700.HK --period 1d --limit 60

# 分钟K线
python trading_api.py --action kline --stock-code 00700.HK --period 1m --limit 120
```

**返回说明**: `data` 内为服务端原始响应，其中 `data.kline` 为 K 线数组，每项含 `date`（日K）或 `time`（分钟K）、`open`、`high`、`low`、`close`。

### get_market_status

获取市场状态：交易时间、数据更新时间、服务可用性。

**参数**: 无

---

## 账户查询 API

### get_account_snapshot

获取账户快照：当前余额、总盈亏、可用资金。

**参数**: 无

**返回示例**:
```json
{
  "success": true,
  "data": {
    "balance": 1000000.00,
    "available": 800000.00,
    "total_profit": 50000.00,
    "total_profit_percent": 5.0
  }
}
```

### get_positions

查询当前持仓列表及浮动盈亏。

**参数**: 无

### get_holdings

持股明细：查询当前持仓列表及最新价。

**参数**: 无

---

## 交易操作 API

### buy_stock

买入股票。

**参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| stock_code | string | 是 | 股票代码，如 00700.HK |
| quantity | integer | 是 | 买入数量（股），最小 10 股 |

**调用示例**:
```bash
python trading_api.py --action buy --stock-code 00700.HK --quantity 100
```

**返回示例**:
```json
{
  "success": true,
  "data": {
    "order_id": "20240115001",
    "stock_code": "00700.HK",
    "quantity": 100,
    "price": 380.00,
    "amount": 38000.00,
    "fee": 38.00
  }
}
```

### sell_stock

卖出股票。

**参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| stock_code | string | 是 | 股票代码 |
| quantity | integer | 是 | 卖出数量（股），最小 10 股 |

**调用示例**:
```bash
python trading_api.py --action sell --stock-code 00700.HK --quantity 100
```

---

## 历史记录 API

### get_orders_history

查询买卖交易历史记录（分页）。

**参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| limit | integer | 否 | 返回记录数，默认 50，最大 200 |

### get_buy_list

查询买入历史（分页）。

**参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| page | integer | 否 | 页码，从 1 开始 |
| limit | integer | 否 | 返回条数，默认 50 |

### get_sell_list

查询卖出历史（分页）。

**参数**:
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| page | integer | 否 | 页码，从 1 开始 |
| limit | integer | 否 | 返回条数，默认 50 |

### get_settlement_list

查询结算记录（分页）。

**参数**:
 同 get_sell_list

### get_balance_log

账户余额记录：按时间顺序的余额变动流水（分页）。

**参数**:
 同 get_sell_list

### get_fee_log

手续费记录：买卖手续费明细（分页）。

**参数**:
 同 get_sell_list

---

## 规则查询 API

### get_competition_rules

获取比赛规则。

**参数**: 无

**返回示例**:
```json
{
  "success": true,
  "data": {
    "min_unit": 10,
    "commission_rate": 0.001,
    "min_commission": 5.0,
    "max_order_amount": 500000.0,
    "max_daily_orders": 200
  }
}
```

---

## 交易规则说明

### 基本规则

| 规则项 | 说明 |
|--------|------|
| 最小交易单位 | 10 股 |
| 手续费率 | 0.1% |
| 最低手续费 | HK$ 5 |
| 单笔最大金额 | HK$ 500,000 |
| 每日最多交易笔数 | 200 笔 |

### 注意事项

1. 买入/卖出数量必须是 10 的整数倍
2. 手续费按成交金额计算，最低收取 HK$ 5
3. 单笔交易金额不超过 HK$ 500,000
4. 具体规则以后台风控配置为准

### 股票代码格式

港股代码格式为 `XXXXX.HK`，例如：
- `00700.HK` - 腾讯控股
- `00388.HK` - 香港交易所
- `00941.HK` - 中国移动
