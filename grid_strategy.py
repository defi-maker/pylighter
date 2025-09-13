"""
简化网格交易策略 - 对齐 Binance 参考实现
Simplified Grid Trading Strategy - Aligned with Binance Reference Implementation

参考原始策略：/home/wayhome/stuff/trading/buou_grid/grid_BN_XRP.py
使用 pylighter SDK 工具简化代码，保持核心功能完整

主要特点：
- 完全对齐 Binance 参考实现的结构和方法名
- 使用 SDK 工具处理 WebSocket、订单管理和市场数据
- 代码简洁但功能完整，专注于交易逻辑
- 优雅的启动检查和关闭处理
"""

import os
import asyncio
import logging
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

# 加载环境变量
load_dotenv()
os.makedirs("log", exist_ok=True)

# ==================== 配置 ====================
COIN_NAME = "TON"
GRID_SPACING = 0.0003         # 0.03% 超高频网格 (利用零手续费优势)
INITIAL_QUANTITY = 15.0       # 每单 $15 USD (提高单次收益)
LEVERAGE = 8                  # 8倍杠杆 (零费率下适度提高)
POSITION_THRESHOLD = 300      # 锁仓阈值 (提高资金效率)
ORDER_FIRST_TIME = 5          # 首单间隔时间 (提高响应速度)

# 新增优化参数
MAX_ORDERS_PER_SIDE = 15      # 单边最大订单数
ORDER_REFRESH_INTERVAL = 30   # 订单刷新间隔(秒)
PRICE_UPDATE_THRESHOLD = 0.0001  # 价格变动阈值触发订单调整

# ==================== 日志配置 ====================
script_name = os.path.splitext(os.path.basename(__file__))[0]
logging.basicConfig(
    level=logging.INFO,  # 根 logger 设置为 INFO，过滤掉所有 DEBUG 信息
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"log/{script_name}.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger()
logger.setLevel(logging.INFO)


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

        # 4. 启动状态分析 (对齐 Binance)
        await self.analyze_startup_state()

        # 5. 初始化价格 WebSocket
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
        """启动状态分析 (对齐 Binance)"""
        logger.info("📊 分析启动状态...")

        # 检查现有持仓
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
        """获取持仓 (简化版)"""
        if self.dry_run:
            return self.long_position, self.short_position
        # 实际实现中调用 API 获取持仓
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

    def get_take_profit_quantity(self, position, side):
        """调整止盈数量 (对齐 Binance)"""
        base_quantity = self.long_initial_quantity if side == 'long' else self.short_initial_quantity

        if position > POSITION_THRESHOLD:
            return base_quantity * 2
        elif (side == 'long' and self.short_position >= POSITION_THRESHOLD) or \
             (side == 'short' and self.long_position >= POSITION_THRESHOLD):
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

    async def place_grid_orders(self, side: str):
        """下网格订单 (简化版)"""
        try:
            position = self.long_position if side == 'long' else self.short_position
            quantity = self.get_take_profit_quantity(position, side)

            if position > POSITION_THRESHOLD:
                # 持仓过大，只下止盈单
                logger.info(f"{side} 持仓过大 ({position})，只下止盈单")
                if side == 'long':
                    exit_price = self.latest_price * 1.01  # 1% 止盈
                    await self.place_order_safe('sell', exit_price, quantity, 'long')
                else:
                    exit_price = self.latest_price * 0.99  # 1% 止盈
                    await self.place_order_safe('buy', exit_price, quantity, 'short')
            else:
                # 正常网格
                if side == 'long':
                    # 止盈单 + 补仓单
                    upper_price = self.latest_price * (1 + self.grid_spacing)
                    lower_price = self.latest_price * (1 - self.grid_spacing)
                    await self.place_order_safe('sell', upper_price, quantity, 'long')
                    await self.place_order_safe('buy', lower_price, quantity, 'long')
                else:
                    # 止盈单 + 补仓单
                    lower_price = self.latest_price * (1 - self.grid_spacing)
                    upper_price = self.latest_price * (1 + self.grid_spacing)
                    await self.place_order_safe('buy', lower_price, quantity, 'short')
                    await self.place_order_safe('sell', upper_price, quantity, 'short')

                logger.info(f"✅ {side} 网格订单已下达")

        except Exception as e:
            logger.error(f"{side} 网格订单失败: {e}")

    async def adjust_grid_strategy(self):
        """网格策略主逻辑 (带价格阈值优化)"""
        try:
            # 检查价格是否有效
            if self.latest_price <= 0:
                logger.debug("等待有效价格...")
                return

            # 检查是否需要更新订单 (基于价格阈值)
            if not self.should_update_orders(self.latest_price):
                # 价格变动未达到阈值，跳过此次更新
                return

            logger.debug(f"价格变动达到阈值，执行网格调整 (${self.latest_price:.6f})")

            # 多头逻辑
            if self.long_position == 0:
                logger.info("初始化多头订单")
                await self.initialize_long_orders()
                self.update_last_order_price()  # 更新基准价格
            else:
                await self.place_grid_orders('long')
                self.update_last_order_price()  # 更新基准价格

            # 空头逻辑
            if self.short_position == 0:
                logger.info("初始化空头订单")
                await self.initialize_short_orders()
                # 不重复更新，已在上面更新
            else:
                await self.place_grid_orders('short')
                # 不重复更新，已在上面更新

        except Exception as e:
            logger.error(f"网格策略失败: {e}")

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
        stats_print_interval = 300  # 每5分钟显示一次统计
        last_stats_time = 0

        try:
            while not self.shutdown_requested:
                # 显示状态
                logger.info(f"价格: ${self.latest_price:.6f}, 持仓: 多头={self.long_position}, 空头={self.short_position}")

                # 定期同步 (简化)
                await self.order_manager.sync_orders_from_api(self.symbol)
                tracker = self.order_manager.get_tracker(self.symbol)
                counts = tracker.get_order_counts()
                logger.info(f"订单: {counts['total_active']} 个活跃")

                # 定期显示官方统计信息
                current_time = time.time()
                if current_time - last_stats_time > stats_print_interval:
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
    logger.info(f"   锁仓阈值: {POSITION_THRESHOLD}")

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
