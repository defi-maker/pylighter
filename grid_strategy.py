"""
简化网格交易策略

使用 pylighter SDK 工具简化代码，保持核心功能完整

主要特点：
- 使用 SDK 工具处理 WebSocket、订单管理和市场数据
- 代码简洁但功能完整，专注于交易逻辑
- 优雅的启动检查和关闭处理
"""

import os
import asyncio
import time
import argparse
import signal
import lighter
from dotenv import load_dotenv

# 使用新的 SDK 工具
from pylighter.client import Lighter
from pylighter.websocket_manager import PriceWebSocketManager
from pylighter.order_manager import OrderSyncManager, BatchOrderManager
from pylighter.market_utils import MarketDataManager

# 使用日志工具库
from utils.logger_config import get_strategy_logger

# 加载环境变量
load_dotenv()

# 初始化日志器
logger = get_strategy_logger("grid")

# ==================== 配置 ====================
COIN_NAME = "TON"

# 🎯 优化后的核心参数
GRID_SPACING = 0.0005         # 0.05% 优化网格间距 (与价格阈值协调)
INITIAL_QUANTITY = 15.0       # 每单 $15 USD (保持不变，金额合理)
LEVERAGE = 6                  # 6倍杠杆 (降低风险暴露)
POSITION_THRESHOLD_RATIO = 0.5   # 持仓阈值比例 (50% of 账户价值)
ORDER_FIRST_TIME = 3          # 首单间隔3秒 (提高响应速度)

# 新增优化参数
MAX_ORDERS_PER_SIDE = 15      # 单边最大订单数 (降低复杂度)
ORDER_REFRESH_INTERVAL = 20   # 订单刷新间隔(秒) (更频繁调整)
PRICE_UPDATE_THRESHOLD = 0.0002  # 价格变动阈值 0.02% (减少噪音交易)

# 🚀 动态止盈参数 (对齐 Binance 参考实现)
DYNAMIC_PROFIT_MIN = 0.005    # 最小止盈率 0.5%
DYNAMIC_PROFIT_MAX = 0.1      # 最大止盈率 10%
HEDGE_RATIO_DIVISOR = 100     # 对冲比例除数 (对齐 Binance / 100 + 1)
INVENTORY_REDUCTION_RATIO = 0.8  # 库存风险阈值比例 (80%)

# 🔧 API优化参数 (减少服务器压力)
POSITION_SYNC_INTERVAL = 180  # 持仓同步间隔 (3分钟，降低API压力)
ORDER_SYNC_INTERVAL = 60      # 订单同步间隔 (1分钟)
STATS_DISPLAY_INTERVAL = 300  # 统计显示间隔 (5分钟)
LOG_THROTTLE_FACTOR = 10      # 日志节流因子 (每10次循环显示一次状态)


