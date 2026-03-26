"""
Telegram Notification Module
Sends trading alerts and status updates
"""
import os
import requests
from typing import Optional
from datetime import datetime
from . import config


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str = None,
        chat_id: str = None
    ):
        self.bot_token = bot_token or os.getenv(
            'TELEGRAM_BOT_TOKEN',
            config.TELEGRAM_BOT_TOKEN
        )
        self.chat_id = chat_id or os.getenv(
            'TELEGRAM_CHAT_ID',
            config.TELEGRAM_CHAT_ID
        )
        self.enabled = bool(self.bot_token and self.chat_id)

    def _send_message(self, text: str) -> bool:
        """发送消息到 Telegram"""
        if not self.enabled:
            print(f"[Telegram Disabled] {text}")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }

        # 获取代理配置
        proxies = self._get_proxies()

        try:
            response = requests.post(url, json=payload, timeout=10, proxies=proxies)
            return response.status_code == 200
        except Exception as e:
            print(f"Telegram send error: {e}")
            return False

    def _get_proxies(self) -> dict:
        """获取代理配置"""
        from . import config
        proxies = {}
        if config.HTTP_PROXY:
            proxies['http'] = config.HTTP_PROXY
        if config.HTTPS_PROXY:
            proxies['https'] = config.HTTPS_PROXY
        return proxies

    def send_regime_change(
        self,
        instrument: str,
        old_regime: str,
        new_regime: str,
        adx: float,
        reason: str
    ):
        """发送市场状态变化通知"""
        emoji = "🔄"
        text = (
            f"{emoji} <b>市场状态变化</b>\n"
            f"────────────────────\n"
            f"<b>{instrument}</b> 1H\n"
            f"\n"
            f"状态: {old_regime} → <b>{new_regime}</b>\n"
            f"ADX: {adx:.1f}\n"
            f"\n"
            f"📌 {reason}"
        )
        self._send_message(text)

    def send_entry_signal(
        self,
        instrument: str,
        side: str,
        price: float,
        size: float,
        stop_loss: float,
        tp1: float,
        regime: str,
        rsi: float,
        adx: float,
        reason: str
    ):
        """发送开仓信号通知"""
        emoji = "🟢" if side == "buy" else "🔴"
        side_text = "做多" if side == "buy" else "做空"

        usdt_value = price * size

        text = (
            f"{emoji} <b>均值回归开仓</b>\n"
            f"────────────────────\n"
            f"<b>{instrument}</b> @ ${price:,.0f}\n"
            f"\n"
            f"方向: {side_text}\n"
            f"数量: {size:.6f} BTC (${usdt_value:.0f})\n"
            f"止损: ${stop_loss:,.0f} ({((stop_loss/price-1)*100):.2f}%)\n"
            f"TP1: ${tp1:,.0f}\n"
            f"\n"
            f"市场状态: {regime}\n"
            f"RSI: {rsi:.1f} | ADX: {adx:.1f}\n"
            f"\n"
            f"📌 {reason}"
        )
        self._send_message(text)

    def send_exit_signal(
        self,
        instrument: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
        pnl: float,
        pnl_percent: float,
        duration: str,
        exit_reason: str,
        regime: str
    ):
        """发送平仓信号通知"""
        if pnl >= 0:
            emoji = "✅"
            result_text = "止盈"
        else:
            emoji = "❌"
            result_text = "止损"

        side_text = "多仓" if side == "long" else "空仓"

        text = (
            f"{emoji} <b>均值回归{result_text}</b>\n"
            f"────────────────────\n"
            f"<b>{instrument}</b>\n"
            f"\n"
            f"持仓: {side_text}\n"
            f"入场: ${entry_price:,.0f} → 出场: ${exit_price:,.0f}\n"
            f"数量: {size:.6f} BTC\n"
            f"\n"
            f"盈亏: ${pnl:+.2f} ({pnl_percent:+.2f}%)\n"
            f"持仓时间: {duration}\n"
            f"\n"
            f"平仓原因: {exit_reason}\n"
            f"市场状态: {regime}"
        )
        self._send_message(text)

    def send_auto_stop(
        self,
        reason: str,
        consecutive_losses: int,
        weekly_pnl: float,
        total_pnl: float,
        resume_time: str = None
    ):
        """发送自动停手通知"""
        text = (
            f"🛑 <b>策略自动停手</b>\n"
            f"────────────────────\n"
            f"原因: {reason}\n"
            f"\n"
            f"已停止开新仓\n"
        )

        if resume_time:
            text += f"恢复时间: {resume_time}\n"

        text += (
            f"\n"
            f"连续亏损: {consecutive_losses} 笔\n"
            f"本周盈亏: ${weekly_pnl:+.2f}\n"
            f"总盈亏: ${total_pnl:+.2f}"
        )
        self._send_message(text)

    def send_warning(self, message: str):
        """发送预警通知"""
        text = (
            f"⚠️ <b>风险预警</b>\n"
            f"────────────────────\n"
            f"{message}"
        )
        self._send_message(text)

    def send_daily_summary(
        self,
        capital: float,
        total_pnl: float,
        total_trades: int,
        win_rate: float,
        consecutive_losses: int,
        positions: int
    ):
        """发送每日总结"""
        text = (
            f"📊 <b>每日交易总结</b>\n"
            f"────────────────────\n"
            f"日期: {datetime.now().strftime('%Y-%m-%d')}\n"
            f"\n"
            f"当前资金: ${capital:,.2f}\n"
            f"总盈亏: ${total_pnl:+.2f}\n"
            f"今日交易: {total_trades} 笔\n"
            f"胜率: {win_rate:.1f}%\n"
            f"连续亏损: {consecutive_losses}\n"
            f"持仓中: {positions} 个"
        )
        self._send_message(text)

    def send_heartbeat(self, status: dict):
        """发送心跳消息"""
        emoji = "💚" if not status.get('is_stopped') else "❤️"
        text = (
            f"{emoji} <b>系统运行中</b>\n"
            f"────────────────────\n"
            f"时间: {datetime.now().strftime('%H:%M:%S')}\n"
            f"资金: ${status.get('capital', 0):,.2f}\n"
            f"持仓: {status.get('open_positions', 0)}\n"
            f"状态: {'运行中' if not status.get('is_stopped') else '已停手'}"
        )
        self._send_message(text)

    def send_error(self, error_message: str):
        """发送错误通知"""
        text = (
            f"🔴 <b>系统错误</b>\n"
            f"────────────────────\n"
            f"{error_message}"
        )
        self._send_message(text)


# 全局通知器实例
notifier = TelegramNotifier()
