"""
Risk Management Module
Position sizing, stop loss, drawdown tracking
"""
import json
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, List
from . import config


@dataclass
class Position:
    instrument: str
    side: str  # "long" or "short"
    entry_price: float
    size: float  # BTC amount
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    entry_time: str
    risk_amount: float  # USDT


@dataclass
class TradeRecord:
    instrument: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_percent: float
    entry_time: str
    exit_time: str
    exit_reason: str
    regime: str


class RiskManager:
    def __init__(self, capital: float = config.TOTAL_CAPITAL):
        self.capital = capital
        self.initial_capital = capital
        self.positions: List[Position] = []
        self.trade_history: List[TradeRecord] = []
        self.consecutive_losses = 0
        self.daily_trades = 0
        self.weekly_trades = 0
        self.last_trade_date = None
        self.last_week_start = None
        self.is_stopped = False
        self.stop_until = None
        self.stop_reason = ""

        # 加载历史记录
        self._load_history()

    def _get_history_path(self) -> str:
        """获取历史记录文件路径"""
        os.makedirs(config.LOG_DIR, exist_ok=True)
        return os.path.join(config.LOG_DIR, config.TRADE_LOG_FILE)

    def _load_history(self):
        """加载交易历史"""
        path = self._get_history_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    self.capital = data.get('capital', self.capital)
                    self.consecutive_losses = data.get('consecutive_losses', 0)
                    self.trade_history = [
                        TradeRecord(**t) for t in data.get('trades', [])
                    ]
            except Exception as e:
                print(f"Error loading history: {e}")

    def _save_history(self):
        """保存交易历史"""
        path = self._get_history_path()
        data = {
            'capital': self.capital,
            'consecutive_losses': self.consecutive_losses,
            'trades': [asdict(t) for t in self.trade_history[-100:]]  # 保留最近100条
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        risk_per_trade: float = config.RISK_PER_TRADE
    ) -> float:
        """
        计算仓位大小

        Returns: BTC数量
        """
        risk_amount = self.capital * risk_per_trade
        stop_distance = abs(entry_price - stop_loss)

        if stop_distance == 0:
            return 0.0

        position_size = risk_amount / stop_distance
        return position_size

    def can_open_position(self) -> tuple:
        """
        检查是否可以开仓

        Returns: (can_open: bool, reason: str)
        """
        # 检查是否被停手
        if self.is_stopped:
            if self.stop_until and datetime.now() < self.stop_until:
                remaining = self.stop_until - datetime.now()
                return False, f"策略已停手: {self.stop_reason}, 剩余 {remaining}"
            else:
                # 停手时间已过，重置
                self.is_stopped = False
                self.stop_until = None
                self.stop_reason = ""

        # 检查最大持仓数
        if len(self.positions) >= config.MAX_POSITIONS:
            return False, f"已达最大持仓数 ({config.MAX_POSITIONS})"

        # 检查每日交易限制
        now = datetime.now()
        if self.last_trade_date and self.last_trade_date.date() == now.date():
            if self.daily_trades >= config.MAX_DAILY_TRADES:
                return False, f"已达每日交易上限 ({config.MAX_DAILY_TRADES})"
        else:
            # 新的一天，重置
            self.daily_trades = 0

        # 检查每周交易限制
        week_start = now - timedelta(days=now.weekday())
        if self.last_week_start and week_start.date() == self.last_week_start.date():
            if self.weekly_trades >= config.MAX_WEEKLY_TRADES:
                return False, f"已达每周交易上限 ({config.MAX_WEEKLY_TRADES})"
        else:
            # 新的一周，重置
            self.weekly_trades = 0
            self.last_week_start = week_start

        return True, "OK"

    def check_auto_stop(self) -> tuple:
        """
        检查自动停手条件

        Returns: (should_stop: bool, reason: str)
        """
        # 连续亏损检查
        if self.consecutive_losses >= config.CONSECUTIVE_LOSS_STOP:
            self.is_stopped = True
            self.stop_until = datetime.now() + timedelta(
                hours=config.CONSECUTIVE_LOSS_STOP_HOURS
            )
            self.stop_reason = f"连续亏损 {self.consecutive_losses} 笔"
            return True, self.stop_reason

        # 周回撤检查
        weekly_pnl = self._calculate_weekly_pnl()
        if weekly_pnl < -config.get_max_weekly_loss():
            self.is_stopped = True
            self.stop_until = datetime.now() + timedelta(days=7)
            self.stop_reason = f"周亏损 {abs(weekly_pnl):.2f} USDT 超过限制"
            return True, self.stop_reason

        # 总回撤检查
        total_loss = self.initial_capital - self.capital
        if total_loss >= config.get_max_total_loss():
            self.is_stopped = True
            self.stop_reason = f"总亏损 {total_loss:.2f} USDT 超过限制"
            return True, self.stop_reason

        # 连续亏损预警
        if self.consecutive_losses >= config.CONSECUTIVE_LOSS_WARNING:
            return False, f"⚠️ 连续亏损 {self.consecutive_losses} 笔，注意风险"

        return False, ""

    def open_position(
        self,
        instrument: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        tp1: float,
        tp2: float,
        tp3: float,
        regime: str
    ) -> Optional[Position]:
        """记录开仓"""
        can_open, reason = self.can_open_position()
        if not can_open:
            print(f"Cannot open position: {reason}")
            return None

        position_size = self.calculate_position_size(entry_price, stop_loss)
        risk_amount = position_size * abs(entry_price - stop_loss)

        position = Position(
            instrument=instrument,
            side=side,
            entry_price=entry_price,
            size=position_size,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            entry_time=datetime.now().isoformat(),
            risk_amount=risk_amount
        )

        self.positions.append(position)
        self.daily_trades += 1
        self.weekly_trades += 1
        self.last_trade_date = datetime.now()

        print(f"Position opened: {side} {position_size:.6f} BTC @ {entry_price}")
        return position

    def close_position(
        self,
        position: Position,
        exit_price: float,
        exit_reason: str,
        regime: str
    ) -> TradeRecord:
        """记录平仓"""
        # 计算盈亏
        if position.side == "long":
            pnl = (exit_price - position.entry_price) * position.size
        else:
            pnl = (position.entry_price - exit_price) * position.size

        pnl_percent = (pnl / self.capital) * 100

        # 更新资金
        self.capital += pnl

        # 更新连续亏损计数
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # 创建交易记录
        record = TradeRecord(
            instrument=position.instrument,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            size=position.size,
            pnl=pnl,
            pnl_percent=pnl_percent,
            entry_time=position.entry_time,
            exit_time=datetime.now().isoformat(),
            exit_reason=exit_reason,
            regime=regime
        )

        self.trade_history.append(record)
        self.positions.remove(position)

        # 保存历史
        self._save_history()

        # 检查自动停手
        self.check_auto_stop()

        print(f"Position closed: {pnl:.2f} USDT ({pnl_percent:.2f}%)")
        return record

    def _calculate_weekly_pnl(self) -> float:
        """计算本周总盈亏"""
        week_start = datetime.now() - timedelta(days=datetime.now().weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0)

        weekly_pnl = 0
        for trade in self.trade_history:
            try:
                exit_time = datetime.fromisoformat(trade.exit_time)
                if exit_time >= week_start:
                    weekly_pnl += trade.pnl
            except:
                pass

        return weekly_pnl

    def get_status(self) -> dict:
        """获取当前状态"""
        weekly_pnl = self._calculate_weekly_pnl()
        total_pnl = self.capital - self.initial_capital

        return {
            'capital': self.capital,
            'total_pnl': total_pnl,
            'total_pnl_percent': (total_pnl / self.initial_capital) * 100,
            'weekly_pnl': weekly_pnl,
            'consecutive_losses': self.consecutive_losses,
            'open_positions': len(self.positions),
            'daily_trades': self.daily_trades,
            'weekly_trades': self.weekly_trades,
            'is_stopped': self.is_stopped,
            'stop_reason': self.stop_reason,
        }

    def get_position_by_instrument(self, instrument: str) -> Optional[Position]:
        """获取指定交易对的持仓"""
        for pos in self.positions:
            if pos.instrument == instrument:
                return pos
        return None
