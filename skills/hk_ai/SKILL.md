---
name: hk-stock-trading
description: 港股模拟炒股大赛交易助手，支持行情查询、K线走势、账户管理、买卖交易和历史记录查询；当用户需要查看港股行情、查看K线、管理模拟账户、执行买卖操作或查询交易记录时使用
---

# 港股模拟炒股大赛交易助手

## 任务目标

- 本 Skill 用于：港股模拟炒股大赛的交易与账户管理
- 能力包含：行情查询、K线走势、账户快照、持仓管理、买卖交易、历史记录查询
- 触发条件：用户提及港股、模拟炒股、查看行情、K线走势、买入卖出、账户查询、持仓、手续费、比赛规则等

## 前置准备

### 凭证配置（必需）

使用本 Skill 前，必须先配置 MCP Token 凭证。Token 是用户的身份验证凭据，每个用户的 Token 不同。

**获取方式**：从港股模拟炒股大赛 MCP 服务提供方获取您的专属 Token

### 依赖说明

脚本使用 requests 库进行 HTTP 请求：
```
requests>=2.28.0
```

## 操作步骤

### 一、行情查询

1. **查看可选股票列表**
   - 调用 `scripts/trading_api.py --action list_stocks` 获取可交易股票及最新行情
   - 返回股票代码、名称、价格、涨跌幅等信息

2. **查询指定股票行情**
   - 调用 `scripts/trading_api.py --action get_quote --symbols "股票代码"`
   - 支持批量查询，多个代码用逗号分隔
   - 示例：`--symbols "00700.HK,00388.HK"`

3. **查询指定股票 K 线走势**
   - 调用 `scripts/trading_api.py --action kline --stock-code 股票代码 --period 1d --limit 60` 获取日K线
   - 或 `--period 1m --limit 120` 获取分钟K线
   - 示例：`--action kline --stock-code 00700.HK --period 1d --limit 60`

4. **查询市场状态**
   - 调用 `scripts/trading_api.py --action market_status` 获取交易时间和数据更新状态

### 二、账户查询

1. **账户快照**
   - 调用 `scripts/trading_api.py --action account` 查看当前余额、总盈亏、可用资金

2. **持仓查询**
   - 调用 `scripts/trading_api.py --action positions` 查看当前持仓及浮动盈亏
   - 或调用 `--action holdings` 查看持股明细及最新价

### 三、交易操作

1. **买入股票**
   - 调用 `scripts/trading_api.py --action buy --stock-code 股票代码 --quantity 数量`
   - 示例：买入 100 股腾讯 `--action buy --stock-code 00700.HK --quantity 100`
   - 注意：数量必须是 10 的整数倍，单笔不超过 HK$ 500,000

2. **卖出股票**
   - 调用 `scripts/trading_api.py --action sell --stock-code 股票代码 --quantity 数量`
   - 需确保持仓中有足够数量

### 四、历史记录

- **交易历史**：`--action orders_history --limit 50`
- **买入记录**：`--action buy_list --page 1 --limit 50`
- **卖出记录**：`--action sell_list --page 1 --limit 50`
- **结算记录**：`--action settlement_list --page 1 --limit 50`
- **余额流水**：`--action balance_log --page 1 --limit 50`
- **手续费记录**：`--action fee_log --page 1 --limit 50`

### 五、规则查询

- 调用 `scripts/trading_api.py --action rules` 获取比赛规则详情

## 资源索引

- 必要脚本：见 [scripts/trading_api.py](scripts/trading_api.py)（用途：封装 MCP API 调用，提供命令行接口）
- API 参考：见 [references/api_reference.md](references/api_reference.md)（何时读取：需要了解详细参数说明和返回格式时）

## 注意事项

- 交易数量必须为 10 的整数倍（最小交易单位）
- 手续费率 0.1%，最低 HK$ 5
- 单笔交易上限 HK$ 500,000
- 每日最多 200 笔交易
- 交易前先查看账户可用资金和当前持仓
- 详细规则以后台风控配置为准，可通过 `--action rules` 查询最新规则

## 权限验证

- **凭证必需**：首次使用需配置 MCP Token，否则所有操作将返回凭证缺失错误
- 配置文件路径: `~/.hkai/config.json`
- Agent 在执行前**必须检查**此文件是否存在：
1. 如果存在，读取并解析 JSON
2. 询问用户是否使用已保存配置
3. 执行完成后保存当前配置到此文件
4. 如果不存在， 则询问用户token，并保持。

**配置文件结构**:
```json
{
  "token": "<具体token值>"
}
```

## 使用示例

**示例 1：查看账户并买入股票**

```bash
# 1. 查看账户可用资金
python trading_api.py --action account

# 2. 查看可选股票
python trading_api.py --action list_stocks

# 3. 查询指定股票行情
python trading_api.py --action get_quote --symbols "00700.HK"

# 4. 可选：查看该股票日K线
python trading_api.py --action kline --stock-code 00700.HK --period 1d --limit 60

# 5. 买入股票
python trading_api.py --action buy --stock-code 00700.HK --quantity 100
```

**示例 4：查看某只股票 K 线走势**

```bash
# 日K线（最近 60 个交易日）
python trading_api.py --action kline --stock-code 00700.HK --period 1d --limit 60

# 分钟K线（最近 120 个交易分钟）
python trading_api.py --action kline --stock-code 00700.HK --period 1m --limit 120
```

**示例 2：查看持仓并卖出**

```bash
# 1. 查看当前持仓
python trading_api.py --action positions

# 2. 卖出股票
python trading_api.py --action sell --stock-code 00700.HK --quantity 100

# 3. 确认卖出结果
python trading_api.py --action sell_list --limit 10
```

**示例 3：查看交易历史**

```bash
# 查看最近交易记录
python trading_api.py --action orders_history --limit 20

# 查看买入历史
python trading_api.py --action buy_list --page 1 --limit 50
```
