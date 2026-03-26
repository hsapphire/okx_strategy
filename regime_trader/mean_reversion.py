"""
Mean Reversion Strategy Module
Active when market is in RANGE_BOUND regime (ADX ≤ 20)
"""
import subprocess
import re
import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List
from .regime_detector import RegimeState, Regime, get_candle_data, calculate_ema


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"


@dataclass
class TradeSignal:
    signal: Signal
    price: float
    rsi: float
    bb_position: float  # 价格在BB中的位置 (0=下轨, 1=上轨)
    reason: str
    stop_loss: float
    tp1: float  # RSI回到50
    tp2: float  # BB中轨
    tp3: float  # BB上轨


def calculate_rsi(candles: list, period: int = 14) -> float:
    """计算 RSI"""
    if len(candles) < period + 1:
        return 50.0

    # OKX返回倒序数据 (最新在前)，反转为正序
    candles_reversed = list(reversed(candles))
    closes = [float(c[4]) for c in candles_reversed[:period + 20]]

    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    if len(gains) < period:
        return 50.0

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_atr(candles: list, period: int = 14) -> float:
    """计算 ATR"""
    if len(candles) < period + 1:
        return 0.0

    # OKX返回倒序数据 (最新在前)，反转为正序
    candles_reversed = list(reversed(candles))
    
    tr_list = []
    for i in range(1, min(len(candles_reversed), period + 10)):
        high = float(candles_reversed[i][2])
        low = float(candles_reversed[i][3])
        prev_close = float(candles_reversed[i - 1][4])

        hl = high - low
        hc = abs(high - prev_close)
        lc = abs(low - prev_close)
        tr_list.append(max(hl, hc, lc))

    if not tr_list:
        return 0.0

    # 简单移动平均
    atr = sum(tr_list[:period]) / min(len(tr_list), period)
    return atr


def calculate_bb_position(price: float, bb_lower: float,
                          bb_middle: float, bb_upper: float) -> float:
    """计算价格在布林带中的位置 (0-1)"""
    if bb_upper == bb_lower:
        return 0.5
    position = (price - bb_lower) / (bb_upper - bb_lower)
    return max(0.0, min(1.0, position))


def calculate_bollinger(candles: list, period: int = 20,
                        std_mult: float = 2.0) -> tuple:
    """计算布林带"""
    if not candles or len(candles) < period:
        return None, None, None

    closes = [float(c[4]) for c in candles[:period]]
    middle = sum(closes) / len(closes)
    variance = sum((c - middle) ** 2 for c in closes) / len(closes)
    std = variance ** 0.5

    upper = middle + std_mult * std
    lower = middle - std_mult * std

    return upper, middle, lower


def check_mean_reversion_signal(
    regime_state: RegimeState,
    instrument: str = "BTC-USDT",
    rsi_period: int = 14,
    rsi_oversold: float = 25,
    rsi_overbought: float = 75,
    bb_period: int = 20,
    bb_std: float = 2.0,
    sl_atr_mult: float = 2.0
) -> TradeSignal:
    """
    检查均值回归信号

    仅在 RANGE_BOUND 市场状态下生成信号
    """
    # 获取K线数据
    candles = get_candle_data(instrument, "1H", 100)
    if not candles or len(candles) < 50:
        return TradeSignal(
            signal=Signal.HOLD,
            price=regime_state.price,
            rsi=50, bb_position=0.5,
            reason="数据不足",
            stop_loss=0, tp1=0, tp2=0, tp3=0
        )

    # 计算指标
    rsi = calculate_rsi(candles, rsi_period)
    atr = calculate_atr(candles, 14)
    bb_upper, bb_middle, bb_lower = calculate_bollinger(candles, bb_period, bb_std)
    closes = [float(c[4]) for c in candles]
    ema_50 = calculate_ema(closes, 50) or 0

    price = regime_state.price
    bb_position = calculate_bb_position(price, bb_lower, bb_middle, bb_upper)

    # ═══════════════════════════════════════════════════════════════
    # 做多信号 (Buy Signal)
    # ═══════════════════════════════════════════════════════════════
    if rsi < rsi_oversold:
        # 检查是否触及或接近BB下轨
        if price <= bb_middle:  # 价格在中轨以下
            # 检查大趋势 (EMA50 过滤)
            if price > ema_50 * 0.98:  # 允许2%的容差
                # 检查反转信号 (前一根阴线，当前有下影线)
                prev_candle = candles[1]
                curr_candle = candles[0]

                prev_open = float(prev_candle[1])
                prev_close = float(prev_candle[4])
                curr_open = float(curr_candle[1])
                curr_close = float(curr_candle[4])
                curr_low = float(curr_candle[3])

                prev_is_bearish = prev_close < prev_open
                curr_has_lower_wick = curr_low < min(curr_open, curr_close)

                if prev_is_bearish or curr_has_lower_wick:
                    # 计算止盈止损
                    stop_loss = price - sl_atr_mult * atr
                    tp1 = price + 0.5 * atr  # RSI回到50
                    tp2 = bb_middle  # BB中轨
                    tp3 = bb_upper  # BB上轨

                    return TradeSignal(
                        signal=Signal.BUY,
                        price=price,
                        rsi=rsi,
                        bb_position=bb_position,
                        reason=f"RSI={rsi:.1f}<{rsi_oversold}, 价格触及BB下半区, 反转信号确认",
                        stop_loss=stop_loss,
                        tp1=tp1,
                        tp2=tp2,
                        tp3=tp3
                    )

    # ═══════════════════════════════════════════════════════════════
    # 做空信号 (Sell Signal) - 简化版，主要用于平多仓
    # ═══════════════════════════════════════════════════════════════
    if rsi > rsi_overbought and price >= bb_middle:
        return TradeSignal(
            signal=Signal.SELL,
            price=price,
            rsi=rsi,
            bb_position=bb_position,
            reason=f"RSI={rsi:.1f}>{rsi_overbought}, 价格在BB上半区",
            stop_loss=price + sl_atr_mult * atr,
            tp1=price - 0.5 * atr,
            tp2=bb_middle,
            tp3=bb_lower
        )

    return TradeSignal(
        signal=Signal.HOLD,
        price=price,
        rsi=rsi,
        bb_position=bb_position,
        reason=f"无信号 (RSI={rsi:.1f}, BB位置={bb_position:.2f})",
        stop_loss=0, tp1=0, tp2=0, tp3=0
    )


def check_exit_signal(
    entry_price: float,
    position_side: str,  # "long" or "short"
    current_rsi: float,
    current_price: float,
    bb_middle: float,
    rsi_exit: float = 50,
    rsi_overbought: float = 75,
    rsi_oversold: float = 25
) -> Signal:
    """
    检查出场信号

    Returns: Signal.EXIT if should exit, Signal.HOLD otherwise
    """
    if position_side == "long":
        # RSI 回到中性区域
        if current_rsi >= rsi_exit:
            return Signal.EXIT
        # 价格触及BB中轨
        if current_price >= bb_middle:
            return Signal.EXIT
        # RSI 超买
        if current_rsi >= rsi_overbought:
            return Signal.EXIT

    elif position_side == "short":
        # RSI 回到中性区域
        if current_rsi <= rsi_exit:
            return Signal.EXIT
        # 价格触及BB中轨
        if current_price <= bb_middle:
            return Signal.EXIT
        # RSI 超卖
        if current_rsi <= rsi_oversold:
            return Signal.EXIT

    return Signal.HOLD
