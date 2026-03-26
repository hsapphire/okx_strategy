"""
Market Regime Detection Module
Detects: TRENDING, RANGE_BOUND, TRANSITION
"""
import json
import requests
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List
from . import config

OKX_BASE_URL = "https://www.okx.com"


class Regime(Enum):
    STRONG_UPTREND = "STRONG_UPTREND"
    STRONG_DOWNTREND = "STRONG_DOWNTREND"
    RANGE_BOUND = "RANGE_BOUND"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeState:
    regime: Regime
    adx: float
    di_plus: float
    di_minus: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_bandwidth: float
    ema_20: float
    ema_50: float
    price: float
    reason: str


def get_proxies() -> dict:
    """获取代理配置"""
    proxies = {}
    if config.HTTP_PROXY:
        proxies['http'] = config.HTTP_PROXY
    if config.HTTPS_PROXY:
        proxies['https'] = config.HTTPS_PROXY
    return proxies


def okx_get(endpoint: str, params: dict = None) -> Optional[dict]:
    """调用 OKX API"""
    try:
        url = f"{OKX_BASE_URL}{endpoint}"
        response = requests.get(url, params=params, proxies=get_proxies(), timeout=30)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"OKX API error: {e}")
        return None


def get_candle_data(instrument: str, bar: str = "1H", limit: int = 100) -> Optional[List]:
    """获取K线数据"""
    result = okx_get("/api/v5/market/candles", {
        "instId": instrument,
        "bar": bar,
        "limit": str(limit)
    })
    if result and result.get("code") == "0":
        return result.get("data", [])
    return None


def get_ticker(instrument: str) -> Optional[dict]:
    """获取最新价格"""
    result = okx_get("/api/v5/market/ticker", {"instId": instrument})
    if result and result.get("code") == "0" and result.get("data"):
        return result["data"][0]
    return None


def calculate_adx(candles: list, period: int = 14) -> tuple:
    """
    从K线数据计算ADX
    OKX返回的数据是倒序的 (最新在前)，需要反转
    
    返回: (adx, di_plus, di_minus)
    """
    if not candles or len(candles) < period + 1:
        return None, None, None

    # OKX candles 格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    # 数据是倒序的 (最新在前)，反转为正序 (最旧在前)
    candles_reversed = list(reversed(candles))
    
    n = min(len(candles_reversed), period + 50)
    highs = [float(c[2]) for c in candles_reversed[:n]]
    lows = [float(c[3]) for c in candles_reversed[:n]]
    closes = [float(c[4]) for c in candles_reversed[:n]]

    # 计算 True Range (TR)
    tr_list = []
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))

    # 计算 Directional Movement (DM)
    plus_dm = []
    minus_dm = []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]

        if up > down and up > 0:
            plus_dm.append(up)
        else:
            plus_dm.append(0)

        if down > up and down > 0:
            minus_dm.append(down)
        else:
            minus_dm.append(0)

    # 使用 Wilder 平滑计算
    def wilder_smooth(data, period):
        if len(data) < period:
            return data[:]
        result = [sum(data[:period]) / period]
        for i in range(period, len(data)):
            result.append((result[-1] * (period - 1) + data[i]) / period)
        return result

    atr = wilder_smooth(tr_list, period)
    plus_di_raw = wilder_smooth(plus_dm, period)
    minus_di_raw = wilder_smooth(minus_dm, period)

    if not atr or len(atr) == 0:
        return None, None, None

    # 计算 DI
    plus_di = [(plus_di_raw[i] / atr[i] * 100) if atr[i] != 0 else 0
               for i in range(len(atr))]
    minus_di = [(minus_di_raw[i] / atr[i] * 100) if atr[i] != 0 else 0
                for i in range(len(atr))]

    # 计算 DX 和 ADX
    dx = []
    for i in range(len(plus_di)):
        sum_di = plus_di[i] + minus_di[i]
        if sum_di != 0:
            dx.append(abs(plus_di[i] - minus_di[i]) / sum_di * 100)
        else:
            dx.append(0)

    adx_values = wilder_smooth(dx, period)

    # 返回最新的值 (最后一个)
    if len(adx_values) > 0:
        return adx_values[-1], plus_di[-1], minus_di[-1]
    return None, None, None


def calculate_bollinger(candles: list, period: int = 20, std_mult: float = 2.0) -> tuple:
    """
    计算布林带
    返回: (upper, middle, lower, bandwidth)
    """
    if not candles or len(candles) < period:
        return None, None, None, None

    closes = [float(c[4]) for c in candles[:period]]

    # 中轨 (SMA)
    middle = sum(closes) / len(closes)

    # 标准差
    variance = sum((c - middle) ** 2 for c in closes) / len(closes)
    std = variance ** 0.5

    upper = middle + std_mult * std
    lower = middle - std_mult * std

    # 带宽
    bandwidth = (upper - lower) / middle if middle != 0 else 0

    return upper, middle, lower, bandwidth


def calculate_ema(closes: list, period: int) -> float:
    """计算 EMA"""
    if len(closes) < period:
        return None

    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period

    for close in closes[period:]:
        ema = (close - ema) * multiplier + ema

    return ema


