"""
Cross-Exchange Arbitrage Strategy using Trading Velocity Acceleration Factor
Binance -> Lighter Protocol arbitrage with 0 fee advantage

Strategy Logic:
1. Monitor Binance orderbook changes and trades velocity
2. Calculate trading velocity acceleration factor (成交笔数变化率)
3. Detect sudden increases in trading velocity indicating potential volatility
4. Execute trades on Lighter with 0 fees for profit from small price movements
5. Maintain maker/taker ratio to avoid detection
"""

import os
import asyncio
import logging
import time
import math
import json
import argparse
import signal
import websockets
import ccxt
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from pylighter.client import Lighter

# Load environment variables
load_dotenv()

# Create log directory
os.makedirs("log", exist_ok=True)

# ==================== Configuration ====================
COIN_NAME = "TON"  # Trading symbol
BINANCE_SYMBOL = "TONUSDT"  # Binance symbol format
LIGHTER_SYMBOL = "TON"  # Lighter symbol format
VELOCITY_WINDOW = 3  # Seconds for velocity calculation (3s, 5s as mentioned)
VELOCITY_THRESHOLD = 2.0  # Multiplier for velocity spike detection
VOLUME_THRESHOLD = 1.5  # Volume surge multiplier
ORDER_AMOUNT_USD = 10.0  # Order amount in USD
LEVERAGE = 5  # Leverage for trading
MAKER_RATIO = 0.3  # 30% maker orders to avoid detection
MAX_POSITIONS = 2  # Maximum concurrent positions
MAX_DAILY_TRADES = 100  # Maximum daily trades to limits exposure
MIN_PROFIT_THRESHOLD = 0.001  # 0.1% minimum profit threshold

# ==================== Logging Configuration ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("log/cross_exchange_arbitrage.log", mode='a'),
        logging.StreamHandler(),
    ],
    force=True
)
logger = logging.getLogger()

