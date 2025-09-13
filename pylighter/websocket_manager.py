"""
WebSocket 管理工具 - 纯 SDK 功能
WebSocket Management Utilities - Pure SDK Functions

这个模块提供 WebSocket 连接管理、重连逻辑和错误处理
专门为 Lighter Protocol 优化
"""

import asyncio
import json
import logging
import websockets
import time
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger(__name__)


class AccountWebSocketManager:
    """账户 WebSocket 管理器 - 处理订单和账户更新"""

    def __init__(self, auth_token: str, market_id: int, account_idx: int):
        self.auth_token = auth_token
        self.market_id = market_id
        self.account_idx = account_idx
        self.websocket_url = "wss://mainnet.zklighter.elliot.ai/stream"

        # 连接状态
        self.connected = False
        self.subscribed = False
        self.shutdown_requested = False

        # 重连配置
        self.max_retries = 5
        self.retry_count = 0
        self.base_delay = 2

        # 回调函数
        self.on_orders_update: Optional[Callable] = None
        self.on_connection_status: Optional[Callable] = None

        # 健康监控
        self.last_message_time = None
        self.connection_start_time = None

    def set_orders_callback(self, callback: Callable[[Dict], None]):
        """设置订单更新回调函数"""
        self.on_orders_update = callback

    def set_status_callback(self, callback: Callable[[bool], None]):
        """设置连接状态回调函数"""
        self.on_connection_status = callback

    async def connect_and_run(self) -> None:
        """连接并运行 WebSocket (带重连逻辑)"""
        while not self.shutdown_requested and self.retry_count < self.max_retries:
            try:
                await self._run_websocket_session()
                self.retry_count = 0  # 重置重试计数
            except websockets.exceptions.ConnectionClosed:
                self._handle_connection_closed()
            except websockets.exceptions.WebSocketException as e:
                self._handle_websocket_error(e)
            except Exception as e:
                self._handle_unexpected_error(e)

            if not self.shutdown_requested and self.retry_count < self.max_retries:
                await self._wait_before_retry()

    async def _run_websocket_session(self):
        """运行单个 WebSocket 会话"""
        logger.info("🌐 连接到账户 WebSocket...")
        self.connection_start_time = time.time()

        async with websockets.connect(self.websocket_url) as ws:
            self.connected = False
            self.subscribed = False

            # 设置连接超时
            connection_timeout = 10
            start_time = time.time()

            async for message in ws:
                if self.shutdown_requested:
                    break

                # 检查连接超时
                if time.time() - start_time > connection_timeout and not self.connected:
                    logger.warning("⏱️ WebSocket 连接超时")
                    break

                await self._handle_message(ws, message)

    async def _handle_message(self, ws, message: str):
        """处理 WebSocket 消息"""
        try:
            data = json.loads(message)
            message_type = data.get('type', '')
            self.last_message_time = time.time()

            logger.debug(f"📨 WebSocket 消息: type={message_type}")

            if message_type == 'connected':
                await self._handle_connected(ws)
            elif message_type == 'subscribed/account_orders' or message_type.startswith('subscribed'):
                await self._handle_subscribed(data)
            elif message_type == 'update/account_orders':
                await self._handle_orders_update(data)
            elif message_type == 'error':
                self._handle_error_message(data)
            elif message_type == 'ping':
                await self._handle_ping(ws)
            elif message_type == 'pong':
                logger.debug("🏓 收到 pong")
            else:
                if message_type and message_type not in ['heartbeat', 'status']:
                    logger.debug(f"📨 未处理的消息: {message_type}")

        except json.JSONDecodeError as e:
            logger.warning(f"❌ JSON 解析失败: {e}")
        except Exception as e:
            logger.error(f"❌ 处理消息错误: {e}")

    async def _handle_connected(self, ws):
        """处理连接确认"""
        logger.info("🔗 WebSocket 已连接，发送订阅请求...")
        self.connected = True

        # 发送订阅请求
        subscribe_msg = {
            "type": "subscribe",
            "channel": f"account_orders/{self.market_id}/{self.account_idx}",
            "auth": self.auth_token
        }
        await ws.send(json.dumps(subscribe_msg))
        logger.info(f"📋 已发送账户订单订阅请求 (市场 {self.market_id})")

        # 通知连接状态
        if self.on_connection_status:
            self.on_connection_status(True)

    async def _handle_subscribed(self, data: Dict):
        """处理订阅确认"""
        channel = data.get('channel', '')
        if 'account_orders' in channel:
            logger.info(f"✅ 成功订阅账户订单: {channel}")
            self.subscribed = True
            self.retry_count = 0  # 重置重试计数

    async def _handle_orders_update(self, data: Dict):
        """处理订单更新"""
        if not self.subscribed:
            logger.debug("忽略订单更新 - 尚未正确订阅")
            return

        orders_data = data.get('orders', {})
        market_orders = orders_data.get(str(self.market_id), [])

        logger.info(f"🔍 处理账户订单更新: {len(market_orders)} 个订单")

        # 调用回调函数
        if self.on_orders_update:
            self.on_orders_update(data)

    def _handle_error_message(self, data: Dict):
        """处理错误消息"""
        error_msg = data.get('message', data.get('error', 'Unknown error'))
        logger.error(f"❌ WebSocket 错误: {error_msg}")

    async def _handle_ping(self, ws):
        """处理 ping 消息"""
        await ws.send(json.dumps({"type": "pong"}))
        logger.debug("🏓 响应 ping")

    def _handle_connection_closed(self):
        """处理连接关闭"""
        logger.warning("🔌 WebSocket 连接已关闭")
        self.connected = False
        self.subscribed = False
        self.retry_count += 1

        if self.on_connection_status:
            self.on_connection_status(False)

    def _handle_websocket_error(self, error):
        """处理 WebSocket 错误"""
        logger.error(f"❌ WebSocket 错误: {error}")
        self.connected = False
        self.subscribed = False
        self.retry_count += 1

        if self.on_connection_status:
            self.on_connection_status(False)

    def _handle_unexpected_error(self, error):
        """处理意外错误"""
        logger.error(f"❌ 意外错误: {error}")
        self.connected = False
        self.subscribed = False
        self.retry_count += 1

    async def _wait_before_retry(self):
        """重连前等待"""
        wait_time = min(self.base_delay ** self.retry_count, 10)  # 最大10秒
        logger.info(f"⏳ {wait_time}秒后重试连接 (第{self.retry_count}/{self.max_retries}次)")
        await asyncio.sleep(wait_time)

    def shutdown(self):
        """关闭 WebSocket 连接"""
        logger.info("🛑 关闭 WebSocket 管理器")
        self.shutdown_requested = True

    def is_healthy(self, max_silence_seconds: int = 120) -> bool:
        """检查连接健康状态"""
        if not self.connected or not self.subscribed:
            return False

        if self.last_message_time is None:
            # 如果连接时间过长但没收到消息
            if self.connection_start_time and time.time() - self.connection_start_time > max_silence_seconds:
                return False
            return True

        # 检查最后收到消息的时间
        return time.time() - self.last_message_time < max_silence_seconds