def detect_regime(instrument: str = "BTC-USDT",
                  bar: str = "1H",
                  adx_period: int = 14,
                  bb_period: int = 20,
                  bb_std: float = 2.0) -> RegimeState:
    """
    检测市场状态

    返回 RegimeState 包含:
    - regime: 市场状态 (STRONG_UPTREND/STRONG_DOWNTREND/RANGE_BOUND/TRANSITION)
    - 各项指标的当前值
    """
    # 获取K线数据
    candles = get_candle_data(instrument, bar, 100)
    if not candles:
        return RegimeState(
            regime=Regime.UNKNOWN,
            adx=0, di_plus=0, di_minus=0,
            bb_upper=0, bb_middle=0, bb_lower=0, bb_bandwidth=0,
            ema_20=0, ema_50=0, price=0,
            reason="无法获取K线数据"
        )

    # 当前价格
    price = float(candles[0][4])  # 最新收盘价

    # 计算 ADX
    adx, di_plus, di_minus = calculate_adx(candles, adx_period)
    if adx is None:
        return RegimeState(
            regime=Regime.UNKNOWN,
            adx=0, di_plus=0, di_minus=0,
            bb_upper=0, bb_middle=0, bb_lower=0, bb_bandwidth=0,
            ema_20=0, ema_50=0, price=price,
            reason="ADX计算失败"
        )

    # 计算布林带
    bb_upper, bb_middle, bb_lower, bb_bandwidth = calculate_bollinger(
        candles, bb_period, bb_std
    )
    if bb_upper is None:
        bb_upper = bb_middle = bb_lower = bb_bandwidth = 0

    # 计算 EMA
    closes = [float(c[4]) for c in candles]
    ema_20 = calculate_ema(closes, 20)
    ema_50 = calculate_ema(closes, 50)

    if ema_20 is None or ema_50 is None:
        ema_20 = ema_50 = 0

    # ═══════════════════════════════════════════════════════════════
    # 市场状态判定逻辑
    # ═══════════════════════════════════════════════════════════════

    # TRANSITION: ADX 在 20-25 之间 (灰色地带)
    if 20 < adx <= 25:
        return RegimeState(
            regime=Regime.TRANSITION,
            adx=adx, di_plus=di_plus, di_minus=di_minus,
            bb_upper=bb_upper, bb_middle=bb_middle,
            bb_lower=bb_lower, bb_bandwidth=bb_bandwidth,
            ema_20=ema_20, ema_50=ema_50, price=price,
            reason=f"ADX={adx:.1f} 在过渡区间 (20-25)"
        )

    # STRONG_UPTREND: ADX > 25, DI+ > DI-, EMA20 > EMA50
    if adx > 25 and di_plus > di_minus and ema_20 > ema_50:
        return RegimeState(
            regime=Regime.STRONG_UPTREND,
            adx=adx, di_plus=di_plus, di_minus=di_minus,
            bb_upper=bb_upper, bb_middle=bb_middle,
            bb_lower=bb_lower, bb_bandwidth=bb_bandwidth,
            ema_20=ema_20, ema_50=ema_50, price=price,
            reason=f"ADX={adx:.1f}>25, DI+>{di_plus:.1f}>DI-{di_minus:.1f}, 多头排列"
        )

    # STRONG_DOWNTREND: ADX > 25, DI- > DI+, EMA20 < EMA50
    if adx > 25 and di_minus > di_plus and ema_20 < ema_50:
        return RegimeState(
            regime=Regime.STRONG_DOWNTREND,
            adx=adx, di_plus=di_plus, di_minus=di_minus,
            bb_upper=bb_upper, bb_middle=bb_middle,
            bb_lower=bb_lower, bb_bandwidth=bb_bandwidth,
            ema_20=ema_20, ema_50=ema_50, price=price,
            reason=f"ADX={adx:.1f}>25, DI-{di_minus:.1f}>DI+{di_plus:.1f}, 空头排列"
        )

    # RANGE_BOUND: ADX ≤ 20
    if adx <= 20:
        return RegimeState(
            regime=Regime.RANGE_BOUND,
            adx=adx, di_plus=di_plus, di_minus=di_minus,
            bb_upper=bb_upper, bb_middle=bb_middle,
            bb_lower=bb_lower, bb_bandwidth=bb_bandwidth,
            ema_20=ema_20, ema_50=ema_50, price=price,
            reason=f"ADX={adx:.1f}≤20, 市场震荡"
        )

    # 默认: TRANSITION
    return RegimeState(
        regime=Regime.TRANSITION,
        adx=adx, di_plus=di_plus, di_minus=di_minus,
        bb_upper=bb_upper, bb_middle=bb_middle,
        bb_lower=bb_lower, bb_bandwidth=bb_bandwidth,
        ema_20=ema_20, ema_50=ema_50, price=price,
        reason=f"未匹配状态，ADX={adx:.1f}"
    )


if __name__ == "__main__":
    # 测试
    state = detect_regime()
    print(f"Regime: {state.regime.value}")
    print(f"ADX: {state.adx:.2f}")
    print(f"DI+: {state.di_plus:.2f}, DI-: {state.di_minus:.2f}")
    print(f"BB: Upper={state.bb_upper:.0f}, Middle={state.bb_middle:.0f}, Lower={state.bb_lower:.0f}")
    print(f"EMA20: {state.ema_20:.0f}, EMA50: {state.ema_50:.0f}")
    print(f"Price: {state.price:.0f}")
    print(f"Reason: {state.reason}")