class CrossExchangeArbitrageBot:
    """Cross-exchange arbitrage bot using trading velocity acceleration factor"""
    
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        
        # Exchange clients
        self.binance = None
        self.lighter = None
        
        # WebSocket connections
        self.binance_ws = None
        self.lighter_ws = None
        
        # Market data
        self.binance_price = 0
        self.lighter_price = 0
        self.binance_bid = 0
        self.binance_ask = 0
        self.lighter_bid = 0
        self.lighter_ask = 0
        
        # Trading velocity tracking
        self.trade_count_history = []  # List of (timestamp, trade_count) tuples
        self.volume_history = []  # List of (timestamp, volume) tuples
        self.current_velocity = 0
        self.velocity_acceleration = 0
        self.volume_surge = 0
        
        # Trading state
        self.positions = []  # List of active positions
        
        # Mock Lighter client methods for dry-run compatibility
        self.add_mock_methods()
        self.daily_trade_count = 0
        self.maker_order_count = 0
        self.taker_order_count = 0
        self.last_signal_time = 0
        
        # Order management
        self.active_orders = {}  # Track active orders with timestamps
        self.order_timeout = 300  # 5 minutes for order timeout
        self.max_orders_per_side = 4  # Maximum orders per side (buy/sell)
        
        # Position management
        self.max_position_size = ORDER_AMOUNT_USD * LEVERAGE
        self.position_threshold = 100  # Position size threshold for risk management
        self.inventory_threshold = 80  # Inventory risk threshold
        self.daily_pnl = 0
        self.max_daily_loss = -50  # Maximum daily loss in USD
        
        # Enhanced risk management
        self.min_profit_threshold = 0.001  # 0.1% minimum profit
        self.max_concurrent_signals = 3  # Maximum concurrent trading signals
        self.signal_cooldown = 10  # Seconds between signals
        self.position_sizing_multiplier = 1.0  # Dynamic position sizing
        
        # Shutdown control
        self.shutdown_requested = False
        
    def add_mock_methods(self):
        """Add mock methods to Lighter client for compatibility"""
        # This will be called after lighter client is initialized
        pass
        
    async def add_compatibility_methods(self):
        """Add compatibility methods to Lighter client"""
        # Add get_ticker method
        async def get_ticker(symbol):
            orderbook = await self.lighter.orderbook_details(symbol)
            if orderbook:
                return {
                    'last_price': orderbook.get('mark_price', 0),
                    'bid': orderbook.get('best_bid', 0),
                    'ask': orderbook.get('best_ask', 0)
                }
            return None
            
        # Add get_positions method
        async def get_positions():
            pnl_data = await self.lighter.pnl()
            if pnl_data and 'positions' in pnl_data:
                return pnl_data['positions']
            return []
            
        # Add cancel_all_orders method
        async def cancel_all_orders():
            # Try to cancel all orders using the available methods
            try:
                # Get active orders and cancel them individually
                orders = await self.lighter.account_active_orders(LIGHTER_SYMBOL)
                cancelled_orders = []
                for order in orders:
                    result = await self.lighter.cancel_order(LIGHTER_SYMBOL, order['order_id'])
                    if result:
                        cancelled_orders.append(order['order_id'])
                return cancelled_orders
            except Exception as e:
                logger.error(f"Error cancelling all orders: {e}")
                return []
        
        # Add methods to the Lighter client
        self.lighter.get_ticker = get_ticker
        self.lighter.get_positions = get_positions
        self.lighter.cancel_all_orders = cancel_all_orders
        
    async def setup(self):
        """Initialize exchange connections"""
        logger.info("🚀 Setting up cross-exchange arbitrage bot...")
        
        # Initialize Binance
        await self.setup_binance()
        
        # Initialize Lighter
        await self.setup_lighter()
        
        logger.info("✅ Setup complete")
        
    async def setup_binance(self):
        """Initialize Binance connection"""
        try:
            # Initialize CCXT Binance client
            self.binance = ccxt.binance({
                'apiKey': os.getenv('BINANCE_API_KEY'),
                'secret': os.getenv('BINANCE_API_SECRET'),
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',
                },
            })
            self.binance.load_markets()
            
            logger.info("✅ Binance client initialized")
            
            # Get market info
            market = self.binance.market(BINANCE_SYMBOL)
            self.binance_precision = market['precision']['price']
            self.binance_amount_precision = market['precision']['amount']
            self.binance_min_amount = market['limits']['amount']['min']
            
            logger.info(f"Binance market: {BINANCE_SYMBOL}, Price precision: {self.binance_precision}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Binance: {e}")
            raise
            
    async def setup_lighter(self):
        """Initialize Lighter connection"""
        try:
            api_key = os.getenv("LIGHTER_KEY")
            api_secret = os.getenv("LIGHTER_SECRET")
            
            if not api_key or not api_secret:
                raise ValueError("Please set LIGHTER_KEY and LIGHTER_SECRET environment variables")
            
            self.lighter = Lighter(key=api_key, secret=api_secret)
            await self.lighter.init_client()
            
            # Add compatibility methods to Lighter client
            await self.add_compatibility_methods()
            
            logger.info("✅ Lighter client initialized")
            
            # Get market constraints
            constraints = await self.lighter.get_market_constraints(LIGHTER_SYMBOL)
            self.lighter_min_quote = constraints['min_quote_amount']
            self.lighter_price_precision = constraints['price_precision']
            self.lighter_amount_precision = constraints['amount_precision']
            
            logger.info(f"Lighter market: {LIGHTER_SYMBOL}, Min quote: ${self.lighter_min_quote}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Lighter: {e}")
            raise
            
    async def setup_binance_websocket(self):
        """Setup Binance WebSocket for orderbook and trades"""
        try:
            logger.info("🔌 Setting up Binance WebSocket...")
            
            # WebSocket URL for Binance Futures
            ws_url = "wss://fstream.binance.com/ws"
            
            async def connect_binance_ws():
                while not self.shutdown_requested:
                    try:
                        async with websockets.connect(ws_url) as websocket:
                            # Subscribe to orderbook and trades
                            await self.subscribe_binance_data(websocket)
                            
                            # Listen for messages
                            async for message in websocket:
                                if self.shutdown_requested:
                                    break
                                    
                                data = json.loads(message)
                                await self.handle_binance_message(data)
                                
                    except Exception as e:
                        logger.error(f"Binance WebSocket error: {e}")
                        await asyncio.sleep(5)
                        
            # Start WebSocket connection
            asyncio.create_task(connect_binance_ws())
            logger.info("✅ Binance WebSocket setup complete")
            
        except Exception as e:
            logger.error(f"❌ Failed to setup Binance WebSocket: {e}")
            raise
            
    async def subscribe_binance_data(self, websocket):
        """Subscribe to Binance orderbook and trades"""
        # Subscribe to orderbook ticker
        book_ticker_msg = {
            "method": "SUBSCRIBE",
            "params": [f"{BINANCE_SYMBOL.lower()}@bookTicker"],
            "id": 1
        }
        await websocket.send(json.dumps(book_ticker_msg))
        
        # Subscribe to trades
        trades_msg = {
            "method": "SUBSCRIBE", 
            "params": [f"{BINANCE_SYMBOL.lower()}@trade"],
            "id": 2
        }
        await websocket.send(json.dumps(trades_msg))
        
        logger.info(f"Subscribed to {BINANCE_SYMBOL} orderbook and trades")
        
    async def handle_binance_message(self, data):
        """Handle incoming Binance WebSocket messages"""
        try:
            if data.get("e") == "bookTicker":
                await self.handle_binance_orderbook(data)
            elif data.get("e") == "trade":
                await self.handle_binance_trade(data)
        except Exception as e:
            logger.error(f"Error handling Binance message: {e}")
            
    async def handle_binance_orderbook(self, data):
        """Handle Binance orderbook updates"""
        try:
            self.binance_bid = float(data.get("b", 0))
            self.binance_ask = float(data.get("a", 0))
            self.binance_price = (self.binance_bid + self.binance_ask) / 2
            
            # Update price spread analysis
            await self.analyze_price_spread()
            
        except Exception as e:
            logger.error(f"Error processing Binance orderbook: {e}")
            
    async def handle_binance_trade(self, data):
        """Handle Binance trade updates for velocity calculation"""
        try:
            current_time = time.time()
            trade_quantity = float(data.get("q", 0))
            
            # Update trade count history
            self.trade_count_history.append((current_time, 1))
            self.volume_history.append((current_time, trade_quantity))
            
            # Clean old data (keep only VELOCITY_WINDOW seconds)
            cutoff_time = current_time - VELOCITY_WINDOW
            self.trade_count_history = [(t, c) for t, c in self.trade_count_history if t > cutoff_time]
            self.volume_history = [(t, v) for t, v in self.volume_history if t > cutoff_time]
            
            # Calculate velocity acceleration
            await self.calculate_velocity_acceleration()
            
        except Exception as e:
            logger.error(f"Error processing Binance trade: {e}")
            
    async def calculate_velocity_acceleration(self):
        """Calculate trading velocity acceleration factor"""
        try:
            current_time = time.time()
            
            # Calculate current velocity (trades per second in the window)
            recent_trades = sum(count for _, count in self.trade_count_history)
            self.current_velocity = recent_trades / VELOCITY_WINDOW if VELOCITY_WINDOW > 0 else 0
            
            # Calculate previous velocity (for acceleration)
            prev_window_start = current_time - VELOCITY_WINDOW * 2
            prev_window_end = current_time - VELOCITY_WINDOW
            
            prev_trades = sum(count for t, count in self.trade_count_history 
                            if prev_window_start <= t <= prev_window_end)
            prev_velocity = prev_trades / VELOCITY_WINDOW if VELOCITY_WINDOW > 0 else 0
            
            # Calculate acceleration factor
            if prev_velocity > 0:
                self.velocity_acceleration = self.current_velocity / prev_velocity
            else:
                self.velocity_acceleration = self.current_velocity * 10  # High value if coming from zero
                
            # Calculate volume surge
            recent_volume = sum(volume for _, volume in self.volume_history)
            prev_volume = sum(volume for t, volume in self.volume_history 
                            if prev_window_start <= t <= prev_window_end)
            
            if prev_volume > 0:
                self.volume_surge = recent_volume / prev_volume
            else:
                self.volume_surge = recent_volume * 10 if recent_volume > 0 else 0
                
            # Log significant velocity changes
            if self.velocity_acceleration > VELOCITY_THRESHOLD:
                logger.info(f"🚀 Velocity spike detected! Acceleration: {self.velocity_acceleration:.2f}x, Current: {self.current_velocity:.2f} trades/sec")
                
            # Check for trading signals
            await self.check_trading_signals()
            
        except Exception as e:
            logger.error(f"Error calculating velocity acceleration: {e}")
            
    async def analyze_price_spread(self):
        """Analyze price spread between Binance and Lighter"""
        try:
            if self.binance_price > 0 and self.lighter_price > 0:
                spread = (self.lighter_price - self.binance_price) / self.binance_price
                
                # Log significant spreads
                if abs(spread) > 0.001:  # 0.1% spread
                    logger.debug(f"Price spread: {spread*100:.3f}% (Binance: ${self.binance_price:.6f}, Lighter: ${self.lighter_price:.6f})")
                    
        except Exception as e:
            logger.error(f"Error analyzing price spread: {e}")
            
    async def check_trading_signals(self):
        """Check for trading signals based on velocity acceleration with enhanced filtering"""
        try:
            current_time = time.time()
            
            # Prevent signal spam
            if current_time - self.last_signal_time < self.signal_cooldown:
                return
                
            # Enhanced signal conditions
            velocity_signal = self.velocity_acceleration > VELOCITY_THRESHOLD
            volume_signal = self.volume_surge > VOLUME_THRESHOLD
            position_limit = len(self.positions) < MAX_POSITIONS
            daily_limit = self.daily_trade_count < MAX_DAILY_TRADES
            order_limit = len(self.active_orders) < self.max_orders_per_side * 2
            
            # Additional risk filters
            pnl_limit = self.daily_pnl > self.max_daily_loss
            inventory_ok = self.position_sizing_multiplier > 0.5
            
            # Market condition check
            spread_ok = abs(self.lighter_price - self.binance_price) / self.binance_price < 0.01  # 1% max spread
            
            # Generate trading signal only if all conditions are met
            if (velocity_signal and volume_signal and position_limit and 
                daily_limit and order_limit and pnl_limit and inventory_ok and spread_ok):
                
                # Signal strength calculation
                signal_strength = self.calculate_signal_strength()
                
                if signal_strength > 0.5:  # Minimum signal strength
                    logger.info(f"🎯 TRADING SIGNAL: Velocity={self.velocity_acceleration:.2f}x, Volume={self.volume_surge:.2f}x")
                    logger.info(f"📊 Signal Strength: {signal_strength:.2f}, Spread: {abs(self.lighter_price - self.binance_price)/self.binance_price*100:.3f}%")
                    await self.execute_trading_signal()
                    self.last_signal_time = current_time
                else:
                    logger.debug(f"Signal strength ({signal_strength:.2f}) below threshold, skipping")
            else:
                # Log why signal was rejected
                if not velocity_signal:
                    logger.debug("Signal rejected: velocity below threshold")
                elif not volume_signal:
                    logger.debug("Signal rejected: volume below threshold")
                elif not position_limit:
                    logger.debug("Signal rejected: position limit reached")
                elif not daily_limit:
                    logger.debug("Signal rejected: daily trade limit reached")
                elif not order_limit:
                    logger.debug("Signal rejected: order limit reached")
                elif not pnl_limit:
                    logger.debug("Signal rejected: daily loss limit reached")
                elif not inventory_ok:
                    logger.debug("Signal rejected: inventory risk too high")
                elif not spread_ok:
                    logger.debug("Signal rejected: spread too wide")
                
        except Exception as e:
            logger.error(f"Error checking trading signals: {e}")
    
    def calculate_signal_strength(self):
        """Calculate signal strength based on multiple factors"""
        try:
            # Base strength from velocity acceleration
            velocity_strength = min(self.velocity_acceleration / VELOCITY_THRESHOLD, 3.0) / 3.0
            
            # Volume strength
            volume_strength = min(self.volume_surge / VOLUME_THRESHOLD, 3.0) / 3.0
            
            # Market spread strength (tighter spreads are better)
            if self.binance_price > 0 and self.lighter_price > 0:
                spread = abs(self.lighter_price - self.binance_price) / self.binance_price
                spread_strength = max(0, 1.0 - spread * 100)  # Convert percentage to strength
            else:
                spread_strength = 0.5
            
            # Order book depth strength (simplified)
            if self.binance_bid > 0 and self.binance_ask > 0:
                spread_bid_ask = (self.binance_ask - self.binance_bid) / self.binance_bid
                depth_strength = max(0, 1.0 - spread_bid_ask * 1000)  # Tighter spreads = higher strength
            else:
                depth_strength = 0.5
            
            # Weighted average
            signal_strength = (
                velocity_strength * 0.4 +
                volume_strength * 0.3 +
                spread_strength * 0.2 +
                depth_strength * 0.1
            )
            
            return min(1.0, max(0.0, signal_strength))
            
        except Exception as e:
            logger.error(f"Error calculating signal strength: {e}")
            return 0.5
            
    async def execute_trading_signal(self):
        """Execute trading signal on Lighter"""
        try:
            # Determine order type based on maker/taker ratio
            use_maker_order = (self.maker_order_count / max(1, self.maker_order_count + self.taker_order_count)) < MAKER_RATIO
            
            if use_maker_order:
                await self.place_maker_order()
            else:
                await self.place_taker_order()
                
        except Exception as e:
            logger.error(f"Error executing trading signal: {e}")
            
    async def place_maker_order(self):
        """Place a maker order on Lighter with enhanced order management"""
        try:
            # Check order limits
            if len(self.active_orders) >= self.max_orders_per_side * 2:
                logger.warning(f"Maximum orders ({self.max_orders_per_side * 2}) reached, skipping order")
                return
                
            # Calculate order price (slightly away from current price for maker status)
            if self.lighter_price > 0:
                # Place limit order slightly below/above current price
                price_adjustment = 0.0005  # 0.05% adjustment
                
                # Determine direction based on velocity trend
                if self.velocity_acceleration > 3.0:  # Strong acceleration
                    # Expect price to increase, place buy order
                    order_price = self.lighter_price * (1 - price_adjustment)
                    side = 'buy'
                else:
                    # Moderate acceleration, place sell order
                    order_price = self.lighter_price * (1 + price_adjustment)
                    side = 'sell'
                    
                # Apply dynamic position sizing
                order_amount = ORDER_AMOUNT_USD * self.position_sizing_multiplier
                order_quantity = order_amount / order_price
                
                # Check minimum profit threshold
                expected_profit = self.calculate_expected_profit(side, order_price, order_quantity)
                if expected_profit < self.min_profit_threshold:
                    logger.debug(f"Expected profit ({expected_profit:.4f}) below threshold, skipping order")
                    return
                
                logger.info(f"📊 Placing maker {side} order: {order_quantity:.6f} @ ${order_price:.6f}")
                
                if not self.dry_run:
                    # Execute real order
                    result = await self.lighter.limit_order(
                        ticker=LIGHTER_SYMBOL,
                        amount=order_quantity if side == 'buy' else -order_quantity,
                        price=order_price,
                        tif='GTC'
                    )
                    
                    if result:
                        # Track order with timestamp
                        order_id = result.get('order_id', str(time.time()))
                        self.active_orders[order_id] = {
                            'side': side,
                            'price': order_price,
                            'quantity': order_quantity,
                            'timestamp': time.time(),
                            'type': 'maker'
                        }
                        
                        self.maker_order_count += 1
                        self.daily_trade_count += 1
                        logger.info(f"✅ Maker order placed successfully (ID: {order_id})")
                    else:
                        logger.error(f"❌ Failed to place maker order")
                else:
                    # Simulate order tracking in dry run
                    order_id = f"dry_{time.time()}"
                    self.active_orders[order_id] = {
                        'side': side,
                        'price': order_price,
                        'quantity': order_quantity,
                        'timestamp': time.time(),
                        'type': 'maker'
                    }
                    
                    self.maker_order_count += 1
                    self.daily_trade_count += 1
                    logger.info(f"🔄 DRY RUN: Maker order would be placed (ID: {order_id})")
                    
        except Exception as e:
            logger.error(f"Error placing maker order: {e}")
    
    def calculate_expected_profit(self, side, price, quantity):
        """Calculate expected profit based on price spread and fees"""
        try:
            # Simple profit calculation based on current spread
            if side == 'buy':
                # Expecting price to rise
                expected_exit_price = price * 1.001  # 0.1% profit target
                profit = (expected_exit_price - price) * quantity
            else:
                # Expecting price to fall
                expected_exit_price = price * 0.999  # 0.1% profit target
                profit = (price - expected_exit_price) * quantity
            
            return profit / (price * quantity)  # Return as percentage
        except Exception as e:
            logger.error(f"Error calculating expected profit: {e}")
            return 0
            
    async def place_taker_order(self):
        """Place a taker order on Lighter with enhanced order management"""
        try:
            # Check order limits
            if len(self.active_orders) >= self.max_orders_per_side * 2:
                logger.warning(f"Maximum orders ({self.max_orders_per_side * 2}) reached, skipping order")
                return
                
            if self.lighter_price > 0:
                # Apply dynamic position sizing
                order_amount = ORDER_AMOUNT_USD * self.position_sizing_multiplier
                order_quantity = order_amount / self.lighter_price
                
                # Determine direction based on velocity trend and price spread
                if self.velocity_acceleration > 2.5:  # Strong upward momentum
                    side = 'buy'
                else:
                    side = 'sell'
                
                # Check minimum profit threshold
                expected_profit = self.calculate_expected_profit(side, self.lighter_price, order_quantity)
                if expected_profit < self.min_profit_threshold:
                    logger.debug(f"Expected profit ({expected_profit:.4f}) below threshold, skipping order")
                    return
                
                logger.info(f"⚡ Placing taker {side} order: {order_quantity:.6f} @ market")
                
                if not self.dry_run:
                    # Execute real market order
                    result = await self.lighter.market_order(
                        ticker=LIGHTER_SYMBOL,
                        amount=order_quantity if side == 'buy' else -order_quantity
                    )
                    
                    if result:
                        # Track order with timestamp (market orders fill immediately)
                        order_id = result.get('order_id', str(time.time()))
                        self.active_orders[order_id] = {
                            'side': side,
                            'price': self.lighter_price,
                            'quantity': order_quantity,
                            'timestamp': time.time(),
                            'type': 'taker',
                            'status': 'filled'
                        }
                        
                        self.taker_order_count += 1
                        self.daily_trade_count += 1
                        logger.info(f"✅ Taker order executed successfully (ID: {order_id})")
                    else:
                        logger.error(f"❌ Failed to execute taker order")
                else:
                    # Simulate order tracking in dry run
                    order_id = f"dry_{time.time()}"
                    self.active_orders[order_id] = {
                        'side': side,
                        'price': self.lighter_price,
                        'quantity': order_quantity,
                        'timestamp': time.time(),
                        'type': 'taker',
                        'status': 'filled'
                    }
                    
                    self.taker_order_count += 1
                    self.daily_trade_count += 1
                    logger.info(f"🔄 DRY RUN: Taker order would be executed (ID: {order_id})")
                    
        except Exception as e:
            logger.error(f"Error placing taker order: {e}")
            
    async def update_lighter_price(self):
        """Update Lighter price data and manage order timeouts"""
        try:
            # Get current price from Lighter using compatibility method
            ticker = await self.lighter.get_ticker(LIGHTER_SYMBOL)
            if ticker:
                self.lighter_price = float(ticker.get('last_price', 0))
                self.lighter_bid = float(ticker.get('bid', 0))
                self.lighter_ask = float(ticker.get('ask', 0))
            
            # Check for order timeouts
            await self.check_order_timeouts()
            
        except Exception as e:
            logger.error(f"Error updating Lighter price: {e}")
    
    async def check_order_timeouts(self):
        """Check for and cancel orders that have been open too long"""
        try:
            current_time = time.time()
            orders_to_cancel = []
            
            for order_id, order_info in self.active_orders.items():
                # Skip filled orders
                if order_info.get('status') == 'filled':
                    continue
                    
                # Check if order has timed out
                if current_time - order_info['timestamp'] > self.order_timeout:
                    orders_to_cancel.append(order_id)
            
            # Cancel timed out orders
            for order_id in orders_to_cancel:
                await self.cancel_timed_out_order(order_id)
                
        except Exception as e:
            logger.error(f"Error checking order timeouts: {e}")
    
    async def cancel_timed_out_order(self, order_id):
        """Cancel a single timed out order"""
        try:
            order_info = self.active_orders.get(order_id)
            if not order_info:
                return
                
            logger.info(f"🕐 Order {order_id} timed out after {self.order_timeout}s, cancelling...")
            
            if not self.dry_run and not order_id.startswith('dry_'):
                # Cancel real order
                result = await self.lighter.cancel_order(LIGHTER_SYMBOL, order_id)
                if result:
                    logger.info(f"✅ Order {order_id} cancelled successfully")
                else:
                    logger.warning(f"⚠️ Failed to cancel order {order_id}")
            
            # Remove from active orders
            self.active_orders.pop(order_id, None)
            
        except Exception as e:
            logger.error(f"Error cancelling timed out order {order_id}: {e}")
            # Remove from tracking even if cancellation failed
            self.active_orders.pop(order_id, None)
            
    async def monitor_positions(self):
        """Monitor and manage open positions with enhanced risk management"""
        try:
            # Update positions from Lighter using compatibility method
            positions = await self.lighter.get_positions()
            total_position_size = 0
            
            # Calculate PnL and manage risk
            for position in positions:
                size = position.get('size', 0)
                if size != 0:
                    total_position_size += abs(size)
                    
                    # Calculate unrealized PnL
                    entry_price = position.get('entry_price', 0)
                    current_price = self.lighter_price
                    
                    if entry_price > 0 and current_price > 0:
                        pnl = (current_price - entry_price) * size
                        self.daily_pnl += pnl
                        
                        # Enhanced risk management
                        await self.manage_position_risk(position, pnl)
            
            # Check inventory risk
            await self.check_inventory_risk(total_position_size)
            
            # Check daily loss limit
            if self.daily_pnl < self.max_daily_loss:
                logger.warning(f"🚨 Daily loss limit reached (${self.daily_pnl:.2f}), stopping trading")
                self.shutdown_requested = True
                
        except Exception as e:
            logger.error(f"Error monitoring positions: {e}")
    
    async def manage_position_risk(self, position, pnl):
        """Manage individual position risk"""
        try:
            size = position.get('size', 0)
            position_id = position.get('position_id', 'unknown')
            
            # Dynamic profit targets and stop losses based on volatility
            volatility_factor = max(1.0, self.velocity_acceleration)
            profit_target = 2.0 * volatility_factor  # Higher targets during high volatility
            stop_loss = -1.5 * volatility_factor  # Wider stops during high volatility
            
            # Close position if profit target hit or stop loss
            if pnl > profit_target:
                logger.info(f"🎯 Profit target reached for position {position_id}: ${pnl:.2f}")
                await self.close_position(position)
            elif pnl < stop_loss:
                logger.warning(f"🛑 Stop loss triggered for position {position_id}: ${pnl:.2f}")
                await self.close_position(position)
            elif abs(size) > self.position_threshold:
                logger.warning(f"⚠️ Position size {abs(size)} exceeds threshold {self.position_threshold}")
                # Consider partial close
                await self.partial_close_position(position, 0.3)  # Close 30%
                
        except Exception as e:
            logger.error(f"Error managing position risk: {e}")
    
    async def check_inventory_risk(self, total_position_size):
        """Check and manage inventory risk"""
        try:
            if total_position_size > self.inventory_threshold:
                logger.warning(f"📦 Inventory risk: Total position size {total_position_size} exceeds threshold {self.inventory_threshold}")
                
                # Reduce position sizing multiplier
                self.position_sizing_multiplier = max(0.5, self.position_sizing_multiplier * 0.9)
                logger.info(f"📉 Reduced position sizing multiplier to {self.position_sizing_multiplier:.2f}")
                
                # Cancel some active orders to reduce exposure
                await self.cancel_excess_orders()
                
        except Exception as e:
            logger.error(f"Error checking inventory risk: {e}")
    
    async def cancel_excess_orders(self):
        """Cancel excess orders to reduce exposure"""
        try:
            if len(self.active_orders) > self.max_orders_per_side:
                # Cancel oldest orders first
                sorted_orders = sorted(self.active_orders.items(), key=lambda x: x[1]['timestamp'])
                orders_to_cancel = sorted_orders[:len(self.active_orders) - self.max_orders_per_side]
                
                for order_id, _ in orders_to_cancel:
                    await self.cancel_timed_out_order(order_id)
                    
        except Exception as e:
            logger.error(f"Error cancelling excess orders: {e}")
    
    async def partial_close_position(self, position, close_ratio):
        """Partially close a position"""
        try:
            size = position.get('size', 0)
            if size == 0:
                return
                
            close_size = abs(size) * close_ratio
            side = 'sell' if size > 0 else 'buy'
            
            logger.info(f"🔄 Partially closing position: {side} {close_size:.6f}")
            
            if not self.dry_run:
                result = await self.lighter.market_order(
                    ticker=LIGHTER_SYMBOL,
                    amount=close_size if side == 'buy' else -close_size
                )
                
                if result:
                    logger.info(f"✅ Position partially closed successfully")
                else:
                    logger.error(f"❌ Failed to partially close position")
                    
        except Exception as e:
            logger.error(f"Error partially closing position: {e}")
            
    async def close_position(self, position):
        """Close a position"""
        try:
            size = position.get('size', 0)
            if size != 0:
                side = 'sell' if size > 0 else 'buy'
                close_size = abs(size)
                
                logger.info(f"🔄 Closing position: {side} {close_size}")
                
                if not self.dry_run:
                    result = await self.lighter.market_order(
                        ticker=LIGHTER_SYMBOL,
                        amount=close_size if side == 'buy' else -close_size
                    )
                    
                    if result:
                        logger.info(f"✅ Position closed successfully")
                    else:
                        logger.error(f"❌ Failed to close position")
                        
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            
    async def run(self):
        """Main trading loop with enhanced monitoring"""
        logger.info("🚀 Starting cross-exchange arbitrage bot...")
        
        # Setup WebSocket connections
        await self.setup_binance_websocket()
        
        # Performance tracking
        status_counter = 0
        performance_summary_interval = 600  # 10 minutes
        
        # Main trading loop
        while not self.shutdown_requested:
            try:
                # Update Lighter price
                await self.update_lighter_price()
                
                # Monitor positions
                await self.monitor_positions()
                
                # Enhanced status logging
                status_counter += 1
                await self.log_status()
                
                # Log performance summary periodically
                if status_counter % (performance_summary_interval // 5) == 0:  # Every 10 minutes
                    await self.log_performance_summary()
                
                # Adaptive sleep based on market conditions
                sleep_duration = self.calculate_sleep_duration()
                
                # Sleep with responsive shutdown
                for _ in range(int(sleep_duration * 2)):  # Convert to 0.5s increments
                    if self.shutdown_requested:
                        break
                    await asyncio.sleep(0.5)
                    
            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
                self.shutdown_requested = True
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(5)
                
        await self.graceful_shutdown()
    
    def calculate_sleep_duration(self):
        """Calculate adaptive sleep duration based on market conditions"""
        try:
            # Base sleep duration
            base_sleep = 5.0  # 5 seconds
            
            # Adjust based on velocity acceleration
            if self.velocity_acceleration > 2.0:
                # High volatility - check more frequently
                return base_sleep * 0.5
            elif self.velocity_acceleration > 1.5:
                # Moderate volatility
                return base_sleep * 0.75
            else:
                # Low volatility - can sleep longer
                return base_sleep
                
        except Exception as e:
            logger.error(f"Error calculating sleep duration: {e}")
            return 5.0
        
    async def log_status(self):
        """Log comprehensive status and performance metrics"""
        try:
            # Market data
            logger.info(f"📊 Market Status: Velocity={self.current_velocity:.2f}/s, Acceleration={self.velocity_acceleration:.2f}x")
            logger.info(f"📈 Prices: Binance=${self.binance_price:.6f}, Lighter=${self.lighter_price:.6f}")
            if self.binance_price > 0 and self.lighter_price > 0:
                spread_pct = abs(self.lighter_price - self.binance_price) / self.binance_price * 100
                logger.info(f"🔄 Spread: {spread_pct:.3f}%")
            
            # Order statistics
            active_maker_orders = sum(1 for order in self.active_orders.values() if order['type'] == 'maker')
            active_taker_orders = sum(1 for order in self.active_orders.values() if order['type'] == 'taker')
            logger.info(f"💰 Orders: Total={len(self.active_orders)}, Maker={active_maker_orders}, Taker={active_taker_orders}")
            logger.info(f"📊 Daily: Maker={self.maker_order_count}, Taker={self.taker_order_count}, Total={self.daily_trade_count}/{MAX_DAILY_TRADES}")
            
            # Position and risk metrics
            total_position_value = sum(abs(order['price'] * order['quantity']) for order in self.active_orders.values())
            logger.info(f"🎯 Positions: {len(self.positions)}, Total Value: ${total_position_value:.2f}")
            logger.info(f"💵 Daily PnL: ${self.daily_pnl:.2f}, Limit: ${self.max_daily_loss}")
            
            # Risk management status
            logger.info(f"⚖️ Risk: Position Multiplier={self.position_sizing_multiplier:.2f}, Max Orders={self.max_orders_per_side}")
            
            # Performance metrics
            if self.daily_trade_count > 0:
                maker_ratio = self.maker_order_count / self.daily_trade_count
                logger.info(f"📈 Performance: Maker Ratio={maker_ratio:.2f}, Target={MAKER_RATIO}")
            
            # Order timeout status
            current_time = time.time()
            timed_out_orders = [order_id for order_id, order in self.active_orders.items() 
                              if current_time - order['timestamp'] > self.order_timeout]
            if timed_out_orders:
                logger.warning(f"⏰ Orders pending timeout: {len(timed_out_orders)}")
            
            # Signal quality
            if hasattr(self, 'last_signal_strength'):
                logger.info(f"🎯 Last Signal Strength: {self.last_signal_strength:.2f}")
            
        except Exception as e:
            logger.error(f"Error logging status: {e}")
    
    async def log_performance_summary(self):
        """Log detailed performance summary"""
        try:
            logger.info("=" * 60)
            logger.info("📊 PERFORMANCE SUMMARY")
            logger.info("=" * 60)
            
            # Trading performance
            logger.info(f"💰 Trading Performance:")
            logger.info(f"  Total Trades: {self.daily_trade_count}")
            logger.info(f"  Maker Orders: {self.maker_order_count}")
            logger.info(f"  Taker Orders: {self.taker_order_count}")
            if self.daily_trade_count > 0:
                logger.info(f"  Maker Ratio: {self.maker_order_count/self.daily_trade_count:.2%}")
            
            # Financial performance
            logger.info(f"💵 Financial Performance:")
            logger.info(f"  Daily PnL: ${self.daily_pnl:.2f}")
            logger.info(f"  Max Daily Loss: ${self.max_daily_loss}")
            
            # Risk metrics
            logger.info(f"⚖️ Risk Management:")
            logger.info(f"  Active Orders: {len(self.active_orders)}")
            logger.info(f"  Position Multiplier: {self.position_sizing_multiplier:.2f}")
            logger.info(f"  Position Threshold: {self.position_threshold}")
            
            # Market conditions
            logger.info(f"📈 Market Conditions:")
            logger.info(f"  Current Velocity: {self.current_velocity:.2f}/s")
            logger.info(f"  Velocity Threshold: {VELOCITY_THRESHOLD}")
            logger.info(f"  Max Acceleration: {self.velocity_acceleration:.2f}x")
            
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error logging performance summary: {e}")
            
    async def graceful_shutdown(self):
        """Graceful shutdown with comprehensive cleanup"""
        logger.info("🛑 Initiating graceful shutdown...")
        
        try:
            # Log final performance summary
            await self.log_performance_summary()
            
            # Cancel all active orders
            if len(self.active_orders) > 0:
                logger.info(f"Cancelling {len(self.active_orders)} active orders...")
                if not self.dry_run:
                    result = await self.lighter.cancel_all_orders()
                    logger.info(f"✅ Cancelled {len(result)} orders")
                else:
                    logger.info("🔄 DRY RUN: Would cancel all orders")
                
                # Clear tracking
                self.active_orders.clear()
            
            # Close all positions
            if len(self.positions) > 0:
                logger.info(f"Closing {len(self.positions)} open positions...")
                for position in self.positions:
                    await self.close_position(position)
                    
            logger.info("✅ Shutdown complete")
            
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
            
        # Cleanup
        if self.lighter:
            await self.lighter.cleanup()
            
        # Final statistics
        logger.info("🏁 Final Statistics:")
        logger.info(f"  Total Trading Day: {self.daily_trade_count} trades")
        logger.info(f"  Final PnL: ${self.daily_pnl:.2f}")
        logger.info(f"  Maker Orders: {self.maker_order_count}")
        logger.info(f"  Taker Orders: {self.taker_order_count}")
        if self.daily_trade_count > 0:
            logger.info(f"  Success Rate: {self.maker_order_count/self.daily_trade_count:.2%}")
            
def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Cross-Exchange Arbitrage Bot')
    parser.add_argument('--dry-run', action='store_true', help='Run in simulation mode')
    return parser.parse_args()

async def main():
    """Main function with signal handling"""
    args = parse_arguments()
    
    # Create bot instance
    bot = CrossExchangeArbitrageBot(dry_run=args.dry_run)
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        bot.shutdown_requested = True
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if args.dry_run:
        logger.info("🧪 DRY RUN mode - no real orders")
    else:
        logger.info("💰 LIVE TRADING mode - real money!")
        logger.warning("⚠️ Use Ctrl+C for graceful shutdown")
        
        user_input = input("Type 'YES' to confirm live trading: ")
        if user_input != 'YES':
            logger.info("Live trading cancelled")
            return
    
    try:
        await bot.setup()
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt")
        await bot.graceful_shutdown()
    except Exception as e:
        logger.error(f"Bot failed: {e}")
        await bot.graceful_shutdown()
        raise
    finally:
        logger.info("🏁 Application shutdown complete")

if __name__ == "__main__":
    args = parse_arguments()
    mode_str = "DRY RUN" if args.dry_run else "LIVE TRADING"
    print(f"🤖 Cross-Exchange Arbitrage Bot ({mode_str})")
    print(f"📊 Symbol: {COIN_NAME}, Leverage: {LEVERAGE}x")
    print(f"💰 Order Amount: ${ORDER_AMOUNT_USD} USD per order")
    print(f"🚀 Strategy: Trading Velocity Acceleration Factor")
    print("=" * 50)
    
    asyncio.run(main())