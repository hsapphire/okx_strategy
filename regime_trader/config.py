"""
Configuration for OKX Regime-Aware Trading System
All quantifiable parameters in one place
"""

# ═══════════════════════════════════════════════════════════════
# Trading Configuration
# ═══════════════════════════════════════════════════════════════
INSTRUMENT = "BTC-USDT"
TIMEFRAME = "1H"  # K线周期
CANDLE_INTERVAL = "1H"  # 用于获取K线数据
INDICATOR_BAR = "1H"  # 用于指标计算
TOTAL_CAPITAL = 1000.0  # USDT
DEMO_MODE = True  # 使用 Demo 账户
CHECK_INTERVAL = 300  # 5分钟检测一次 (秒)

# ═══════════════════════════════════════════════════════════════
# Risk Management
# ═══════════════════════════════════════════════════════════════
RISK_PER_TRADE = 0.05  # 单笔风险 5%
SL_ATR_MULTIPLIER = 2.0  # 止损 = 2 × ATR
MAX_POSITIONS = 2  # 最大同时持仓数
MAX_DAILY_TRADES = 3  # 每日最大交易数
MAX_WEEKLY_TRADES = 10  # 每周最大交易数

# ═══════════════════════════════════════════════════════════════
# Auto-Stop Conditions
# ═══════════════════════════════════════════════════════════════
CONSECUTIVE_LOSS_WARNING = 3  # 连续亏损预警
CONSECUTIVE_LOSS_STOP = 5  # 连续亏损停手
CONSECUTIVE_LOSS_STOP_HOURS = 24  # 停手时长
WEEKLY_DRAWDOWN_LIMIT = 0.15  # 周回撤限制 15%
TOTAL_DRAWDOWN_LIMIT = 0.30  # 总回撤限制 30%

# ═══════════════════════════════════════════════════════════════
# Regime Detection Parameters
# ═══════════════════════════════════════════════════════════════
ADX_PERIOD = 14  # ADX计算周期
ADX_TRENDING_THRESHOLD = 25  # 趋势市阈值
ADX_RANGE_THRESHOLD = 20  # 震荡市阈值
ADX_CONFIRMATION_BARS = 2  # 状态切换确认K线数
BB_PERIOD = 20  # 布林带周期
BB_STD = 2.0  # 布林带标准差倍数
BB_BANDWIDTH_LOOKBACK = 20  # 带宽历史比较周期

# ═══════════════════════════════════════════════════════════════
# Mean Reversion Parameters
# ═══════════════════════════════════════════════════════════════
RSI_PERIOD = 14
RSI_OVERSOLD = 25  # 超卖阈值 (保守模式)
RSI_OVERBOUGHT = 75  # 超买阈值
RSI_EXIT = 50  # RSI出场阈值
EMA_SLOW = 50  # 用于趋势过滤

# ═══════════════════════════════════════════════════════════════
# Telegram Configuration
# ═══════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = ""  # 从环境变量或配置文件读取
TELEGRAM_CHAT_ID = ""  # 从环境变量或配置文件读取

# ═══════════════════════════════════════════════════════════════
# Proxy Configuration
# ═══════════════════════════════════════════════════════════════
HTTP_PROXY = "http://127.0.0.1:42001"
HTTPS_PROXY = "http://127.0.0.1:42001"

# ═══════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════
LOG_DIR = "logs"
TRADE_LOG_FILE = "trades.json"


def get_proxy_env():
    """获取代理环境变量，用于 subprocess"""
    import os
    env = os.environ.copy()
    if HTTP_PROXY:
        env['http_proxy'] = HTTP_PROXY
        env['HTTP_PROXY'] = HTTP_PROXY
    if HTTPS_PROXY:
        env['https_proxy'] = HTTPS_PROXY
        env['HTTPS_PROXY'] = HTTPS_PROXY
    return env

# ═══════════════════════════════════════════════════════════════
# Derived Calculations
# ═══════════════════════════════════════════════════════════════
def get_risk_amount():
    """计算单笔最大风险金额"""
    return TOTAL_CAPITAL * RISK_PER_TRADE

def get_max_weekly_loss():
    """计算每周最大亏损金额"""
    return TOTAL_CAPITAL * WEEKLY_DRAWDOWN_LIMIT

def get_max_total_loss():
    """计算总最大亏损金额"""
    return TOTAL_CAPITAL * TOTAL_DRAWDOWN_LIMIT
