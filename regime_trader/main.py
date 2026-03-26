#!/usr/bin/env python3
"""
OKX Regime-Aware Trading System - Main Entry Point
Mean Reversion Strategy for Range-Bound Markets
"""
import time
import signal
import sys
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta
from typing import Optional

from . import config
from .regime_detector import detect_regime, Regime, RegimeState
from .mean_reversion import (
    check_mean_reversion_signal,
    check_exit_signal,
    calculate_rsi,
    calculate_bollinger,
    Signal,
    TradeSignal
)
from .risk_manager import RiskManager, Position
from .trade_executor import (
    execute_entry,
    execute_exit,
    get_open_orders,
    cancel_order
)
from .notifier import notifier


def setup_logger() -> logging.Logger:
    """配置日志系统"""
    # 创建日志目录
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config.LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)

    # 创建 logger
    logger = logging.getLogger('regime_trader')
    logger.setLevel(logging.DEBUG)

    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 文件处理器 - 按天轮转，保留30天
    log_file = os.path.join(log_dir, 'trader.log')
    file_handler = TimedRotatingFileHandler(
        log_file,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.suffix = '%Y%m%d'

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


class RegimeTrader:
    def __init__(self):
        self.logger = setup_logger()
        self.risk_manager = RiskManager()
        self.running = True
        self.current_regime: Optional[RegimeState] = None
        self.last_regime: Optional[Regime] = None
        self.cycle_count = 0
        self.start_time = datetime.now()

        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """优雅退出"""
        self.logger.info("收到退出信号，正在停止...")
        self.running = False

    def _log(self, message: str, level: str = "INFO"):
        """日志输出"""
        if level == "DEBUG":
            self.logger.debug(message)
        elif level == "WARNING":
            self.logger.warning(message)
        elif level == "ERROR":
            self.logger.error(message)
        else:
            self.logger.info(message)

    def _check_regime_change(self, new_state: RegimeState) -> bool:
        """检查市场状态是否变化"""
        if self.last_regime is None or self.last_regime != new_state.regime:
            old_regime = self.last_regime.value if self.last_regime else "UNKNOWN"
            new_regime = new_state.regime.value

            self.logger.warning(f"市场状态变化: {old_regime} → {new_regime}")
            self.logger.info(f"变化原因: {new_state.reason}")

            # 发送通知
            notifier.send_regime_change(
                instrument=config.INSTRUMENT,
                old_regime=old_regime,
                new_regime=new_regime,
                adx=new_state.adx,
                reason=new_state.reason
            )

            # 状态变化时检查是否需要平仓
            if self.last_regime == Regime.RANGE_BOUND and new_state.regime != Regime.RANGE_BOUND:
                # 从震荡市变成其他状态，平掉均值回归仓位
                self._close_regime_positions("市场状态变化")

            self.last_regime = new_state.regime
            return True
        return False

    def _close_regime_positions(self, reason: str):
        """平掉所有持仓"""
        position = self.risk_manager.get_position_by_instrument(config.INSTRUMENT)
        if position:
            self._log(f"平仓: {reason}")

            # 市价平仓
            result = execute_exit(
                config.INSTRUMENT,
                position.side,
                position.size
            )

            if result.success:
                # 获取当前价格 (简化处理)
                exit_price = position.entry_price  # 实际应该获取最新价格

                # 记录平仓
                trade = self.risk_manager.close_position(
                    position,
                    exit_price,
                    reason,
                    self.current_regime.regime.value if self.current_regime else "UNKNOWN"
                )

                notifier.send_exit_signal(
                    instrument=config.INSTRUMENT,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    size=position.size,
                    pnl=trade.pnl,
                    pnl_percent=trade.pnl_percent,
                    duration="手动平仓",
                    exit_reason=reason,
                    regime=self.current_regime.regime.value if self.current_regime else "UNKNOWN"
                )

    def _check_positions(self):
        """检查持仓状态，管理止盈止损"""
        position = self.risk_manager.get_position_by_instrument(config.INSTRUMENT)
        if not position:
            return

        # 获取当前市场数据
        from .mean_reversion import get_candle_data, calculate_rsi

        candles = get_candle_data(config.INSTRUMENT, "1H", 50)
        if not candles:
            return

        current_price = float(candles[0][4])
        current_rsi = calculate_rsi(candles, config.RSI_PERIOD)

        # 检查止损
        if position.side == "long" and current_price <= position.stop_loss:
            self._execute_stop_loss(position, current_price, "触发止损")
            return

        if position.side == "short" and current_price >= position.stop_loss:
            self._execute_stop_loss(position, current_price, "触发止损")
            return

        # 检查止盈
        if position.side == "long" and current_price >= position.tp1:
            self._execute_take_profit(position, current_price, "触发TP1 (BB中轨)")
            return

        # 检查RSI出场
        exit_signal = check_exit_signal(
            entry_price=position.entry_price,
            position_side=position.side,
            current_rsi=current_rsi,
            current_price=current_price,
            bb_middle=self.current_regime.bb_middle if self.current_regime else 0,
            rsi_exit=config.RSI_EXIT,
            rsi_overbought=config.RSI_OVERBOUGHT,
            rsi_oversold=config.RSI_OVERSOLD
        )

        if exit_signal == Signal.EXIT:
            self._execute_take_profit(position, current_price, f"RSI信号出场 (RSI={current_rsi:.1f})")

    def _execute_stop_loss(self, position: Position, price: float, reason: str):
        """执行止损"""
        self._log(f"止损: {reason}")

        result = execute_exit(config.INSTRUMENT, position.side, position.size)
        if result.success:
            trade = self.risk_manager.close_position(
                position, price, reason,
                self.current_regime.regime.value if self.current_regime else "UNKNOWN"
            )

            notifier.send_exit_signal(
                instrument=config.INSTRUMENT,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=price,
                size=position.size,
                pnl=trade.pnl,
                pnl_percent=trade.pnl_percent,
                duration="N/A",
                exit_reason=reason,
                regime=self.current_regime.regime.value if self.current_regime else "UNKNOWN"
            )

    def _execute_take_profit(self, position: Position, price: float, reason: str):
        """执行止盈"""
        self._log(f"止盈: {reason}")

        result = execute_exit(config.INSTRUMENT, position.side, position.size)
        if result.success:
            trade = self.risk_manager.close_position(
                position, price, reason,
                self.current_regime.regime.value if self.current_regime else "UNKNOWN"
            )

            notifier.send_exit_signal(
                instrument=config.INSTRUMENT,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=price,
                size=position.size,
                pnl=trade.pnl,
                pnl_percent=trade.pnl_percent,
                duration="N/A",
                exit_reason=reason,
                regime=self.current_regime.regime.value if self.current_regime else "UNKNOWN"
            )

    def _execute_entry(self, signal: TradeSignal):
        """执行入场"""
        # 检查是否可以开仓
        can_open, reason = self.risk_manager.can_open_position()
        if not can_open:
            self._log(f"无法开仓: {reason}")
            return

        # 计算仓位大小
        size = self.risk_manager.calculate_position_size(
            signal.price,
            signal.stop_loss
        )

        if size <= 0:
            self._log("仓位大小为0，跳过")
            return

        side = "buy" if signal.signal == Signal.BUY else "sell"

        self._log(f"执行入场: {side} {size:.6f} BTC @ ${signal.price:,.0f}")

        # 下单
        result = execute_entry(
            instrument=config.INSTRUMENT,
            side=side,
            price=signal.price,
            size=size,
            stop_loss=signal.stop_loss,
            tp1=signal.tp1
        )

        if result.success:
            # 记录仓位
            position = self.risk_manager.open_position(
                instrument=config.INSTRUMENT,
                side="long" if side == "buy" else "short",
                entry_price=signal.price,
                stop_loss=signal.stop_loss,
                tp1=signal.tp1,
                tp2=signal.tp2,
                tp3=signal.tp3,
                regime=self.current_regime.regime.value if self.current_regime else "UNKNOWN"
            )

            if position:
                notifier.send_entry_signal(
                    instrument=config.INSTRUMENT,
                    side=side,
                    price=signal.price,
                    size=size,
                    stop_loss=signal.stop_loss,
                    tp1=signal.tp1,
                    regime=self.current_regime.regime.value if self.current_regime else "UNKNOWN",
                    rsi=signal.rsi,
                    adx=self.current_regime.adx if self.current_regime else 0,
                    reason=signal.reason
                )
        else:
            self._log(f"下单失败: {result.message}")

    def _check_auto_stop(self):
        """检查自动停手条件"""
        should_stop, reason = self.risk_manager.check_auto_stop()
        if should_stop:
            self._log(f"自动停手: {reason}")

            # 平掉所有仓位
            self._close_regime_positions(f"自动停手: {reason}")

            # 发送通知
            status = self.risk_manager.get_status()
            notifier.send_auto_stop(
                reason=reason,
                consecutive_losses=status['consecutive_losses'],
                weekly_pnl=status['weekly_pnl'],
                total_pnl=status['total_pnl'],
                resume_time=(datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
            )

        # 检查预警
        if self.risk_manager.consecutive_losses >= config.CONSECUTIVE_LOSS_WARNING:
            notifier.send_warning(
                f"连续亏损 {self.risk_manager.consecutive_losses} 笔，请注意风险"
            )

    def run_cycle(self):
        """执行一次检测循环"""
        self.cycle_count += 1
        self.logger.info("=" * 60)
        self.logger.info(f"检测周期 #{self.cycle_count}")

        # 1. 检查自动停手
        self._check_auto_stop()

        if self.risk_manager.is_stopped:
            self.logger.warning(f"策略已停手: {self.risk_manager.stop_reason}")
            return

        # 2. 检测市场状态
        self.current_regime = detect_regime(
            instrument=config.INSTRUMENT,
            bar=config.INDICATOR_BAR,
            adx_period=config.ADX_PERIOD,
            bb_period=config.BB_PERIOD,
            bb_std=config.BB_STD
        )

        self.logger.info(f"市场状态: {self.current_regime.regime.value}")
        self.logger.info(f"ADX: {self.current_regime.adx:.1f} | DI+: {self.current_regime.di_plus:.1f} | DI-: {self.current_regime.di_minus:.1f}")
        self.logger.info(f"价格: ${self.current_regime.price:,.0f} | BB中轨: ${self.current_regime.bb_middle:,.0f} | BB下轨: ${self.current_regime.bb_lower:,.0f}")
        self.logger.info(f"EMA20: ${self.current_regime.ema_20:,.0f} | EMA50: ${self.current_regime.ema_50:,.0f}")

        # 3. 检查状态变化
        self._check_regime_change(self.current_regime)

        # 4. 管理现有仓位
        self._check_positions()

        # 5. 震荡市才执行均值回归
        if self.current_regime.regime == Regime.RANGE_BOUND:
            # 检查均值回归信号
            signal = check_mean_reversion_signal(
                regime_state=self.current_regime,
                instrument=config.INSTRUMENT,
                rsi_period=config.RSI_PERIOD,
                rsi_oversold=config.RSI_OVERSOLD,
                rsi_overbought=config.RSI_OVERBOUGHT,
                bb_period=config.BB_PERIOD,
                bb_std=config.BB_STD,
                sl_atr_mult=config.SL_ATR_MULTIPLIER
            )

            self.logger.info(f"RSI: {signal.rsi:.1f} | BB位置: {signal.bb_position:.2f}")
            self.logger.info(f"交易信号: {signal.signal.value} | 原因: {signal.reason}")

            # 执行交易
            if signal.signal in [Signal.BUY, Signal.SELL]:
                self.logger.warning(f"触发交易信号: {signal.signal.value}")
                self._execute_entry(signal)

        elif self.current_regime.regime == Regime.TRANSITION:
            self.logger.info("过渡期，不交易")

        else:
            self.logger.info("趋势市，均值回归策略不适用")

        # 6. 输出状态
        status = self.risk_manager.get_status()
        self.logger.info(f"账户状态: 资金=${status['capital']:,.2f} | 持仓={status['open_positions']} | 本周盈亏=${status['weekly_pnl']:+.2f}")

    def run(self):
        """主运行循环"""
        self.logger.info("=" * 60)
        self.logger.info("OKX 均值回归交易系统启动")
        self.logger.info(f"交易对: {config.INSTRUMENT}")
        self.logger.info(f"资金: ${config.TOTAL_CAPITAL}")
        self.logger.info(f"单笔风险: {config.RISK_PER_TRADE * 100}%")
        self.logger.info(f"检测间隔: {config.CHECK_INTERVAL}秒 ({config.CHECK_INTERVAL // 60}分钟)")
        self.logger.info(f"RSI超卖阈值: {config.RSI_OVERSOLD}")
        self.logger.info(f"Demo模式: {config.DEMO_MODE}")
        self.logger.info("=" * 60)

        # 发送启动通知
        notifier.send_heartbeat(self.risk_manager.get_status())

        while self.running:
            try:
                self.run_cycle()

                # 每小时发送一次心跳 (12个周期)
                if self.cycle_count > 0 and self.cycle_count % 12 == 0:
                    notifier.send_heartbeat(self.risk_manager.get_status())

            except KeyboardInterrupt:
                self.logger.info("收到键盘中断")
                break
            except Exception as e:
                self.logger.error(f"异常: {e}", exc_info=True)
                notifier.send_error(str(e))

            # 等待下一次检测 (5分钟)
            if self.running:
                next_check = datetime.now() + timedelta(seconds=config.CHECK_INTERVAL)
                self.logger.info(f"下次检测: {next_check.strftime('%H:%M:%S')}")
                self.logger.info("-" * 40)
                time.sleep(config.CHECK_INTERVAL)

        # 退出前发送总结
        status = self.risk_manager.get_status()
        notifier.send_daily_summary(
            capital=status['capital'],
            total_pnl=status['total_pnl'],
            total_trades=len(self.risk_manager.trade_history),
            win_rate=self._calculate_win_rate(),
            consecutive_losses=status['consecutive_losses'],
            positions=status['open_positions']
        )

        self.logger.info("=" * 60)
        self.logger.info(f"系统已停止 | 运行周期: {self.cycle_count}")

    def _calculate_win_rate(self) -> float:
        """计算胜率"""
        trades = self.risk_manager.trade_history
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.pnl > 0)
        return (wins / len(trades)) * 100


def main():
    """入口函数"""
    trader = RegimeTrader()
    trader.run()


if __name__ == "__main__":
    main()
