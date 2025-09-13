"""
市场数据工具 - 纯 SDK 功能
Market Data Utilities - Pure SDK Functions

这个模块提供市场约束获取、价格精度处理和数量计算功能
专门为 Lighter Protocol 优化
"""

import math
import logging
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MarketConstraints:
    """市场约束数据类"""
    symbol: str
    market_id: int
    min_quote_amount: float
    min_base_amount: float
    price_precision: int
    amount_precision: int
    step_size: float
    tick_size: float


class MarketDataManager:
    """市场数据管理器"""

    def __init__(self, lighter_client):
        self.lighter = lighter_client
        self.constraints_cache: Dict[str, MarketConstraints] = {}
        self.last_cache_update = 0
        self.cache_duration = 3600  # 1小时缓存

    async def get_market_constraints(self, symbol: str, use_cache: bool = True) -> MarketConstraints:
        """获取市场约束 (带缓存)"""
        import time

        # 检查缓存
        if (use_cache and symbol in self.constraints_cache and
            time.time() - self.last_cache_update < self.cache_duration):
            return self.constraints_cache[symbol]

        try:
            # 从客户端获取约束信息
            constraints = await self._fetch_constraints_from_client(symbol)

            # 更新缓存
            self.constraints_cache[symbol] = constraints
            self.last_cache_update = time.time()

            logger.debug(f"✅ 获取 {symbol} 市场约束: 最小报价=${constraints.min_quote_amount}")
            return constraints

        except Exception as e:
            logger.warning(f"获取 {symbol} 市场约束失败: {e}")
            # 返回默认约束
            return self._get_default_constraints(symbol)

    async def _fetch_constraints_from_client(self, symbol: str) -> MarketConstraints:
        """从客户端获取约束信息"""
        # 获取市场 ID
        market_id = self.lighter.ticker_to_idx.get(symbol)
        if market_id is None:
            raise ValueError(f"未找到交易对 {symbol}")

        # 获取精度和最小值
        price_precision = self.lighter.ticker_to_price_precision.get(symbol, 6)
        amount_precision = self.lighter.ticker_to_lot_precision.get(symbol, 1)
        min_quote_amount = self.lighter.ticker_min_quote.get(symbol, 10.0)
        min_base_amount = self.lighter.ticker_min_base.get(symbol, 0.1)

        # 计算步长
        step_size = 10 ** (-amount_precision)
        tick_size = 10 ** (-price_precision)

        return MarketConstraints(
            symbol=symbol,
            market_id=market_id,
            min_quote_amount=min_quote_amount,
            min_base_amount=min_base_amount,
            price_precision=price_precision,
            amount_precision=amount_precision,
            step_size=step_size,
            tick_size=tick_size
        )

    def _get_default_constraints(self, symbol: str) -> MarketConstraints:
        """获取默认约束 (当 API 失败时使用)"""
        market_id = self.lighter.ticker_to_idx.get(symbol, 0)

        return MarketConstraints(
            symbol=symbol,
            market_id=market_id,
            min_quote_amount=10.0,
            min_base_amount=0.1,
            price_precision=6,
            amount_precision=1,
            step_size=0.1,
            tick_size=0.000001
        )

    def format_price(self, price: float, symbol: str) -> float:
        """格式化价格到正确精度"""
        constraints = self.constraints_cache.get(symbol)
        if not constraints:
            # 如果没有缓存，使用客户端数据
            precision = self.lighter.ticker_to_price_precision.get(symbol, 6)
        else:
            precision = constraints.price_precision

        return round(price, precision)

    def format_quantity(self, quantity: float, symbol: str) -> float:
        """格式化数量到正确精度"""
        constraints = self.constraints_cache.get(symbol)
        if not constraints:
            # 如果没有缓存，使用客户端数据
            precision = self.lighter.ticker_to_lot_precision.get(symbol, 1)
            step_size = 10 ** (-precision)
        else:
            precision = constraints.amount_precision
            step_size = constraints.step_size

        # 使用步长进行舍入
        if step_size > 0:
            return math.floor(abs(quantity) / step_size) * step_size
        else:
            return round(abs(quantity), precision)

    def calculate_quantity_for_quote_amount(self, price: float, quote_amount: float,
                                          symbol: str) -> Tuple[float, bool, str]:
        """
        根据报价金额计算基础货币数量

        返回: (计算的数量, 是否有效, 错误信息)
        """
        try:
            if price <= 0:
                return 0, False, "价格必须大于0"

            if quote_amount <= 0:
                return 0, False, "报价金额必须大于0"

            # 获取约束
            constraints = self.constraints_cache.get(symbol)
            if not constraints:
                # 使用默认值
                min_quote = self.lighter.ticker_min_quote.get(symbol, 10.0)
                precision = self.lighter.ticker_to_lot_precision.get(symbol, 1)
                step_size = 10 ** (-precision)
            else:
                min_quote = constraints.min_quote_amount
                step_size = constraints.step_size
                precision = constraints.amount_precision

            # 检查最小报价金额
            if quote_amount < min_quote:
                return 0, False, f"报价金额必须至少 ${min_quote}"

            # 计算基础数量
            base_quantity = quote_amount / price

            # 应用步长
            if step_size > 0:
                formatted_quantity = math.floor(base_quantity / step_size) * step_size
            else:
                formatted_quantity = round(base_quantity, precision)

            # 验证最终结果
            final_quote = formatted_quantity * price
            if final_quote < min_quote:
                # 调整到最小要求
                min_quantity = min_quote / price
                if step_size > 0:
                    formatted_quantity = math.ceil(min_quantity / step_size) * step_size
                else:
                    formatted_quantity = round(min_quantity, precision)

            return formatted_quantity, True, ""

        except Exception as e:
            error_msg = f"数量计算失败: {e}"
            logger.error(error_msg)
            return 0, False, error_msg

    def validate_order_amount(self, price: float, quantity: float,
                            symbol: str) -> Tuple[bool, float, str]:
        """
        验证订单金额和数量

        返回: (是否有效, 调整后的数量, 消息)
        """
        try:
            # 获取约束
            constraints = self.constraints_cache.get(symbol)
            if not constraints:
                min_quote = self.lighter.ticker_min_quote.get(symbol, 10.0)
                min_base = self.lighter.ticker_min_base.get(symbol, 0.1)
            else:
                min_quote = constraints.min_quote_amount
                min_base = constraints.min_base_amount

            # 格式化数量
            formatted_quantity = self.format_quantity(abs(quantity), symbol)

            # 检查最小基础数量
            if formatted_quantity < min_base:
                formatted_quantity = min_base
                logger.debug(f"数量调整到最小基础数量: {formatted_quantity}")

            # 检查最小报价金额
            quote_value = formatted_quantity * price
            if quote_value < min_quote:
                # 重新计算最小数量
                min_quantity_for_quote = min_quote / price
                formatted_quantity = self.format_quantity(min_quantity_for_quote, symbol)

                # 确保调整后仍满足要求
                final_quote = formatted_quantity * price
                if final_quote < min_quote:
                    # 微调确保满足最小报价要求
                    formatted_quantity *= 1.01  # 增加1%
                    formatted_quantity = self.format_quantity(formatted_quantity, symbol)

                return True, formatted_quantity, f"数量已调整以满足最小报价要求 (${min_quote})"

            return True, formatted_quantity, "订单金额有效"

        except Exception as e:
            error_msg = f"订单验证失败: {e}"
            logger.error(error_msg)
            return False, abs(quantity), error_msg

    def calculate_grid_prices(self, center_price: float, grid_spacing: float,
                            levels: int, symbol: str) -> Dict[str, list]:
        """
        计算网格价格

        参数:
            center_price: 中心价格
            grid_spacing: 网格间距 (小数形式, 如 0.001 表示 0.1%)
            levels: 网格层数
            symbol: 交易对符号

        返回:
            {'buy_prices': [price1, price2, ...], 'sell_prices': [price1, price2, ...]}
        """
        try:
            buy_prices = []
            sell_prices = []

            for i in range(1, levels + 1):
                # 买入价格 (低于中心价)
                buy_price = center_price * (1 - grid_spacing * i)
                buy_price = self.format_price(buy_price, symbol)
                buy_prices.append(buy_price)

                # 卖出价格 (高于中心价)
                sell_price = center_price * (1 + grid_spacing * i)
                sell_price = self.format_price(sell_price, symbol)
                sell_prices.append(sell_price)

            return {
                'buy_prices': sorted(buy_prices, reverse=True),  # 从高到低
                'sell_prices': sorted(sell_prices)  # 从低到高
            }

        except Exception as e:
            logger.error(f"计算网格价格失败: {e}")
            return {'buy_prices': [], 'sell_prices': []}

    def get_price_change_percentage(self, old_price: float, new_price: float) -> float:
        """计算价格变化百分比"""
        if old_price <= 0:
            return 0.0
        return ((new_price - old_price) / old_price) * 100

    def is_significant_price_move(self, old_price: float, new_price: float,
                                threshold: float = 0.001) -> bool:
        """检查是否为显著价格变动"""
        if old_price <= 0:
            return True

        change_pct = abs((new_price - old_price) / old_price)
        return change_pct >= threshold

    def clear_cache(self) -> None:
        """清除约束缓存"""
        self.constraints_cache.clear()
        self.last_cache_update = 0
        logger.info("✅ 市场约束缓存已清除")

    def get_cached_symbols(self) -> list:
        """获取已缓存的交易对列表"""
        return list(self.constraints_cache.keys())