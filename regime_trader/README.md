# OKX 均值回归交易系统

自动识别震荡/趋势市场的 OKX 交易模型，震荡市执行均值回归策略。

## 快速开始

### 1. 安装依赖

```bash
pip3 install requests
```

### 2. 配置 Telegram 通知 (可选)

1. 创建 Telegram Bot:
   - 找 @BotFather 发送 `/newbot`
   - 获取 Bot Token

2. 获取 Chat ID:
   - 找 @userinfobot 获取你的 Chat ID

3. 编辑 `config_example.toml`,并改名为config.toml
```toml
[telegram]
bot_token="你的BOT_TOKEN"
chat_id="你的CHAT_ID"
```

### 3. 运行

```bash
cd /Users/chunbohe/projects/code/okx-agent
python3 run_trader.py
```

## 策略说明

### 市场状态识别 (ADX)

| 状态 | 条件 | 行为 |
|------|------|------|
| STRONG_UPTREND | ADX>25, DI+>DI-, EMA20>EMA50 | 趋势市 (Phase 2) |
| STRONG_DOWNTREND | ADX>25, DI->DI+, EMA20<EMA50 | 趋势市 (Phase 2) |
| RANGE_BOUND | ADX≤20 | 均值回归 |
| TRANSITION | 20<ADX≤25 | 停手观望 |

### 均值回归入场条件 (RSI<25)

- ✅ RSI(14) < 25
- ✅ 价格在 BB 中轨以下
- ✅ 价格 > EMA50 (大趋势保护)
- ✅ 有反转信号 (下影线)

### 止盈止损

- 止损: 入场价 - 2×ATR
- TP1: 入场价 + 0.5×ATR (减仓50%)
- TP2: BB 中轨
- TP3: BB 上轨

### 自动停手条件

- 连续亏损 5 笔 → 停手 24 小时
- 周亏损 > 15% → 停手 7 天
- 总亏损 > 30% → 暂停

## 配置参数

编辑 `regime_trader/config.py`:

```python
TOTAL_CAPITAL = 1000.0      # 总资金 USDT
RISK_PER_TRADE = 0.05       # 单笔风险 5%
RSI_OVERSOLD = 25           # 超卖阈值 (保守)
ADX_RANGE_THRESHOLD = 20    # 震荡市阈值
ADX_TRENDING_THRESHOLD = 25 # 趋势市阈值
```

## 文件结构

```
regime_trader/
├── __init__.py
├── main.py              # 主入口
├── config.py            # 参数配置
├── regime_detector.py   # 市场状态识别
├── mean_reversion.py    # 均值回归策略
├── risk_manager.py      # 风险管理
├── trade_executor.py    # OKX 订单执行
├── notifier.py          # Telegram 通知
└── logs/                # 交易日志
```

## 注意事项

1. **Demo 模式**: 默认使用 Demo 账户测试
2. **网络**: 需要能访问 OKX API
3. **风险**: 交易有风险，请谨慎使用
