"""
订单管理工具 - 纯 SDK 功能
Order Management Utilities - Pure SDK Functions

这个模块提供订单同步、状态跟踪和批量操作功能
专门为 Lighter Protocol 优化
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OrderInfo:
    """订单信息数据类"""
    order_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    price: float
    quantity: float
    remaining_quantity: float
    status: str
    timestamp: float
    position_type: Optional[str] = None  # 'long' or 'short'


class OrderTracker:
    """订单跟踪器 - 管理活跃订单状态"""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.active_orders: Dict[str, OrderInfo] = {}
        self.last_sync_time = 0
        self.sync_interval = 60  # 60秒同步间隔

        # 订单计数器 (用于显示)
        self.buy_orders_count = 0
        self.sell_orders_count = 0

        # 统计信息
        self.total_filled_orders = 0
        self.total_cancelled_orders = 0

    def add_order(self, order_info: OrderInfo) -> None:
        """添加订单到跟踪"""
        self.active_orders[order_info.order_id] = order_info
        self._update_counters()
        logger.debug(f"📋 添加订单跟踪: {order_info.order_id} ({order_info.side} {order_info.quantity})")

    def remove_order(self, order_id: str) -> Optional[OrderInfo]:
        """移除订单跟踪"""
        order_info = self.active_orders.pop(order_id, None)
        if order_info:
            self._update_counters()
            logger.debug(f"📋 移除订单跟踪: {order_id}")
        return order_info

    def update_order(self, order_id: str, **updates) -> bool:
        """更新订单信息"""
        if order_id in self.active_orders:
            order_info = self.active_orders[order_id]
            for key, value in updates.items():
                if hasattr(order_info, key):
                    setattr(order_info, key, value)
            self._update_counters()
            return True
        return False

    def get_order(self, order_id: str) -> Optional[OrderInfo]:
        """获取订单信息"""
        return self.active_orders.get(order_id)

    def get_orders_by_side(self, side: str) -> List[OrderInfo]:
        """按方向获取订单"""
        return [order for order in self.active_orders.values() if order.side == side]

    def get_orders_by_position_type(self, position_type: str) -> List[OrderInfo]:
        """按持仓类型获取订单"""
        return [order for order in self.active_orders.values()
                if order.position_type == position_type]

    def clear_all(self) -> int:
        """清除所有订单跟踪"""
        count = len(self.active_orders)
        self.active_orders.clear()
        self._update_counters()
        return count

    def cleanup_stale_orders(self, max_age_seconds: int = 1800) -> int:
        """清理过时订单 (默认30分钟)"""
        current_time = time.time()
        stale_orders = [
            order_id for order_id, order_info in self.active_orders.items()
            if current_time - order_info.timestamp > max_age_seconds
        ]

        for order_id in stale_orders:
            self.remove_order(order_id)

        if stale_orders:
            logger.info(f"🔄 清理了 {len(stale_orders)} 个过时订单")

        return len(stale_orders)

    def _update_counters(self) -> None:
        """更新订单计数器"""
        self.buy_orders_count = len([o for o in self.active_orders.values() if o.side == 'buy'])
        self.sell_orders_count = len([o for o in self.active_orders.values() if o.side == 'sell'])

    def get_order_counts(self) -> Dict[str, int]:
        """获取订单统计"""
        return {
            'total_active': len(self.active_orders),
            'buy_orders': self.buy_orders_count,
            'sell_orders': self.sell_orders_count,
            'total_filled': self.total_filled_orders,
            'total_cancelled': self.total_cancelled_orders
        }

    def should_sync(self) -> bool:
        """检查是否需要同步"""
        return time.time() - self.last_sync_time > self.sync_interval

    def mark_synced(self) -> None:
        """标记已同步"""
        self.last_sync_time = time.time()


class OrderSyncManager:
    """订单同步管理器 - 处理 API 同步"""

    def __init__(self, lighter_client):
        self.lighter = lighter_client
        self.trackers: Dict[str, OrderTracker] = {}

    def get_tracker(self, symbol: str) -> OrderTracker:
        """获取或创建订单跟踪器"""
        if symbol not in self.trackers:
            self.trackers[symbol] = OrderTracker(symbol)
        return self.trackers[symbol]

    async def sync_orders_from_api(self, symbol: str) -> bool:
        """从 API 同步订单状态"""
        try:
            tracker = self.get_tracker(symbol)

            # 获取 API 订单数据
            response = await self.lighter.account_active_orders(symbol)
            if not isinstance(response, dict):
                logger.warning(f"API 响应格式异常: {type(response)}")
                return False

            # 检查响应代码
            response_code = response.get('code')
            if response_code and response_code != 200:
                logger.warning(f"API 返回错误代码: {response_code}")
                return False

            # 处理订单数据
            orders = response.get('orders', [])
            api_order_ids = set()
            active_orders = []

            for order_data in orders:
                order_info = self._parse_order_data(order_data, symbol)
                if order_info and self._is_active_order(order_info):
                    api_order_ids.add(order_info.order_id)
                    active_orders.append(order_info)

                    # 更新或添加到跟踪器
                    if order_info.order_id in tracker.active_orders:
                        tracker.update_order(order_info.order_id,
                                           remaining_quantity=order_info.remaining_quantity,
                                           status=order_info.status)
                    else:
                        tracker.add_order(order_info)

            # 移除不再活跃的订单
            tracked_order_ids = set(tracker.active_orders.keys())
            completed_order_ids = tracked_order_ids - api_order_ids

            for order_id in completed_order_ids:
                completed_order = tracker.remove_order(order_id)
                if completed_order:
                    logger.debug(f"🎯 订单已完成: {order_id}")
                    # 这里可以触发订单完成的回调

            tracker.mark_synced()
            logger.debug(f"✅ {symbol} 订单同步完成: {len(active_orders)} 个活跃订单")
            return True

        except Exception as e:
            logger.warning(f"API 订单同步失败: {e}")
            return False

    def _parse_order_data(self, order_data: Dict, symbol: str) -> Optional[OrderInfo]:
        """解析 API 订单数据"""
        try:
            order_id = str(order_data.get('order_id', order_data.get('order_index', '')))
            if not order_id:
                return None

            is_ask = order_data.get('is_ask', False)
            side = 'sell' if is_ask else 'buy'
            price = float(order_data.get('price', '0'))
            total_quantity = float(order_data.get('base_amount', '0'))
            remaining_quantity = float(order_data.get('remaining_base_amount', '0'))
            status = order_data.get('status', '').lower()

            return OrderInfo(
                order_id=order_id,
                symbol=symbol,
                side=side,
                price=price,
                quantity=total_quantity,
                remaining_quantity=remaining_quantity,
                status=status,
                timestamp=time.time()
            )

        except (ValueError, KeyError) as e:
            logger.warning(f"解析订单数据失败: {e}")
            return None

    def _is_active_order(self, order_info: OrderInfo) -> bool:
        """检查订单是否活跃"""
        return (order_info.status in ['active', 'open', 'pending', 'live'] and
                order_info.remaining_quantity > 0)

    async def get_order_count_from_api(self, symbol: str) -> int:
        """从 API 获取活跃订单数量"""
        try:
            response = await self.lighter.account_active_orders(symbol)
            if isinstance(response, dict) and response.get('code') == 200:
                orders = response.get('orders', [])
                active_count = 0
                for order in orders:
                    status = order.get('status', '').lower()
                    remaining = float(order.get('remaining_base_amount', '0'))
                    if status in ['active', 'open', 'pending', 'live'] and remaining > 0:
                        active_count += 1
                return active_count
        except Exception as e:
            logger.debug(f"获取 API 订单数量失败: {e}")

        return 0

    def cleanup_all_trackers(self, max_age_seconds: int = 1800) -> Dict[str, int]:
        """清理所有跟踪器中的过时订单"""
        cleanup_results = {}
        for symbol, tracker in self.trackers.items():
            cleaned = tracker.cleanup_stale_orders(max_age_seconds)
            if cleaned > 0:
                cleanup_results[symbol] = cleaned
        return cleanup_results

    def get_all_order_counts(self) -> Dict[str, Dict[str, int]]:
        """获取所有交易对的订单统计"""
        return {symbol: tracker.get_order_counts()
                for symbol, tracker in self.trackers.items()}


class BatchOrderManager:
    """批量订单管理器 - 处理批量订单操作"""

    def __init__(self, lighter_client, dry_run=False):
        self.lighter = lighter_client
        self.dry_run = dry_run

    async def cancel_all_orders_safe(self) -> Dict[str, Any]:
        """安全地撤销所有订单 (带错误处理和 DRY RUN 支持)"""
        result = {
            'success': False,
            'cancelled_count': 0,
            'error': None,
            'method': 'unknown'
        }

        try:
            if self.dry_run:
                logger.info("🔄 DRY RUN - 模拟批量撤销所有订单")
                result['success'] = True
                result['method'] = 'dry_run'
                result['cancelled_count'] = 0
                logger.info("✅ DRY RUN 模拟撤销完成")
                return result

            # 尝试批量撤销 (真实模式)
            logger.info("🚫 尝试批量撤销所有订单...")
            api_result = await self.lighter.cancel_all_orders()

            # 处理不同的返回格式
            if api_result is None:
                result['error'] = "API 返回 None"
            elif isinstance(api_result, tuple):
                if len(api_result) >= 2:
                    response, error = api_result[0], api_result[1]
                    if error is None:
                        result['success'] = True
                        result['method'] = 'bulk_cancel'
                        logger.info("✅ 批量撤销成功")
                    else:
                        result['error'] = str(error)
                else:
                    result['success'] = True
                    result['method'] = 'bulk_cancel'
                    logger.info("✅ 批量撤销完成")
            else:
                result['success'] = True
                result['method'] = 'bulk_cancel'
                logger.info("✅ 批量撤销成功")

        except Exception as e:
            result['error'] = str(e)
            logger.warning(f"⚠️ 批量撤销失败: {e}")

        return result

    async def cancel_orders_for_side_safe(self, symbol: str, position_side: str) -> Dict[str, Any]:
        """安全地撤销特定方向的订单 (对齐 Binance 参考策略)"""
        result = {
            'success': False,
            'cancelled_count': 0,
            'error': None,
            'method': 'selective_cancel',
            'side': position_side
        }

        try:
            if self.dry_run:
                logger.info(f"🔄 DRY RUN - 模拟撤销 {position_side} 订单")
                result['success'] = True
                result['method'] = 'dry_run'
                logger.info(f"✅ DRY RUN 模拟撤销 {position_side} 订单完成")
                return result

            # 获取活跃订单
            logger.debug(f"🔍 获取 {symbol} 活跃订单...")
            response = await self.lighter.account_active_orders(symbol)

            if not isinstance(response, dict) or response.get('code') != 200:
                result['error'] = f"获取订单失败: {response}"
                return result

            orders = response.get('orders', [])
            if not orders:
                logger.debug(f"没有找到 {symbol} 的活跃订单")
                result['success'] = True
                return result

            # 筛选需要撤销的订单
            orders_to_cancel = []
            for order in orders:
                is_ask = order.get('is_ask', False)
                order_side = 'sell' if is_ask else 'buy'

                # 根据持仓方向筛选订单
                should_cancel = False
                if position_side == 'long':
                    # 多头方向：撤销多头相关的买单和卖单
                    should_cancel = True  # 简化：撤销所有订单，因为无法区分持仓方向
                elif position_side == 'short':
                    # 空头方向：撤销空头相关的买单和卖单
                    should_cancel = True  # 简化：撤销所有订单，因为无法区分持仓方向

                if should_cancel:
                    order_id = str(order.get('order_id', order.get('order_index', '')))
                    if order_id:
                        orders_to_cancel.append(order_id)

            # 逐个撤销订单
            cancelled_count = 0
            for order_id in orders_to_cancel:
                try:
                    logger.debug(f"🚫 撤销订单: {order_id}")
                    await self.lighter.cancel_order(symbol, order_id)
                    cancelled_count += 1
                    await asyncio.sleep(0.1)  # 防止请求过快
                except Exception as e:
                    logger.warning(f"撤销订单 {order_id} 失败: {e}")

            result['success'] = True
            result['cancelled_count'] = cancelled_count
            logger.info(f"✅ 撤销 {position_side} 订单完成: {cancelled_count} 个")

        except Exception as e:
            result['error'] = str(e)
            logger.warning(f"⚠️ 撤销 {position_side} 订单失败: {e}")

        return result

    async def validate_order_limits(self, symbol: str, max_orders_per_symbol: int = 50) -> Dict[str, Any]:
        """验证订单限制"""
        try:
            # 获取当前订单数量
            response = await self.lighter.account_active_orders(symbol)
            if isinstance(response, dict) and response.get('code') == 200:
                orders = response.get('orders', [])
                active_count = len([o for o in orders
                                  if o.get('status', '').lower() in ['active', 'open', 'pending', 'live']
                                  and float(o.get('remaining_base_amount', '0')) > 0])

                return {
                    'current_count': active_count,
                    'max_allowed': max_orders_per_symbol,
                    'can_place_more': active_count < max_orders_per_symbol,
                    'remaining_slots': max(0, max_orders_per_symbol - active_count)
                }

        except Exception as e:
            logger.warning(f"验证订单限制失败: {e}")

        return {
            'current_count': 0,
            'max_allowed': max_orders_per_symbol,
            'can_place_more': True,
            'remaining_slots': max_orders_per_symbol,
            'error': 'validation_failed'
        }