class PriceWebSocketManager:
    """价格 WebSocket 管理器 - 处理订单簿更新"""

    def __init__(self, market_ids: list):
        self.market_ids = market_ids
        self.ws_client = None
        self.shutdown_requested = False

        # 回调函数
        self.on_price_update: Optional[Callable] = None

        # 重连配置
        self.max_retries = 10
        self.retry_delay = 3

    def set_price_callback(self, callback: Callable[[int, Dict], None]):
        """设置价格更新回调函数"""
        self.on_price_update = callback

    async def initialize_and_run(self):
        """初始化并运行价格 WebSocket"""
        import lighter

        def on_order_book_update(market_id, order_book):
            try:
                # 跳过 ping/pong 处理
                if isinstance(order_book, dict) and order_book.get('type') in ['ping', 'pong']:
                    return

                if self.on_price_update and int(market_id) in self.market_ids:
                    self.on_price_update(int(market_id), order_book)

            except Exception as e:
                if not any(keyword in str(e).lower() for keyword in ['ping', 'pong', 'connection']):
                    logger.error(f"价格更新处理错误: {e}")

        # 创建 WebSocket 客户端
        self.ws_client = lighter.WsClient(
            order_book_ids=self.market_ids,
            account_ids=[],
            on_order_book_update=on_order_book_update,
            on_account_update=lambda a, b: None,
        )

        logger.info(f"✅ 价格 WebSocket 初始化完成 (市场: {self.market_ids})")

        # 运行 WebSocket (带重连)
        await self._run_with_retry()

    async def _run_with_retry(self):
        """运行 WebSocket 带重连逻辑"""
        retry_count = 0

        while not self.shutdown_requested and retry_count < self.max_retries:
            try:
                logger.info("🌐 启动价格 WebSocket 连接...")
                retry_count = 0  # 重置计数
                await self.ws_client.run_async()
            except Exception as e:
                retry_count += 1

                # 过滤非关键错误
                error_msg = str(e).lower()
                is_critical = not any(keyword in error_msg for keyword in [
                    'ping', 'pong', 'connection reset', 'connection closed', 'timeout'
                ])

                if is_critical:
                    logger.error(f"价格 WebSocket 关键错误: {e}")
                else:
                    logger.debug(f"价格 WebSocket 非关键错误: {e}")

                if retry_count < self.max_retries:
                    wait_time = min(self.retry_delay * min(retry_count, 3), 30)
                    logger.info(f"⏳ 价格 WebSocket {wait_time}秒后重试 (第{retry_count}/{self.max_retries}次)")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("❌ 价格 WebSocket 最大重试次数已达到")
                    break

    def shutdown(self):
        """关闭价格 WebSocket"""
        logger.info("🛑 关闭价格 WebSocket 管理器")
        self.shutdown_requested = True