"""
OKX Trade Executor Module
Handles order placement, cancellation, and status queries
"""
import json
import hashlib
import hmac
import base64
import time
from datetime import datetime, timezone
from typing import Optional, Dict
from dataclasses import dataclass
import requests
from . import config


OKX_BASE_URL = "https://www.okx.com"


@dataclass
class OrderResult:
    success: bool
    order_id: str
    message: str
    data: Optional[Dict] = None


# 使用 config 中的代理设置
def get_env():
    """获取包含代理设置的环境变量"""
    return config.get_proxy_env()


def get_proxies() -> dict:
    """获取代理配置"""
    proxies = {}
    if config.HTTP_PROXY:
        proxies['http'] = config.HTTP_PROXY
    if config.HTTPS_PROXY:
        proxies['https'] = config.HTTPS_PROXY
    return proxies


def get_timestamp() -> str:
    """获取 ISO 格式的时间戳"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def sign_request(timestamp: str, method: str, path: str, body: str = "") -> tuple:
    """生成 API 签名"""
    if config.DEMO_MODE:
        profile = "demo"
    else:
        profile = "live"

    # 从 config.toml 读取密钥
    api_key = ""
    secret_key = ""
    passphrase = ""

    try:
        import tomllib
        with open("config.toml", "rb") as f:
            toml_data = tomllib.load(f)
            profile_data = toml_data.get("profiles", {}).get(profile, {})
            api_key = profile_data.get("api_key", "")
            secret_key = profile_data.get("secret_key", "")
            passphrase = profile_data.get("passphrase", "")
    except:
        pass

    if not api_key or not secret_key:
        return None, None, None

    # 构建签名字符串
    sign_str = f"{timestamp}{method}{path}{body}"

    # HMAC SHA256 签名
    hmac_key = secret_key.encode('utf-8')
    signature = base64.b64encode(
        hmac.new(hmac_key, sign_str.encode('utf-8'), hashlib.sha256).digest()
    ).decode('utf-8')

    return api_key, signature, passphrase


def okx_request(method: str, endpoint: str, body: dict = None) -> Optional[dict]:
    """发送认证的 OKX API 请求"""
    try:
        url = f"{OKX_BASE_URL}{endpoint}"
        timestamp = get_timestamp()
        body_str = json.dumps(body) if body else ""

        api_key, signature, passphrase = sign_request(
            timestamp, method.upper(), endpoint, body_str
        )

        if not api_key:
            print("API credentials not configured")
            return None

        headers = {
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json"
        }

        # Demo 模式使用 x-simulated-trading 头
        if config.DEMO_MODE:
            headers["x-simulated-trading"] = "1"

        if method.upper() == "GET":
            response = requests.get(url, headers=headers, proxies=get_proxies(), timeout=30)
        else:
            response = requests.post(url, headers=headers, data=body_str, proxies=get_proxies(), timeout=30)

        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"OKX API error: {e}")
        return None
    except Exception as e:
        print(f"Error running command: {e}")
        return None


def place_limit_buy(
    instrument: str,
    price: float,
    size: float,
    stop_loss: float = None,
    tp1: float = None
) -> OrderResult:
    """
    下限价买单

    Args:
        instrument: 交易对 (e.g., "BTC-USDT")
        price: 限价价格
        size: 数量 (BTC)
        stop_loss: 止损价格
        tp1: 止盈价格

    Returns:
        OrderResult
    """
    # 构建订单参数
    body = {
        "instId": instrument,
        "tdMode": "cash",  # 现货
        "side": "buy",
        "ordType": "limit",
        "sz": str(size),
        "px": str(price)
    }

    result = okx_request("POST", "/api/v5/trade/order", body)

    if result and result.get("code") == "0":
        order_id = result.get("data", [{}])[0].get("ordId", "")
        return OrderResult(
            success=True,
            order_id=str(order_id),
            message="订单已提交",
            data=result
        )

    error_msg = result.get("msg", "未知错误") if result else "请求失败"
    return OrderResult(
        success=False,
        order_id="",
        message=f"订单提交失败: {error_msg}"
    )


def place_limit_sell(
    instrument: str,
    price: float,
    size: float,
    stop_loss: float = None,
    tp1: float = None
) -> OrderResult:
    """
    下限价卖单

    Args:
        instrument: 交易对
        price: 限价价格
        size: 数量 (BTC)
        stop_loss: 止损价格
        tp1: 止盈价格

    Returns:
        OrderResult
    """
    body = {
        "instId": instrument,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "limit",
        "sz": str(size),
        "px": str(price)
    }

    result = okx_request("POST", "/api/v5/trade/order", body)

    if result and result.get("code") == "0":
        order_id = result.get("data", [{}])[0].get("ordId", "")
        return OrderResult(
            success=True,
            order_id=str(order_id),
            message="订单已提交",
            data=result
        )

    error_msg = result.get("msg", "未知错误") if result else "请求失败"
    return OrderResult(
        success=False,
        order_id="",
        message=f"订单提交失败: {error_msg}"
    )


def place_market_buy(instrument: str, size: float) -> OrderResult:
    """下市价买单"""
    body = {
        "instId": instrument,
        "tdMode": "cash",
        "side": "buy",
        "ordType": "market",
        "sz": str(size)
    }

    result = okx_request("POST", "/api/v5/trade/order", body)

    if result and result.get("code") == "0":
        order_id = result.get("data", [{}])[0].get("ordId", "")
        return OrderResult(
            success=True,
            order_id=str(order_id),
            message="市价买单已提交",
            data=result
        )

    return OrderResult(success=False, order_id="", message="市价买单失败")


def place_market_sell(instrument: str, size: float) -> OrderResult:
    """下市价卖单"""
    body = {
        "instId": instrument,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": str(size)
    }

    result = okx_request("POST", "/api/v5/trade/order", body)

    if result and result.get("code") == "0":
        order_id = result.get("data", [{}])[0].get("ordId", "")
        return OrderResult(
            success=True,
            order_id=str(order_id),
            message="市价卖单已提交",
            data=result
        )

    return OrderResult(success=False, order_id="", message="市价卖单失败")


def cancel_order(instrument: str, order_id: str) -> bool:
    """取消订单"""
    body = {
        "instId": instrument,
        "ordId": order_id
    }
    result = okx_request("POST", "/api/v5/trade/cancel-order", body)
    return result is not None and result.get("code") == "0"


def get_order_status(instrument: str, order_id: str) -> Optional[Dict]:
    """获取订单状态"""
    result = okx_request("GET", f"/api/v5/trade/order?instId={instrument}&ordId={order_id}")
    if result and result.get("code") == "0" and result.get("data"):
        return result["data"][0]
    return None


def get_open_orders(instrument: str) -> list:
    """获取所有未成交订单"""
    result = okx_request("GET", f"/api/v5/trade/orders-pending?instId={instrument}")
    if result and result.get("code") == "0":
        return result.get("data", [])
    return []


def get_account_balance(ccy: str = "USDT") -> float:
    """获取账户余额"""
    result = okx_request("GET", f"/api/v5/account/balance?ccy={ccy}")
    if result and result.get("code") == "0" and result.get("data"):
        details = result["data"][0].get("details", {})
        if ccy in details:
            return float(details[ccy].get("availBal", 0))
    return 0.0


def execute_entry(
    instrument: str,
    side: str,
    price: float,
    size: float,
    stop_loss: float,
    tp1: float
) -> OrderResult:
    """
    执行入场订单

    Args:
        instrument: 交易对
        side: "buy" 或 "sell"
        price: 入场价格
        size: 数量
        stop_loss: 止损价格
        tp1: 第一止盈目标

    Returns:
        OrderResult
    """
    if side == "buy":
        return place_limit_buy(instrument, price, size, stop_loss, tp1)
    else:
        return place_limit_sell(instrument, price, size, stop_loss, tp1)


def execute_exit(instrument: str, side: str, size: float) -> OrderResult:
    """
    执行平仓 (市价)

    Args:
        instrument: 交易对
        side: "buy" (平空) 或 "sell" (平多)
        size: 数量

    Returns:
        OrderResult
    """
    # 平多仓用卖单，平空仓用买单
    exit_side = "sell" if side == "long" else "buy"
    if exit_side == "buy":
        return place_market_buy(instrument, size)
    else:
        return place_market_sell(instrument, size)


if __name__ == "__main__":
    # 测试
    print("Testing trade executor...")

    # 获取未成交订单
    orders = get_open_orders("BTC-USDT")
    print(f"Open orders: {orders}")