class GridBot:
    """网格交易机器人 - 使用 pylighter SDK 工具"""

    def __init__(self, dry_run=False, max_orders_per_side=None, grid_spacing=None, order_amount=None, price_threshold=None):
        self.dry_run = dry_run
        self.symbol = COIN_NAME
        self.shutdown_requested = False

        # 可配置的策略参数
        self.max_orders_per_side = max_orders_per_side or MAX_ORDERS_PER_SIDE
        self.grid_spacing = grid_spacing or GRID_SPACING
        self.initial_quantity = order_amount or INITIAL_QUANTITY

        # 核心组件
        self.lighter = None
        self.market_manager = None
        self.order_manager = None
        self.batch_manager = None
        self.price_ws = None

        # 持仓和价格 (对齐 Binance)
        self.long_position = 0
        self.short_position = 0
        self.latest_price = 0
        self.best_bid_price = None
        self.best_ask_price = None

        # 订单数量 (对齐 Binance)
        self.long_initial_quantity = 0
        self.short_initial_quantity = 0

        # 时间控制 (对齐 Binance)
        self.last_long_order_time = 0
        self.last_short_order_time = 0

        # 价格阈值控制 (优化订单频率)
        self.last_order_price = 0          # 上次下单时的价格
        self.price_update_threshold = price_threshold or PRICE_UPDATE_THRESHOLD  # 价格变动阈值

        # 账户信息 (启动时获取一次，避免重复API调用)
        self.total_asset_value = 1000.0    # 默认值，会在 setup 时更新

    async def setup(self):
        """初始化所有组件"""
        # 1. 初始化客户端
        api_key = os.getenv("LIGHTER_KEY")
        api_secret = os.getenv("LIGHTER_SECRET")
        if not api_key or not api_secret:
            raise ValueError("请设置 LIGHTER_KEY 和 LIGHTER_SECRET 环境变量")

        self.lighter = Lighter(key=api_key, secret=api_secret)
        await self.lighter.init_client()

        # 2. 初始化 SDK 工具
        self.market_manager = MarketDataManager(self.lighter)
        self.order_manager = OrderSyncManager(self.lighter)
        self.batch_manager = BatchOrderManager(self.lighter, dry_run=self.dry_run)  # 传递 dry_run 参数

        # 3. 获取市场约束
        constraints = await self.market_manager.get_market_constraints(self.symbol)
        logger.info(f"✅ {self.symbol} 约束: 最小订单=${constraints.min_quote_amount}")

        # 4. 启动状态分析和账户信息获取 (一次性完成，减少重复API调用)
        await self.analyze_startup_state()

        # 6. 初始化价格 WebSocket
        market_id = self.lighter.ticker_to_idx[self.symbol]
        self.price_ws = PriceWebSocketManager([market_id])
        self.price_ws.set_price_callback(self.on_price_update)

        logger.info(f"✅ 简化网格机器人初始化完成: {self.symbol}")

    async def get_account_stats(self) -> dict:
        """获取官方账户统计信息"""
        try:
            # 使用官方 API 获取账户统计
            response = await self.lighter.account(by='l1_address')

            if not isinstance(response, dict) or response.get('code') != 200:
                logger.warning(f"获取账户统计失败: {response}")
                return {}

            accounts = response.get('accounts', [])
            if not accounts:
                logger.warning("未找到账户信息")
                return {}

            account = accounts[0]
            positions = account.get('positions', [])

            # 查找当前交易对的持仓
            current_position = None
            for pos in positions:
                if pos.get('symbol') == self.symbol:
                    current_position = pos
                    break

            # 构建统计信息
            stats = {
                'account_info': {
                    'index': account.get('account_index'),
                    'collateral': float(account.get('collateral', 0)),
                    'available_balance': float(account.get('available_balance', 0)),
                    'total_asset_value': float(account.get('total_asset_value', 0)),
                    'cross_asset_value': float(account.get('cross_asset_value', 0)),
                    'total_order_count': account.get('total_order_count', 0),
                },
                'current_position': {},
                'all_positions': []
            }

            if current_position:
                stats['current_position'] = {
                    'symbol': current_position.get('symbol'),
                    'position': float(current_position.get('position', 0)),
                    'sign': current_position.get('sign', 1),  # 添加 sign 字段
                    'position_value': float(current_position.get('position_value', 0)),
                    'avg_entry_price': float(current_position.get('avg_entry_price', 0)),
                    'unrealized_pnl': float(current_position.get('unrealized_pnl', 0)),
                    'realized_pnl': float(current_position.get('realized_pnl', 0)),
                    'liquidation_price': float(current_position.get('liquidation_price', 0)),
                    'open_order_count': current_position.get('open_order_count', 0),
                }

            # 所有持仓概览
            for pos in positions:
                if float(pos.get('position', 0)) != 0:  # 只显示非零持仓
                    stats['all_positions'].append({
                        'symbol': pos.get('symbol'),
                        'position': float(pos.get('position', 0)),
                        'position_value': float(pos.get('position_value', 0)),
                        'unrealized_pnl': float(pos.get('unrealized_pnl', 0)),
                        'realized_pnl': float(pos.get('realized_pnl', 0)),
                    })

            return stats

        except Exception as e:
            logger.error(f"获取账户统计失败: {e}")
            return {}

    def print_account_stats(self, stats: dict) -> None:
        """打印账户统计信息"""
        if not stats:
            logger.warning("无账户统计信息")
            return

        account_info = stats.get('account_info', {})
        current_pos = stats.get('current_position', {})
        all_positions = stats.get('all_positions', [])

        logger.info("📊 ===== 账户统计信息 (官方 API) =====")
        logger.info(f"💰 账户总览:")
        logger.info(f"   总资产价值: ${account_info.get('total_asset_value', 0):.2f}")
        logger.info(f"   保证金: ${account_info.get('collateral', 0):.2f}")
        logger.info(f"   可用余额: ${account_info.get('available_balance', 0):.2f}")
        logger.info(f"   历史订单总数: {account_info.get('total_order_count', 0)}")

        if current_pos:
            logger.info(f"📈 当前交易对 ({self.symbol}) 持仓:")
            logger.info(f"   持仓数量: {current_pos.get('position', 0)}")
            logger.info(f"   持仓价值: ${current_pos.get('position_value', 0):.2f}")
            logger.info(f"   平均开仓价: ${current_pos.get('avg_entry_price', 0):.6f}")
            logger.info(f"   未实现盈亏: ${current_pos.get('unrealized_pnl', 0):.2f}")
            logger.info(f"   已实现盈亏: ${current_pos.get('realized_pnl', 0):.2f}")
            logger.info(f"   清算价格: ${current_pos.get('liquidation_price', 0):.6f}")
            logger.info(f"   活跃订单数: {current_pos.get('open_order_count', 0)}")

        if all_positions:
            logger.info(f"📋 所有持仓概览 ({len(all_positions)} 个):")
            total_unrealized = sum(pos.get('unrealized_pnl', 0) for pos in all_positions)
            total_realized = sum(pos.get('realized_pnl', 0) for pos in all_positions)
            for pos in all_positions:
                symbol = pos.get('symbol', '')
                position = pos.get('position', 0)
                unrealized = pos.get('unrealized_pnl', 0)
                logger.info(f"   {symbol}: {position:.4f} (未实现: ${unrealized:.2f})")
            logger.info(f"   总未实现盈亏: ${total_unrealized:.2f}")
            logger.info(f"   总已实现盈亏: ${total_realized:.2f}")

        logger.info("=" * 50)

    async def analyze_startup_state(self):
        """启动状态分析 (对齐 Binance) - 一次性获取所有账户信息"""
        logger.info("📊 分析启动状态...")

        # 一次性获取完整账户信息 (减少重复API调用)
        try:
            stats = await self.get_account_stats()
            account_info = stats.get('account_info', {})

            # 设置账户总价值
            self.total_asset_value = account_info.get('total_asset_value', 1000.0)
            logger.info(f"✅ 账户总价值: ${self.total_asset_value:.2f}")

            # 启动时显示一次统计信息并从中提取持仓数据 (避免重复调用)
            self.print_account_stats(stats)

            # 从统计信息中提取持仓数据 (使用 position 和 sign 字段)
            current_position = stats.get('current_position', {})
            if current_position and current_position.get('symbol') == self.symbol:
                position_value = float(current_position.get('position', 0))
                sign_value = current_position.get('sign', 1)  # sign: 1=多头, -1=空头

                if position_value != 0:  # 有持仓
                    if sign_value > 0:
                        self.long_position = abs(position_value)  # 多头持仓
                        self.short_position = 0
                    else:
                        self.long_position = 0
                        self.short_position = abs(position_value)  # 空头持仓
                else:
                    self.long_position = 0
                    self.short_position = 0
            else:
                self.long_position = 0
                self.short_position = 0

        except Exception as e:
            logger.warning(f"获取账户信息失败: {e}")
            self.total_asset_value = 1000.0
            # 后备方案：调用 get_positions 方法
            self.long_position, self.short_position = await self.get_positions()

        logger.info(f"启动持仓: 多头={self.long_position}, 空头={self.short_position}")

        if self.long_position > 0 or self.short_position > 0:
            logger.warning("⚠️ 检测到现有持仓! 网格策略将管理这些持仓")

        # 同步订单状态
        await self.order_manager.sync_orders_from_api(self.symbol)
        tracker = self.order_manager.get_tracker(self.symbol)
        counts = tracker.get_order_counts()
        logger.info(f"启动订单: 活跃={counts['total_active']}, 买单={counts['buy_orders']}, 卖单={counts['sell_orders']}")

    async def get_positions(self):
        """获取持仓 (完整实现)"""
        if self.dry_run:
            return self.long_position, self.short_position

        try:
            # 使用官方账户API获取实际持仓
            response = await self.lighter.account(by='l1_address')

            if not isinstance(response, dict) or response.get('code') != 200:
                logger.warning(f"获取账户信息失败: {response}")
                return self.long_position, self.short_position

            accounts = response.get('accounts', [])
            if not accounts:
                logger.warning("未找到账户信息")
                return self.long_position, self.short_position

            account = accounts[0]
            positions = account.get('positions', [])

            # 查找当前交易对的持仓
            long_pos = 0
            short_pos = 0

            for pos in positions:
                if pos.get('symbol') == self.symbol:
                    position_value = float(pos.get('position', 0))
                    sign_value = pos.get('sign', 1)  # sign: 1=多头, -1=空头

                    if position_value != 0:  # 有持仓
                        if sign_value > 0:
                            long_pos = abs(position_value)  # 多头持仓
                        else:
                            short_pos = abs(position_value)  # 空头持仓
                    break

            logger.debug(f"API持仓同步: {self.symbol} 多头={long_pos}, 空头={short_pos}")
            return long_pos, short_pos

        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            # 返回当前缓存的持仓数据
            return self.long_position, self.short_position

    def on_price_update(self, market_id: int, order_book: dict):
        """价格更新回调 (使用 SDK WebSocket 管理器)"""
        try:
            bids = order_book.get('bids', [])
            asks = order_book.get('asks', [])

            if bids and asks:
                self.best_bid_price = float(bids[0]['price'])
                self.best_ask_price = float(asks[0]['price'])
                old_price = self.latest_price
                self.latest_price = (self.best_bid_price + self.best_ask_price) / 2

                # 首次价格更新
                if old_price == 0 and self.latest_price > 0:
                    self.update_initial_quantities()

        except Exception as e:
            logger.error(f"价格更新处理失败: {e}")

    def update_initial_quantities(self):
        """更新初始数量 (对齐 Binance)"""
        if self.latest_price > 0:
            # 使用 SDK 工具计算数量
            quantity, is_valid, msg = self.market_manager.calculate_quantity_for_quote_amount(
                self.latest_price, self.initial_quantity, self.symbol
            )
            if is_valid:
                self.long_initial_quantity = quantity
                self.short_initial_quantity = quantity
                logger.info(f"更新数量: {quantity} {self.symbol} (${self.initial_quantity} USD)")

    def should_update_orders(self, new_price):
        """判断是否需要更新订单 (基于价格变动阈值)"""
        if self.last_order_price == 0:
            # 首次价格更新，必须更新订单
            logger.info(f"🎯 首次价格更新: ${new_price:.6f}")
            return True

        if new_price <= 0:
            # 无效价格，不更新
            return False

        # 计算价格变动百分比
        price_change_pct = abs(new_price - self.last_order_price) / self.last_order_price
        should_update = price_change_pct >= self.price_update_threshold

        if should_update:
            logger.info(f"💡 价格变动超过阈值: {price_change_pct:.4f} >= {self.price_update_threshold:.4f}")
            logger.info(f"📈 价格: ${self.last_order_price:.6f} → ${new_price:.6f}")
        else:
            logger.debug(f"⏸️ 价格变动未达阈值: {price_change_pct:.4f} < {self.price_update_threshold:.4f}")

        return should_update

    def update_last_order_price(self):
        """更新上次下单价格 (在实际下单后调用)"""
        self.last_order_price = self.latest_price
        logger.debug(f"更新订单基准价格: ${self.last_order_price:.6f}")

    def get_position_threshold(self):
        """
        动态获取持仓阈值 (基于账户总价值)

        Returns:
            float: 持仓阈值 (币种数量)
        """
        try:
            # 使用启动时获取的账户总价值
            account_value = self.total_asset_value

            # 计算持仓阈值对应的币种数量
            # 阈值 = 账户价值 * 比例 / 当前币价
            threshold_usd = account_value * POSITION_THRESHOLD_RATIO
            threshold_amount = threshold_usd / self.latest_price if self.latest_price > 0 else 1.0

            logger.debug(f"持仓阈值计算: 账户价值=${account_value:.2f}, 阈值=${threshold_usd:.2f}, {self.symbol}阈值={threshold_amount:.4f}")
            return threshold_amount

        except Exception as e:
            logger.error(f"计算持仓阈值失败: {e}")
            # 使用固定阈值作为后备方案
            fallback_usd = 1000.0 * POSITION_THRESHOLD_RATIO
            return fallback_usd / self.latest_price if self.latest_price > 0 else 1.0

    def get_take_profit_quantity(self, position, side):
        """调整止盈数量 (对齐 Binance)"""
        base_quantity = self.long_initial_quantity if side == 'long' else self.short_initial_quantity
        position_threshold = self.get_position_threshold()

        if position > position_threshold:
            return base_quantity * 2
        elif (side == 'long' and self.short_position >= position_threshold) or \
             (side == 'short' and self.long_position >= position_threshold):
            return base_quantity * 2
        else:
            return base_quantity

    async def place_order_safe(self, side: str, price: float, quantity: float, position_type: str = 'long'):
        """安全下单 (使用 SDK 工具)"""
        try:
            # 使用市场管理器格式化
            formatted_price = self.market_manager.format_price(price, self.symbol)
            is_valid, formatted_quantity, msg = self.market_manager.validate_order_amount(
                formatted_price, quantity, self.symbol
            )

            if not is_valid:
                logger.warning(f"订单验证失败: {msg}")
                return None

            if self.dry_run:
                logger.info(f"🔄 DRY RUN - {side.upper()}: {formatted_quantity} @ ${formatted_price:.6f}")
                return "dry_run_order_id"

            # 实际下单
            logger.info(f"📈 REAL - {side}: {formatted_quantity} {self.symbol} @ ${formatted_price:.6f}")

            if side == 'sell':
                formatted_quantity = -abs(formatted_quantity)

            result = await self.lighter.limit_order(
                ticker=self.symbol,
                amount=formatted_quantity,
                price=formatted_price,
                tif='GTC'
            )

            return str(int(time.time() * 1000)) if result else None

        except Exception as e:
            logger.error(f"下单失败: {e}")
            return None

    async def place_market_order(self, side: str, quantity: float, position_type: str = 'long'):
        """
        下市价单 (用于库存风险控制)

        Args:
            side: 'buy' 或 'sell'
            quantity: 数量
            position_type: 'long' 或 'short' (用于日志)
        """
        try:
            # 验证数量
            is_valid, formatted_quantity, msg = self.market_manager.validate_order_amount(
                self.latest_price, quantity, self.symbol
            )

            if not is_valid:
                logger.warning(f"市价单验证失败: {msg}")
                return None

            if self.dry_run:
                logger.info(f"🔄 DRY RUN - 市价{side.upper()}: {formatted_quantity} {self.symbol}")
                return "dry_run_market_order_id"

            logger.info(f"⚡ 市价{side.upper()}: {formatted_quantity} {self.symbol} (风控平仓)")

            if side == 'sell':
                formatted_quantity = -abs(formatted_quantity)

            # 使用市价单
            result = await self.lighter.market_order(
                ticker=self.symbol,
                amount=formatted_quantity
            )

            return str(int(time.time() * 1000)) if result else None

        except Exception as e:
            logger.error(f"市价单失败: {e}")
            return None

    async def initialize_long_orders(self):
        """初始化多头订单 (对齐 Binance)"""
        if time.time() - self.last_long_order_time < ORDER_FIRST_TIME:
            return

        # 撤销多头方向的订单 (对齐 Binance 参考策略)
        await self.batch_manager.cancel_orders_for_side_safe(self.symbol, 'long')

        # 下多头开仓单
        order_id = await self.place_order_safe('buy', self.best_bid_price, self.long_initial_quantity, 'long')
        if order_id:
            logger.info(f"✅ 多头开仓单已下达")
            self.last_long_order_time = time.time()

    async def initialize_short_orders(self):
        """初始化空头订单 (对齐 Binance)"""
        if time.time() - self.last_short_order_time < ORDER_FIRST_TIME:
            return

        # 撤销空头方向的订单 (对齐 Binance 参考策略)
        await self.batch_manager.cancel_orders_for_side_safe(self.symbol, 'short')

        # 下空头开仓单
        order_id = await self.place_order_safe('sell', self.best_ask_price, self.short_initial_quantity, 'short')
        if order_id:
            logger.info(f"✅ 空头开仓单已下达")
            self.last_short_order_time = time.time()

    async def place_long_orders(self, latest_price):
        """
        挂多头订单 (对齐 Binance 参考实现 line 644-667)
        """
        try:
            position_threshold = self.get_position_threshold()
            quantity = self.get_take_profit_quantity(self.long_position, 'long')

            # 检查持仓是否超过阈值 (对齐 Binance line 651-656)
            if self.long_position > position_threshold:
                logger.info(f"多头持仓过大 ({self.long_position})，进入装死模式")

                # 检查是否已有止盈单 (对齐 Binance: if self.sell_long_orders <= 0)
                tracker = self.order_manager.get_tracker(self.symbol)
                counts = tracker.get_order_counts()
                if counts['sell_orders'] <= 0:  # 没有多头止盈单时才下新单
                    # 装死模式：只下止盈单 (对齐 Binance)
                    if self.short_position > 0:
                        # 动态止盈比例计算 (对齐 Binance line 654)
                        r = float((self.long_position / self.short_position) / 100 + 1)
                        exit_price = self.latest_price * r
                        logger.info(f"🔄 多头装死止盈: 比例={r:.4f}")
                    else:
                        # 无对冲持仓时，固定2%止盈
                        exit_price = self.latest_price * 1.02
                        logger.info("🔄 多头装死止盈: 无对冲，固定2%")

                    await self.place_order_safe('sell', exit_price, quantity, 'long')
                    logger.info(f"✅ 多头装死止盈单 @ ${exit_price:.6f}")
                else:
                    logger.debug(f"多头装死模式：已有止盈单({counts['sell_orders']})，跳过")
            else:
                # 正常网格模式 (对齐 Binance line 658-664)
                logger.info(f"多头正常网格模式 (持仓={self.long_position})")

                # 撤销现有订单并重新下单
                await self.batch_manager.cancel_orders_for_side_safe(self.symbol, 'long')

                # 计算网格价格
                exit_price = self.latest_price * (1 + self.grid_spacing)
                entry_price = self.latest_price * (1 - self.grid_spacing)

                # 下止盈单和补仓单
                await self.place_order_safe('sell', exit_price, quantity, 'long')
                await self.place_order_safe('buy', entry_price, quantity, 'long')
                logger.info(f"✅ 多头网格: 止盈@${exit_price:.6f}, 补仓@${entry_price:.6f}")

        except Exception as e:
            logger.error(f"多头订单失败: {e}")

    async def place_short_orders(self, latest_price):
        """
        挂空头订单 (对齐 Binance 参考实现 line 669-693)
        """
        try:
            position_threshold = self.get_position_threshold()
            quantity = self.get_take_profit_quantity(self.short_position, 'short')

            # 检查持仓是否超过阈值 (对齐 Binance line 675-681)
            if self.short_position > position_threshold:
                logger.info(f"空头持仓过大 ({self.short_position})，进入装死模式")

                # 检查是否已有止盈单 (对齐 Binance: if self.buy_short_orders <= 0)
                tracker = self.order_manager.get_tracker(self.symbol)
                counts = tracker.get_order_counts()
                if counts['buy_orders'] <= 0:  # 没有空头止盈单时才下新单
                    # 装死模式：只下止盈单 (对齐 Binance)
                    if self.long_position > 0:
                        # 动态止盈比例计算 (对齐 Binance line 678)
                        r = float((self.short_position / self.long_position) / 100 + 1)
                        exit_price = self.latest_price / r  # 空头反向
                        logger.info(f"🔄 空头装死止盈: 比例={1/r:.4f}")
                    else:
                        # 无对冲持仓时，固定2%止盈
                        exit_price = self.latest_price * 0.98
                        logger.info("🔄 空头装死止盈: 无对冲，固定2%")

                    await self.place_order_safe('buy', exit_price, quantity, 'short')
                    logger.info(f"✅ 空头装死止盈单 @ ${exit_price:.6f}")
                else:
                    logger.debug(f"空头装死模式：已有止盈单({counts['buy_orders']})，跳过")
            else:
                # 正常网格模式 (对齐 Binance line 684-690)
                logger.info(f"空头正常网格模式 (持仓={self.short_position})")

                # 撤销现有订单并重新下单
                await self.batch_manager.cancel_orders_for_side_safe(self.symbol, 'short')

                # 计算网格价格
                exit_price = self.latest_price * (1 - self.grid_spacing)
                entry_price = self.latest_price * (1 + self.grid_spacing)

                # 下止盈单和补仓单
                await self.place_order_safe('buy', exit_price, quantity, 'short')
                await self.place_order_safe('sell', entry_price, quantity, 'short')
                logger.info(f"✅ 空头网格: 止盈@${exit_price:.6f}, 补仓@${entry_price:.6f}")

        except Exception as e:
            logger.error(f"空头订单失败: {e}")

    async def check_and_reduce_positions(self):
        """
        检查持仓并减少库存风险 (对齐 Binance 参考实现 line 732-754)
        """
        try:
            position_threshold = self.get_position_threshold()
            # 设置持仓阈值 (对齐 Binance local_position_threshold = POSITION_THRESHOLD * 0.8)
            local_threshold = position_threshold * INVENTORY_REDUCTION_RATIO
            reduce_quantity = position_threshold * 0.1  # 平仓数量

            # 双向持仓过大风险控制 (对齐 Binance line 741-753)
            if (self.long_position >= local_threshold and
                self.short_position >= local_threshold):

                logger.warning(f"⚠️ 双向持仓风险: 多头={self.long_position}, 空头={self.short_position}")
                logger.info(f"🔄 启动库存风险控制，阈值={local_threshold}, 平仓量={reduce_quantity}")

                if self.dry_run:
                    logger.info(f"🔄 DRY RUN - 双向市价平仓: {reduce_quantity}")
                    self.long_position = max(0, self.long_position - reduce_quantity)
                    self.short_position = max(0, self.short_position - reduce_quantity)
                    logger.info(f"✅ 模拟双向平仓完成，剩余: 多头={self.long_position}, 空头={self.short_position}")
                else:
                    # 实际执行市价平仓 (对齐 Binance)
                    logger.info("⚡ 实盘模式：执行双向市价平仓")

                    # 平多头持仓 (卖出)
                    if self.long_position > 0:
                        sell_result = await self.place_market_order('sell', reduce_quantity, 'long')
                        if sell_result:
                            logger.info(f"✅ 多头平仓成功: {reduce_quantity}")
                            self.long_position = max(0, self.long_position - reduce_quantity)
                        else:
                            logger.error("❌ 多头平仓失败")

                    # 平空头持仓 (买入)
                    if self.short_position > 0:
                        buy_result = await self.place_market_order('buy', reduce_quantity, 'short')
                        if buy_result:
                            logger.info(f"✅ 空头平仓成功: {reduce_quantity}")
                            self.short_position = max(0, self.short_position - reduce_quantity)
                        else:
                            logger.error("❌ 空头平仓失败")

                    logger.info(f"📊 平仓后持仓: 多头={self.long_position}, 空头={self.short_position}")

        except Exception as e:
            logger.error(f"持仓风险控制失败: {e}")

    async def adjust_grid_strategy(self):
        """网格策略主逻辑 (对齐 Binance 参考实现)"""
        try:
            # 检查价格是否有效
            if self.latest_price <= 0:
                logger.debug("等待有效价格...")
                return

            # 检查是否需要更新订单 (基于价格阈值)
            if not self.should_update_orders(self.latest_price):
                return

            logger.debug(f"价格变动达到阈值，执行网格调整 (${self.latest_price:.6f})")

            # ====== 双向持仓风控检查 (对齐 Binance line 776) ======
            await self.check_and_reduce_positions()

            # ====== 多头策略逻辑 (对齐 Binance line 780-793) ======
            if self.long_position == 0:
                logger.info("🟢 初始化多头订单")
                await self.initialize_long_orders()
            else:
                logger.debug(f"🔄 调整多头网格 (持仓={self.long_position})")
                await self.place_long_orders(self.latest_price)

            # ====== 空头策略逻辑 (对齐 Binance line 795-808) ======
            if self.short_position == 0:
                logger.info("🔴 初始化空头订单")
                await self.initialize_short_orders()
            else:
                logger.debug(f"🔄 调整空头网格 (持仓={self.short_position})")
                await self.place_short_orders(self.latest_price)

            # ====== 统一更新价格基准 (对齐 Binance 逻辑) ======
            self.update_last_order_price()

        except Exception as e:
            logger.error(f"网格策略执行失败: {e}")

    async def graceful_shutdown(self):
        """优雅关闭 (对齐 Binance)"""
        logger.info("🛑 开始优雅关闭...")
        self.shutdown_requested = True

        try:
            # 使用批量管理器撤销所有订单
            result = await self.batch_manager.cancel_all_orders_safe()
            if result['success']:
                logger.info("✅ 所有订单已撤销")
            else:
                logger.warning(f"⚠️ 撤销订单可能有问题: {result.get('error', 'Unknown')}")

            logger.info("💰 持仓保留 (对齐 Binance 参考)")
        except Exception as e:
            logger.error(f"关闭失败: {e}")

    async def run(self):
        """主运行循环"""
        mode_str = "DRY RUN" if self.dry_run else "LIVE TRADING"
        logger.info(f"🚀 启动简化网格机器人 ({mode_str})")

        # 启动价格 WebSocket
        price_task = asyncio.create_task(self.price_ws.initialize_and_run())

        # 等待价格数据
        logger.info("等待价格数据...")
        for _ in range(20):  # 10秒超时
            if self.latest_price > 0:
                break
            await asyncio.sleep(0.5)

        if self.latest_price == 0:
            logger.error("❌ 未能获取价格数据")
            price_task.cancel()
            return

        logger.info(f"✅ 价格: ${self.latest_price:.6f}")

        # 主循环
        current_time = time.time()  # 获取当前时间
        last_stats_time = current_time  # 初始化为当前时间，避免启动时立即触发
        last_position_sync_time = current_time  # 初始化为当前时间，避免启动时立即触发
        last_order_sync_time = current_time  # 初始化为当前时间，避免启动时立即触发
        loop_count = 0

        logger.info("📊 启动完成，开始运行策略")

        try:
            while not self.shutdown_requested:
                loop_count += 1
                current_time = time.time()

                # 显示状态 (节流日志)
                if loop_count % LOG_THROTTLE_FACTOR == 1:
                    logger.info(f"价格: ${self.latest_price:.6f}, 持仓: 多头={self.long_position}, 空头={self.short_position}")

                # 智能订单同步 (降低频率)
                if current_time - last_order_sync_time > ORDER_SYNC_INTERVAL:
                    await self.order_manager.sync_orders_from_api(self.symbol)
                    tracker = self.order_manager.get_tracker(self.symbol)
                    counts = tracker.get_order_counts()
                    if loop_count % LOG_THROTTLE_FACTOR == 1:  # 节流日志
                        logger.info(f"订单: {counts['total_active']} 个活跃")
                    last_order_sync_time = current_time

                # 智能持仓同步 (大幅降低频率 + 条件触发)
                should_sync_position = (
                    current_time - last_position_sync_time > POSITION_SYNC_INTERVAL or
                    # 在特殊情况下强制同步持仓：
                    (current_time - last_position_sync_time > 60 and (  # 至少60秒后才考虑条件同步
                        self.long_position == 0 or  # 无持仓时需要及时检测新开仓
                        self.short_position == 0 or
                        abs(self.long_position) > self.get_position_threshold() * 0.5 or  # 持仓较大时更频繁检查
                        abs(self.short_position) > self.get_position_threshold() * 0.5
                    ))
                )

                if should_sync_position:
                    logger.debug("📊 同步持仓状态...")
                    old_long, old_short = self.long_position, self.short_position
                    self.long_position, self.short_position = await self.get_positions()

                    if old_long != self.long_position or old_short != self.short_position:
                        logger.info(f"🔄 持仓更新: 多头 {old_long}→{self.long_position}, 空头 {old_short}→{self.short_position}")

                    last_position_sync_time = current_time

                # 定期显示官方统计信息
                if current_time - last_stats_time > STATS_DISPLAY_INTERVAL:
                    stats = await self.get_account_stats()
                    if stats:
                        self.print_account_stats(stats)
                    last_stats_time = current_time

                # 执行策略
                await self.adjust_grid_strategy()

                # 休眠 (可响应中断)
                for _ in range(10):
                    if self.shutdown_requested:
                        break
                    await asyncio.sleep(0.5)

        except KeyboardInterrupt:
            self.shutdown_requested = True
        finally:
            await self.graceful_shutdown()

        # 清理
        price_task.cancel()
        if self.price_ws:
            self.price_ws.shutdown()
        if self.lighter:
            await self.lighter.cleanup()

        logger.info("✅ 网格机器人停止")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='简化 Lighter 网格机器人')
    parser.add_argument('--dry-run', action='store_true', help='模拟模式')
    parser.add_argument('--symbol', default=COIN_NAME, help='交易符号')
    parser.add_argument('--max-orders', type=int, default=MAX_ORDERS_PER_SIDE,
                        help=f'单边最大订单数量 (默认: {MAX_ORDERS_PER_SIDE})')
    parser.add_argument('--grid-spacing', type=float, default=GRID_SPACING,
                        help=f'网格间距百分比 (默认: {GRID_SPACING:.4f} = {GRID_SPACING*100:.2f}%%)')
    parser.add_argument('--order-amount', type=float, default=INITIAL_QUANTITY,
                        help=f'每单金额 USD (默认: ${INITIAL_QUANTITY})')
    parser.add_argument('--price-threshold', type=float, default=PRICE_UPDATE_THRESHOLD,
                        help=f'价格变动阈值 (默认: {PRICE_UPDATE_THRESHOLD:.4f} = {PRICE_UPDATE_THRESHOLD*100:.2f}%%)')
    args = parser.parse_args()

    # 创建机器人
    bot = GridBot(
        dry_run=args.dry_run,
        max_orders_per_side=args.max_orders,
        grid_spacing=args.grid_spacing,
        order_amount=args.order_amount,
        price_threshold=args.price_threshold
    )
    bot.symbol = args.symbol

    # 输出当前配置
    logger.info(f"🚀 启动参数配置:")
    logger.info(f"   交易对: {args.symbol}")
    logger.info(f"   模式: {'模拟交易' if args.dry_run else '实盘交易'}")
    logger.info(f"   单边最大订单数: {args.max_orders}")
    logger.info(f"   网格间距: {args.grid_spacing:.4f} ({args.grid_spacing*100:.2f}%)")
    logger.info(f"   每单金额: ${args.order_amount}")
    logger.info(f"   价格变动阈值: {args.price_threshold:.4f} ({args.price_threshold*100:.2f}%)")
    logger.info(f"   杠杆: {LEVERAGE}x")
    logger.info(f"   锁仓阈值: 账户价值的{POSITION_THRESHOLD_RATIO*100:.0f}%")

    if not args.dry_run:
        logger.warning("⚠️ 实盘交易模式启动!")

    # 信号处理 (对齐 Binance)
    def signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，关闭中...")
        bot.shutdown_requested = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await bot.setup()
        await bot.run()
    except Exception as e:
        logger.error(f"机器人失败: {e}")
        await bot.graceful_shutdown()
        raise


if __name__ == "__main__":
    print("🤖 简化 Lighter 网格机器人")
    print(f"📊 使用 pylighter SDK 工具，代码简洁但功能完整")
    print("=" * 50)
    asyncio.run(main())
