"""
Simplified Grid Trading Strategy for Lighter Protocol
Based on Binance reference but adapted for Lighter Protocol

Key simplifications:
1. Reduced WebSocket complexity
2. Simplified order tracking 
3. Focused error handling
4. Cleaner code structure
"""

import os
import asyncio
import logging
import time
import math
import json
import argparse
import signal
import lighter
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from pylighter.client import Lighter

# Load environment variables
load_dotenv()

# Create log directory
os.makedirs("log", exist_ok=True)

# ==================== Configuration ====================
COIN_NAME = "TON"
GRID_SPACING = 0.0003       # 0.03% grid spacing (ultra-high frequency for zero fees!)
DEFAULT_ORDER_AMOUNT = 10.0  # Default order amount in USD (quote currency)
LEVERAGE = 5                # Leverage for TON (conservative vs OKX's 50x)
SYNC_TIME = 10              # Sync interval (seconds)
UPDATE_INTERVAL = 5         # Price update interval
MAX_ACTIVE_ORDERS = 8       # Maximum active orders

# Ultra-high frequency advantage with zero fees

# ==================== Logging Configuration ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("log/grid_strategy.log", mode='a'),
        logging.StreamHandler(),
    ],
    force=True
)
logger = logging.getLogger()

# Set WebSocket-related loggers to DEBUG level to reduce noise
logging.getLogger('websockets').setLevel(logging.WARNING)
logging.getLogger('lighter').setLevel(logging.INFO)

class SimplifiedGridBot:
    """Simplified Grid Trading Bot for Lighter Protocol"""
    
    def __init__(self, dry_run=False, order_amount=None):
        self.dry_run = dry_run
        self.lighter = None
        self.ws_client = None
        self.symbol = COIN_NAME
        self.market_id = None
        self.grid_spacing = GRID_SPACING
        self.leverage = LEVERAGE
        
        # Order amount configuration
        self.order_amount = order_amount or DEFAULT_ORDER_AMOUNT  # USD amount per order
        
        # Shutdown control
        self.shutdown_requested = False
        
        # Market constraints
        self.min_quote_amount = 10.0
        self.price_precision = 6
        self.amount_precision = 1
        self.step_size = None  # Will be calculated from amount_precision
        
        # Position tracking
        self.long_position = 0
        self.short_position = 0
        self.long_initial_quantity = 0  # Will be calculated dynamically
        self.short_initial_quantity = 0  # Will be calculated dynamically
        
        # Order counting for display
        self.buy_long_orders = 0.0    # Long buy orders count
        self.sell_long_orders = 0.0   # Long sell orders count
        self.sell_short_orders = 0.0  # Short sell orders count
        self.buy_short_orders = 0.0   # Short buy orders count
        
        # Price tracking
        self.latest_price = 0
        self.best_bid_price = None
        self.best_ask_price = None
        self.price_updated = False
        
        # Order tracking
        self.active_orders = {}  # order_id -> order_info
        self.last_position_update_time = 0
        
        # Enhanced order management
        self.max_orders = 8  # Restore original limit for better grid coverage
        self.sync_warning_throttle = {}  # Throttle sync warnings by type
        
        # WebSocket connection status and health monitoring
        self.ws_connected = False
        self._last_account_update_time = None  # Track when we last received account updates
        
        # WebSocket health monitoring
        self._ws_health_check_interval = 60  # Check every minute
        self._last_ws_health_check = 0
        self._ws_connection_failures = 0
        self._max_ws_connection_failures = 5
        self._ws_start_time = None  # Track WebSocket start time
        
        # Initialize WebSocket order count tracking for force cleanup
        self._last_ws_order_count = 0
        self._ws_zero_count = 0
        
    async def setup(self):
        """Initialize the Lighter client"""
        api_key = os.getenv("LIGHTER_KEY")
        api_secret = os.getenv("LIGHTER_SECRET")
        
        if not api_key or not api_secret:
            raise ValueError("Please set LIGHTER_KEY and LIGHTER_SECRET environment variables")
        
        logger.info("Initializing Lighter client...")
        self.lighter = Lighter(key=api_key, secret=api_secret)
        await self.lighter.init_client()
        logger.info("✅ Client initialized successfully")
        
        # Get market_id and constraints
        self.market_id = self.lighter.ticker_to_idx.get(self.symbol)
        if self.market_id is None:
            raise ValueError(f"Market ID not found for symbol {self.symbol}")
        
        # Fetch market constraints
        await self.fetch_market_constraints()
        
        # Setup account orders WebSocket for order tracking
        await self.setup_account_orders_websocket()
        
        logger.info(f"Grid bot setup complete for {self.symbol}")
        logger.info(f"Market ID: {self.market_id}, Min quote: ${self.min_quote_amount}")
        logger.info(f"Leverage: {self.leverage}x, Grid spacing: {self.grid_spacing*100}%")
        
        # Get initial positions
        await self.update_positions()
        
        # Initial API sync to get existing orders
        logger.info("📋 Performing initial order sync...")
        await self.sync_orders_from_api()
        self._last_api_sync = time.time()
        
    async def fetch_market_constraints(self):
        """Fetch market constraints and calculate step_size"""
        try:
            constraints = await self.lighter.get_market_constraints(self.symbol)
            self.min_quote_amount = constraints['min_quote_amount']
            self.price_precision = constraints['price_precision']
            self.amount_precision = constraints['amount_precision']
            
            # Calculate step_size from amount_precision (simplified approach)
            self.step_size = 10 ** (-self.amount_precision)
            
            logger.info(f"Constraints: min_quote=${self.min_quote_amount}, price_precision={self.price_precision}, amount_precision={self.amount_precision}")
            logger.info(f"Calculated step_size: {self.step_size}, Order amount: ${self.order_amount} USD per order")
        except Exception as e:
            logger.warning(f"Failed to fetch constraints: {e}, using defaults")
            self.min_quote_amount = 10.0
            self.price_precision = 6
            self.amount_precision = 1
            self.step_size = 0.1  # Default step size
    
    async def init_websocket(self):
        """Initialize WebSocket client for price updates"""
        logger.info("Initializing WebSocket client...")
        try:
            def on_order_book_update(market_id, order_book):
                try:
                    # Skip ping/pong handling in sync callback
                    if isinstance(order_book, dict) and order_book.get('type') in ['ping', 'pong']:
                        return
                    
                    if int(market_id) == int(self.market_id):
                        bids = order_book.get('bids', [])
                        asks = order_book.get('asks', [])
                        
                        if bids and asks:
                            self.best_bid_price = float(bids[0]['price'])
                            self.best_ask_price = float(asks[0]['price'])
                            old_price = self.latest_price
                            self.latest_price = (self.best_bid_price + self.best_ask_price) / 2
                            self.price_updated = True
                            
                            # Update quantities on first price
                            if old_price == 0 and self.latest_price > 0:
                                self.update_initial_quantities()
                                
                except Exception as e:
                    if not any(keyword in str(e).lower() for keyword in ['ping', 'pong', 'unhandled', 'connection']):
                        logger.error(f"Error processing orderbook: {e}")
            
            self.ws_client = lighter.WsClient(
                order_book_ids=[self.market_id],
                account_ids=[],
                on_order_book_update=on_order_book_update,
                on_account_update=lambda a, b: None,
            )
            logger.info("✅ WebSocket client initialized with enhanced ping/pong handling")
        except Exception as e:
            logger.error(f"❌ WebSocket initialization failed: {e}")
            raise
    
    def calculate_order_quantity(self, price):
        """Calculate order quantity based on configured USD amount and step_size"""
        try:
            if price <= 0:
                return 0
            
            # Calculate base quantity from USD amount
            base_quantity = self.order_amount / price
            
            # Round to step_size (which is derived from amount_precision)
            if self.step_size and self.step_size > 0:
                # Round down to nearest step_size multiple
                quantity = math.floor(base_quantity / self.step_size) * self.step_size
                
                # Ensure minimum quantity
                if quantity < self.step_size:
                    quantity = self.step_size
            else:
                # Fallback to amount_precision rounding
                quantity = round(base_quantity, self.amount_precision)
            
            # Validate minimum quote amount
            quote_value = quantity * price
            if quote_value < self.min_quote_amount:
                # Adjust quantity to meet minimum quote requirement
                min_quantity = self.min_quote_amount / price
                if self.step_size and self.step_size > 0:
                    quantity = math.ceil(min_quantity / self.step_size) * self.step_size
                else:
                    quantity = round(min_quantity, self.amount_precision)
            
            return quantity
            
        except Exception as e:
            logger.error(f"Failed to calculate order quantity: {e}")
            # Fallback to original method
            return self.lighter.calculate_min_quantity_for_quote_amount(
                price, max(self.order_amount, self.min_quote_amount), self.symbol
            )
    
    def update_initial_quantities(self):
        """Update quantities based on current price and configured order amount (OKX-style)"""
        if self.latest_price > 0:
            calculated_quantity = self.calculate_order_quantity(self.latest_price)
            self.long_initial_quantity = calculated_quantity
            self.short_initial_quantity = calculated_quantity
            
            quote_value = calculated_quantity * self.latest_price
            logger.info(f"Updated quantities based on price ${self.latest_price:.6f}: {calculated_quantity:.{self.amount_precision}f} {self.symbol} (${quote_value:.2f})")
    
    async def update_positions(self):
        """Update current positions (simplified)"""
        if self.dry_run:
            # In DRY RUN mode, don't reset positions - they should persist from simulated fills
            # Only update timestamp to prevent issues
            self.last_position_update_time = time.time()
        else:
            # In real mode, you might want to fetch actual positions from the API
            # For now, positions are managed through order fills
            pass

    async def sync_orders_from_api(self):
        """Sync active orders using the new account_active_orders API"""
        try:
            if self.dry_run:
                logger.debug("🔄 DRY RUN - Skipping API order sync")
                return
                
            # Use the new account_active_orders API
            response = await self.lighter.account_active_orders(self.symbol)
            
            # Extract orders from response
            orders = response.get('orders', [])
            if not orders:
                # Clear all active orders if API returns empty
                if self.active_orders:
                    logger.info(f"🧹 API shows no active orders, clearing {len(self.active_orders)} tracked orders")
                    self.active_orders.clear()
                return
            
            # Process orders from API
            api_order_ids = set()
            active_api_orders = []
            
            for order in orders:
                # Check if order is truly active
                status = order.get('status', '').lower()
                remaining_amount = float(order.get('remaining_base_amount', '0'))
                order_id = str(order.get('order_id', order.get('order_index', '')))
                
                if status in ['active', 'open', 'pending', 'live'] and remaining_amount > 0:
                    if order_id:
                        api_order_ids.add(order_id)
                        active_api_orders.append(order)
                        
                        # Update local tracking with API data
                        is_ask = order.get('is_ask', False)
                        side = 'sell' if is_ask else 'buy'
                        price = float(order.get('price', '0'))
                        quantity = remaining_amount
                        
                        # Determine position type based on current positions and side
                        position_type = 'short' if (side == 'sell' and self.long_position <= 0) or (side == 'buy' and self.short_position > 0) else 'long'
                        
                        self.active_orders[order_id] = {
                            'side': side,
                            'price': price,
                            'quantity': quantity,
                            'position_type': position_type,
                            'order_id': order_id,
                            'api_synced': True
                        }
            
            # Remove orders that are no longer active according to API
            tracked_order_ids = set(self.active_orders.keys())
            completed_order_ids = tracked_order_ids - api_order_ids
            
            if completed_order_ids:
                logger.info(f"📋 API sync: {len(completed_order_ids)} orders completed, {len(active_api_orders)} still active")
                for order_id in completed_order_ids:
                    completed_order = self.active_orders.pop(order_id, None)
                    if completed_order:
                        logger.debug(f"🎯 API removed completed order: {order_id} ({completed_order['side']} {completed_order['quantity']} @ {completed_order['price']})")
            
            logger.debug(f"✅ API sync complete: {len(self.active_orders)} active orders")
            
        except Exception as e:
            logger.warning(f"Failed to sync orders from API: {e}")
    
    def check_orders_status(self):
        """Update order counters from active orders"""
        # Reset counters
        self.buy_long_orders = 0.0
        self.sell_long_orders = 0.0
        self.sell_short_orders = 0.0
        self.buy_short_orders = 0.0
        
        # Count active orders by type
        for order_id, order_info in self.active_orders.items():
            side = order_info.get('side', '')
            quantity = order_info.get('quantity', 0)
            
            if side == 'buy':
                if self.short_position > 0:
                    self.buy_short_orders += quantity
                else:
                    self.buy_long_orders += quantity
            elif side == 'sell':
                if self.long_position > 0:
                    self.sell_long_orders += quantity
                else:
                    self.sell_short_orders += quantity
        
        # Log order counts when there are orders
        active_count = len(self.active_orders)
        if active_count > 0:
            logger.debug(f"Order counts: {active_count} active orders - Long(buy={self.buy_long_orders:.1f}, sell={self.sell_long_orders:.1f}), Short(sell={self.sell_short_orders:.1f}, buy={self.buy_short_orders:.1f})")
    
    async def place_order(self, side, price, quantity, position_type='long'):
        """Place an order with order limit control"""
        try:
            # Check order limits only
            if len(self.active_orders) >= self.max_orders:
                logger.warning(f"Max orders ({self.max_orders}) reached, skipping order placement")
                return None
            
            # Validate and format
            formatted_price = self.lighter.format_price(price, self.symbol)
            is_valid, formatted_quantity, error_msg = self.lighter.validate_order_amount(
                formatted_price, quantity, self.symbol
            )
            
            if not is_valid:
                logger.info(f"Order adjusted: {error_msg}")
                quantity = formatted_quantity
            
            if self.dry_run:
                quote_value = formatted_price * abs(quantity)
                logger.info(f"🔄 DRY RUN - {side.upper()}: {quantity} @ ${formatted_price:.6f} (${quote_value:.2f})")
                
                # Generate fake order ID for dry run tracking
                order_id = str(int(time.time() * 1000))
                
                # Track order for dry run
                self.active_orders[order_id] = {
                    'side': side,
                    'price': formatted_price,
                    'quantity': abs(quantity),
                    'position_type': position_type,
                    'timestamp': time.time(),
                    'tx_hash': None
                }
                
                return order_id
            
            # Real order placement
            logger.info(f"📈 REAL - {side}: {quantity} {self.symbol} @ ${formatted_price:.6f}")
            
            # Adjust quantity for short positions
            if position_type == 'short' and side == 'sell':
                quantity = -abs(quantity)
            elif position_type == 'long' and side == 'sell':
                quantity = -abs(quantity)  # Exit long position with negative quantity
            
            result = await self.lighter.limit_order(
                ticker=self.symbol,
                amount=quantity,
                price=formatted_price,
                tif='GTC'
            )
            
            if result is None:
                logger.error("Order failed: No result returned")
                return None
            
            # Extract order information from result
            # Lighter returns (tx_info, tx_hash, error) or similar structure
            if isinstance(result, tuple) and len(result) >= 2:
                tx_info, tx_hash = result[0], result[1]
                error = result[2] if len(result) > 2 else None
                
                if error is not None:
                    logger.error(f"Order failed: {error}")
                    return None
                
                # Generate order ID for tracking
                order_id = str(int(time.time() * 1000))  # Timestamp-based ID
                
                # Extract real order ID from transaction info if available
                if hasattr(tx_info, 'event_info') and tx_info.event_info:
                    try:
                        # Try to extract order index from event_info
                        if hasattr(tx_info.event_info, 'order_index'):
                            order_id = str(tx_info.event_info.order_index)
                        elif hasattr(tx_info.event_info, 'order_id'):
                            order_id = str(tx_info.event_info.order_id)
                    except:
                        pass  # Use timestamp ID as fallback
                
                # Track order
                self.active_orders[order_id] = {
                    'side': side,
                    'price': formatted_price,
                    'quantity': abs(quantity),
                    'position_type': position_type,
                    'timestamp': time.time(),
                    'tx_hash': str(tx_hash) if tx_hash else None
                }
                
                logger.info(f"✅ Order placed: {order_id}")
                return order_id
            else:
                logger.error(f"Unexpected result format: {result}")
                return None
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None
    
    async def setup_account_orders_websocket(self):
        """Setup WebSocket subscription for account orders with proper authentication"""
        try:
            if self.dry_run:
                logger.info("🔄 DRY RUN - Would setup account orders WebSocket")
                return
                
            logger.info("🔌 Setting up account orders WebSocket with authentication...")
            self._ws_start_time = time.time()  # Track WebSocket start time
            
            # Generate authentication token using SignerClient
            auth_token = self.lighter.client.create_auth_token_with_expiry()
            if not auth_token or len(auth_token) < 2 or auth_token[1]:  # Check for error
                logger.error(f"Failed to generate auth token: {auth_token}")
                return
            
            auth_token_str = auth_token[0]  # Extract token string
            logger.info("✅ Authentication token generated successfully")
            
            # Create custom WebSocket client for account orders
            import websockets
            import asyncio
            
            async def run_account_orders_websocket():
                """Run dedicated WebSocket for account orders with proper connection handling"""
                websocket_url = "wss://mainnet.zklighter.elliot.ai/stream"
                max_retries = 5
                retry_count = 0
                
                while retry_count < max_retries and not self.shutdown_requested:
                    try:
                        logger.info("🌐 Connecting to account orders WebSocket...")
                        
                        async with websockets.connect(websocket_url) as ws:
                            # Wait for connection confirmation
                            connected = False
                            subscribed = False
                            
                            # Set up connection timeout
                            connection_timeout = 10  # seconds
                            start_time = asyncio.get_event_loop().time()
                            
                            # Listen for messages with proper state handling
                            async for message in ws:
                                if self.shutdown_requested:
                                    break
                                
                                # Check for connection timeout
                                if asyncio.get_event_loop().time() - start_time > connection_timeout and not connected:
                                    logger.warning("⏱️ WebSocket connection timeout")
                                    break
                                    
                                try:
                                    data = json.loads(message)
                                    message_type = data.get('type', '')
                                    
                                    # Log all messages for debugging
                                    logger.debug(f"📨 WebSocket message: type={message_type}")
                                    
                                    # Handle connection lifecycle
                                    if message_type == 'connected':
                                        logger.info("🔗 WebSocket connected, sending subscription...")
                                        connected = True
                                        
                                        # Now send subscription request
                                        subscribe_msg = {
                                            "type": "subscribe",
                                            "channel": f"account_orders/{self.market_id}/{self.lighter.account_idx}",
                                            "auth": auth_token_str
                                        }
                                        await ws.send(json.dumps(subscribe_msg))
                                        logger.info(f"📋 Sent subscription for account orders market {self.market_id}")
                                        
                                    elif message_type == 'subscribed/account_orders' or message_type.startswith('subscribed'):
                                        channel = data.get('channel', '')
                                        if 'account_orders' in channel:
                                            logger.info(f"✅ Successfully subscribed to account orders: {channel}")
                                            subscribed = True
                                            retry_count = 0  # Reset retry count on successful subscription
                                        
                                    elif message_type == 'update/account_orders':
                                        if subscribed:  # Only process if properly subscribed
                                            logger.info(f"🔍 Processing account orders update: {len(data.get('orders', {}).get(str(self.market_id), []))} orders")
                                            await self.handle_account_orders_update(data)
                                        else:
                                            logger.debug("Ignoring account orders update - not properly subscribed yet")
                                            
                                    elif message_type == 'error':
                                        error_msg = data.get('message', data.get('error', 'Unknown error'))
                                        logger.error(f"❌ WebSocket error: {error_msg}")
                                        # Break to trigger reconnection
                                        break
                                        
                                    elif message_type == 'ping':
                                        # Respond to ping with pong
                                        await ws.send(json.dumps({"type": "pong"}))
                                        logger.debug("🏓 Responded to ping")
                                        
                                    elif message_type == 'pong':
                                        logger.debug("🏓 Received pong")
                                        
                                    else:
                                        # Log unhandled messages for debugging
                                        if message_type and message_type not in ['heartbeat', 'status']:
                                            logger.info(f"📨 Unhandled WebSocket message: type={message_type}, data={data}")
                                        else:
                                            logger.debug(f"📨 Minor WebSocket message: {message_type}")
                                            
                                except json.JSONDecodeError as e:
                                    logger.warning(f"❌ Failed to parse WebSocket message: {e}")
                                except Exception as e:
                                    logger.error(f"❌ Error handling WebSocket message: {e}")
                                    
                    except websockets.exceptions.ConnectionClosed as e:
                        logger.warning(f"🔌 WebSocket connection closed: {e}")
                        retry_count += 1
                        if retry_count < max_retries:
                            wait_time = min(2 ** retry_count, 10)  # Exponential backoff, max 10s
                            logger.info(f"⏳ Retrying WebSocket connection in {wait_time}s (attempt {retry_count}/{max_retries})")
                            await asyncio.sleep(wait_time)
                        
                    except websockets.exceptions.WebSocketException as e:
                        logger.error(f"❌ WebSocket error: {e}")
                        retry_count += 1
                        if retry_count < max_retries:
                            wait_time = min(2 ** retry_count, 10)
                            logger.info(f"⏳ Retrying WebSocket connection in {wait_time}s (attempt {retry_count}/{max_retries})")
                            await asyncio.sleep(wait_time)
                        
                    except Exception as e:
                        logger.error(f"❌ Unexpected WebSocket error: {e}")
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(5)
                
                if retry_count >= max_retries:
                    logger.error(f"❌ WebSocket connection failed after {max_retries} retries")
                else:
                    logger.info("✅ WebSocket connection closed normally")
            
            # Start WebSocket in background
            asyncio.create_task(run_account_orders_websocket())
            logger.info("✅ Account orders WebSocket setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup account orders WebSocket: {e}")
    
    async def handle_account_orders_update(self, data):
        """Handle account orders updates from dedicated WebSocket with improved lifecycle tracking"""
        try:
            # Mark that we received an account update
            self._last_account_update_time = time.time()
            
            # Extract orders data - Lighter format: {"orders": {"{MARKET_INDEX}": [Order]}}
            orders_data = data.get('orders', {})
            market_orders = orders_data.get(str(self.market_id), [])
            
            # Process order lifecycle events - Lighter Protocol format
            order_events = data.get('order_events', [])
            for event in order_events:
                await self.handle_order_lifecycle_event(event)
            
            # Reset order counters when we have meaningful WebSocket data
            if market_orders or len(self.active_orders) == 0:
                self.buy_long_orders = 0.0
                self.sell_long_orders = 0.0
                self.sell_short_orders = 0.0
                self.buy_short_orders = 0.0
            else:
                # WebSocket empty but we have tracked orders - use internal tracking for counters
                logger.debug(f"WebSocket empty, using internal tracking for {len(self.active_orders)} orders")
                self._update_order_counters_from_tracking()
            
            # Get current WebSocket order IDs
            websocket_order_ids = set()
            real_active_orders = []
            
            # Lighter Protocol uses array format: [{Order}, {Order}, ...]
            if isinstance(market_orders, list):
                for order in market_orders:
                    # Check Lighter Protocol order status and remaining amount
                    status = order.get('status', '').lower()
                    remaining_base_amount = float(order.get('remaining_base_amount', '0'))
                    order_id = order.get('order_id', order.get('order_index', ''))
                    
                    if order_id:
                        websocket_order_ids.add(str(order_id))
                    
                    # Only count orders that are truly active (open status AND have remaining amount)
                    if status in ['active', 'open', 'pending', 'live'] and remaining_base_amount > 0:
                        if order_id:
                            real_active_orders.append(str(order_id))
                            self._process_active_order_from_websocket(order)
            
            # Find orders that are no longer in WebSocket data (filled/cancelled)
            tracked_order_ids = set(self.active_orders.keys())
            missing_order_ids = tracked_order_ids - websocket_order_ids
            
            if missing_order_ids:
                logger.info(f"🎯 Orders no longer in WebSocket (filled/cancelled): {len(missing_order_ids)} orders")
                # Remove orders that are no longer present in WebSocket
                for order_id in missing_order_ids:
                    filled_order = self.active_orders.pop(order_id, None)
                    if filled_order:
                        logger.info(f"🎯 Removed completed order: {order_id} ({filled_order['side']} {filled_order['quantity']} @ {filled_order['price']})")
                        # Assume order was filled and update positions
                        await self._update_positions_from_completed_order(filled_order)
            
            # Reconcile tracked vs real orders with improved logic
            await self._reconcile_order_tracking(real_active_orders)
                    
        except Exception as e:
            logger.error(f"Failed to handle account orders update: {e}")
            logger.debug(f"Account orders data: {data}")
    
    async def _update_positions_from_completed_order(self, order_info):
        """Update positions when an order is completed (filled/cancelled)"""
        try:
            side = order_info.get('side', '')
            position_type = order_info.get('position_type', '')
            quantity = order_info.get('quantity', 0)
            price = order_info.get('price', 0)
            
            # Assume the order was filled (we can't distinguish between filled vs cancelled from missing orders)
            # This is safer than not updating positions at all
            if quantity > 0:
                logger.info(f"💰 Position update from completed order: {side.upper()} {quantity} {position_type} @ ${price:.6f}")
                
                # Update positions based on completed order
                if side == 'buy' and position_type == 'long':
                    self.long_position += quantity
                elif side == 'sell' and position_type == 'long':
                    self.long_position = max(0, self.long_position - quantity)
                elif side == 'sell' and position_type == 'short':
                    self.short_position += quantity
                elif side == 'buy' and position_type == 'short':
                    self.short_position = max(0, self.short_position - quantity)
                
                logger.info(f"💰 Updated positions - Long: {self.long_position}, Short: {self.short_position}")
            
        except Exception as e:
            logger.error(f"Failed to update positions from completed order: {e}")
    
    async def _update_positions_from_fill(self, ws_order, local_order):
        """Update positions based on order fill from WebSocket data"""
        try:
            side = local_order.get('side', '')
            position_type = local_order.get('position_type', '')
            filled_quantity = float(ws_order.get('filled_base_amount', '0'))
            fill_price = float(ws_order.get('price', '0'))
            
            if filled_quantity > 0:
                logger.info(f"💰 Position update from fill: {side.upper()} {filled_quantity} {position_type} @ ${fill_price:.6f}")
                
                # Update positions based on fill
                if side == 'buy' and position_type == 'long':
                    self.long_position += filled_quantity
                elif side == 'sell' and position_type == 'long':
                    self.long_position = max(0, self.long_position - filled_quantity)
                elif side == 'sell' and position_type == 'short':
                    self.short_position += filled_quantity
                elif side == 'buy' and position_type == 'short':
                    self.short_position = max(0, self.short_position - filled_quantity)
                
                logger.info(f"💰 Updated positions - Long: {self.long_position}, Short: {self.short_position}")
            
        except Exception as e:
            logger.error(f"Failed to update positions from fill: {e}")
    
    def _update_order_counters_from_tracking(self):
        """Update order counters from internal tracking"""
        for order_id, order_info in self.active_orders.items():
            side = order_info.get('side', '')
            quantity = order_info.get('quantity', 0)
            
            if side == 'buy':
                if self.short_position > 0:
                    self.buy_short_orders += quantity
                else:
                    self.buy_long_orders += quantity
            elif side == 'sell':
                if self.long_position > 0:
                    self.sell_long_orders += quantity
                else:
                    self.sell_short_orders += quantity
    
    def _process_active_order_from_websocket(self, order):
        """Process an active order from WebSocket data"""
        side = order.get('side', '').lower()
        remaining_amount = float(order.get('remaining_base_amount', '0'))
        
        if side == 'buy':
            if self.short_position > 0:
                self.buy_short_orders += remaining_amount
            else:
                self.buy_long_orders += remaining_amount
        elif side == 'sell':
            if self.long_position > 0:
                self.sell_long_orders += remaining_amount
            else:
                self.sell_short_orders += remaining_amount
    
    async def _reconcile_order_tracking(self, real_active_orders):
        """Reconcile internal tracking with WebSocket reality"""
        real_count = len(real_active_orders)
        tracked_count = len(self.active_orders)
        current_time = time.time()
        
        # Log order counts when there are orders
        if real_count > 0 or tracked_count > 0:
            logger.info(f"📋 Orders: WebSocket={real_count}, Tracked={tracked_count} | Long(buy={self.buy_long_orders:.1f}, sell={self.sell_long_orders:.1f}), Short(sell={self.sell_short_orders:.1f}, buy={self.buy_short_orders:.1f})")
        
        # Track last WebSocket order count for force cleanup
        self._last_ws_order_count = real_count
        
        # Improved sync logic with better reconciliation
        if real_count != tracked_count:
            sync_key = f"{real_count}_{tracked_count}"
            
            if sync_key not in self.sync_warning_throttle or current_time - self.sync_warning_throttle[sync_key] > 30:
                logger.warning(f"🔄 Order sync: WebSocket={real_count}, Tracked={tracked_count}")
                self.sync_warning_throttle[sync_key] = current_time
            
            # Smart reconciliation based on order age and WebSocket consistency
            if real_count < tracked_count:
                excess_count = tracked_count - real_count
                
                if real_count == 0 and tracked_count > 0:
                    # WebSocket shows 0 orders - use progressive cleanup based on order age
                    
                    # Initialize WebSocket zero counter for this specific case
                    if not hasattr(self, '_ws_zero_consecutive'):
                        self._ws_zero_consecutive = 0
                        self._last_ws_zero_time = current_time
                    
                    # Count consecutive WebSocket=0 readings
                    if current_time - getattr(self, '_last_ws_zero_time', current_time) < 10:  # Within last 10 seconds
                        self._ws_zero_consecutive += 1
                    else:
                        self._ws_zero_consecutive = 1  # Reset if gap in readings
                    
                    self._last_ws_zero_time = current_time
                    
                    # Progressive cleanup based on how long WebSocket has shown 0
                    if self._ws_zero_consecutive >= 3:  # WebSocket consistently 0 for 3+ readings
                        # First try to verify with REST API if we have significant discrepancy
                        if self._ws_zero_consecutive >= 5 and tracked_count >= 3:
                            logger.info(f"🔍 WebSocket=0 for {self._ws_zero_consecutive} cycles with {tracked_count} tracked orders - verifying via REST API")
                            try:
                                # Query actual orders from REST API as fallback
                                actual_orders = await self._verify_orders_via_rest_api()
                                if actual_orders is not None:
                                    logger.info(f"🔍 REST API verification: {len(actual_orders)} actual orders found")
                                    # If REST API shows 0 orders, trust it and clear stale local tracking
                                    if len(actual_orders) == 0:
                                        logger.warning(f"🔄 REST API confirms 0 orders - clearing {tracked_count} stale tracked orders")
                                        self.active_orders.clear()
                                        self._ws_zero_consecutive = 0
                                        return
                            except Exception as e:
                                logger.debug(f"REST API verification failed: {e}")
                        
                        # Fallback to time-based cleanup if REST verification not available
                        old_threshold = 60 if self._ws_zero_consecutive >= 5 else 120
                        
                        old_orders = [
                            (order_id, order_info) for order_id, order_info in self.active_orders.items()
                            if current_time - order_info['timestamp'] > old_threshold
                        ]
                        
                        if old_orders:
                            logger.info(f"🔄 WebSocket=0 for {self._ws_zero_consecutive} readings: Clearing {len(old_orders)} orders (>{old_threshold}s old)")
                            for order_id, _ in old_orders:
                                self.active_orders.pop(order_id, None)
                        elif self._ws_zero_consecutive >= 12 and tracked_count <= 4:
                            # If WebSocket consistently shows 0 for very long time (3+ minutes) and we don't have too many orders
                            logger.warning(f"🔄 WebSocket=0 for {self._ws_zero_consecutive} readings (3+ min): Clearing all {tracked_count} remaining orders")
                            self.active_orders.clear()
                            self._ws_zero_consecutive = 0
                    else:
                        logger.debug(f"WebSocket=0 (reading #{self._ws_zero_consecutive}), keeping {tracked_count} recent orders")
                else:
                    # Remove stale orders progressively
                    stale_orders = [
                        (order_id, order_info) for order_id, order_info in self.active_orders.items()
                        if current_time - order_info['timestamp'] > 90  # 1.5 minutes old
                    ]
                    
                    stale_orders.sort(key=lambda x: x[1]['timestamp'])
                    orders_to_remove = stale_orders[:min(excess_count, len(stale_orders))]
                    
                    for order_id, _ in orders_to_remove:
                        self.active_orders.pop(order_id, None)
                        logger.info(f"🔄 Synced: Removed stale order {order_id} (>1.5min old)")
            
            elif real_count > tracked_count:
                logger.debug(f"📋 WebSocket shows {real_count - tracked_count} additional orders (normal - others' orders)")
                # Reset WebSocket zero counters since we have valid data
                if hasattr(self, '_ws_zero_consecutive'):
                    self._ws_zero_consecutive = 0
        else:
            # Orders are in sync
            if real_count > 0:
                logger.debug(f"📋 Orders in sync: {real_count} orders")
            # Reset WebSocket zero counters since sync is good
            if hasattr(self, '_ws_zero_consecutive'):
                self._ws_zero_consecutive = 0
    
    async def handle_order_lifecycle_event(self, event):
        """Handle order lifecycle events (fill, cancel, etc.)"""
        try:
            event_type = event.get('type', '').lower()
            order_id = str(event.get('order_id', ''))
            
            if event_type in ['fill', 'partial_fill', 'cancel', 'cancelled']:
                # Remove filled or cancelled orders from tracking
                if order_id in self.active_orders:
                    order_info = self.active_orders.pop(order_id, None)
                    if order_info:
                        logger.info(f"🔄 Order {event_type}: Removed order {order_id} ({order_info['side']} {order_info['quantity']} @ {order_info['price']})")
                        
                        # Update positions for fills
                        if event_type in ['fill', 'partial_fill']:
                            await self.handle_order_fill(event, order_info)
            
        except Exception as e:
            logger.error(f"Failed to handle order lifecycle event: {e}")
    
    async def handle_order_fill(self, fill_event, order_info):
        """Handle order fill events and update positions"""
        try:
            side = order_info.get('side', '')
            position_type = order_info.get('position_type', '')
            fill_quantity = float(fill_event.get('fill_quantity', fill_event.get('quantity', 0)))
            fill_price = float(fill_event.get('fill_price', fill_event.get('price', 0)))
            
            logger.info(f"💰 Order filled: {side.upper()} {fill_quantity} {position_type} @ ${fill_price:.6f}")
            
            # Update positions based on fill
            if side == 'buy' and position_type == 'long':
                self.long_position += fill_quantity
            elif side == 'sell' and position_type == 'long':
                self.long_position = max(0, self.long_position - fill_quantity)
            elif side == 'sell' and position_type == 'short':
                self.short_position += fill_quantity
            elif side == 'buy' and position_type == 'short':
                self.short_position = max(0, self.short_position - fill_quantity)
            
            logger.info(f"💰 Position update - Long: {self.long_position}, Short: {self.short_position}")
            
        except Exception as e:
            logger.error(f"Failed to handle order fill: {e}")
    
    
    async def cancel_all_orders(self):
        """Cancel all orders (simplified)"""
        try:
            if self.dry_run:
                logger.info("🔄 DRY RUN - Would cancel all orders")
                cancelled_count = len(self.active_orders)
                self.active_orders.clear()
                logger.info(f"✅ DRY RUN: {cancelled_count} orders cancelled")
                return cancelled_count
            
            logger.info("🚫 Cancelling all orders...")
            
            # Clear internal tracking immediately to prevent displaying stale counts
            cancelled_count = len(self.active_orders)
            self.active_orders.clear()
            
            # Attempt actual cancellation with improved error handling
            try:
                result = await self.lighter.cancel_all_orders()
                
                # Handle different possible return formats from the API
                if result is None:
                    logger.warning("⚠️ Bulk cancellation returned None")
                elif isinstance(result, tuple):
                    if len(result) >= 2:
                        response, error = result[0], result[1]
                        if error is None:
                            logger.info(f"✅ {cancelled_count} orders cancelled successfully")
                        else:
                            logger.warning(f"⚠️ Cancellation error: {error}")
                    elif len(result) == 1:
                        # Single tuple element - could be success response
                        logger.info(f"✅ {cancelled_count} orders cancelled (single response)")
                    else:
                        logger.warning(f"⚠️ Unexpected tuple format: {result}")
                else:
                    # Single value returned - assume success
                    logger.info(f"✅ {cancelled_count} orders cancelled successfully")
                    
            except Exception as api_error:
                logger.warning(f"⚠️ API cancellation failed: {api_error}")
            
            return cancelled_count
            
        except Exception as e:
            logger.error(f"Cancel all orders failed: {e}")
            # Still clear tracking to prevent stale display
            cancelled_count = len(self.active_orders)
            self.active_orders.clear()
            return cancelled_count
    
    def force_cleanup_stale_orders(self):
        """Force cleanup of stale order tracking to prevent display issues"""
        try:
            current_time = time.time()
            initial_count = len(self.active_orders)
            
            # Conservative cleanup - only very old orders (5 minutes)
            stale_threshold = 300  # 5 minutes (was 2 minutes - too aggressive)
            
            stale_orders = [
                order_id for order_id, order_info in self.active_orders.items()
                if current_time - order_info['timestamp'] > stale_threshold
            ]
            
            # Remove truly stale orders
            for order_id in stale_orders:
                self.active_orders.pop(order_id, None)
            
            if stale_orders:
                logger.info(f"🔄 Force cleanup: Removed {len(stale_orders)} stale orders (>{stale_threshold}s old)")
            
            # Much more conservative WebSocket sync logic
            if len(self.active_orders) > 0 and hasattr(self, '_last_ws_order_count'):
                if not hasattr(self, '_ws_zero_count'):
                    self._ws_zero_count = 0
                    
                # Only count if WebSocket shows 0 AND we have many tracked orders
                if self._last_ws_order_count == 0 and len(self.active_orders) >= 6:  # Only when we have 6+ tracked orders
                    self._ws_zero_count += 1
                    
                    # Much higher threshold - only clear if consistently wrong for very long time
                    if self._ws_zero_count > 20:  # 20 cycles (~5 minutes of consistent mismatch)
                        remaining_count = len(self.active_orders)
                        if remaining_count > 4:  # Only clear if we have more than 4 tracked orders
                            logger.warning(f"🔄 WebSocket consistently 0 for >5min with {remaining_count} tracked orders: Force clearing excess")
                            # Only clear half the orders, not all
                            orders_to_clear = list(self.active_orders.keys())[:remaining_count//2]
                            for order_id in orders_to_clear:
                                self.active_orders.pop(order_id, None)
                            self._ws_zero_count = 0
                else:
                    # Reset counter more readily
                    if self._ws_zero_count > 0:
                        self._ws_zero_count = max(0, self._ws_zero_count - 1)
                
        except Exception as e:
            logger.error(f"Force cleanup failed: {e}")
    
    async def adjust_grid_strategy(self):
        """Main grid strategy logic"""
        try:
            # Update order status and simulate fills
            await self.update_positions()
            self.check_orders_status()
            await self.simulate_order_fills_in_dry_run()
            
            # Cleanup very old orders (likely orphaned)
            current_time = time.time()
            expired_orders = [
                order_id for order_id, order_info in self.active_orders.items()
                if current_time - order_info['timestamp'] > 1800  # 30 minutes
            ]
            for order_id in expired_orders:
                logger.info(f"🔄 Cleaning up very old order (likely orphaned): {order_id}")
                self.active_orders.pop(order_id, None)
            
            # Periodic order status validation and WebSocket health monitoring
            if int(current_time) % 30 == 0:  # Every 30 seconds
                await self.validate_order_tracking()
                await self.monitor_websocket_health()
            
            # Order management with limits
            active_count = len(self.active_orders)
            if active_count >= self.max_orders:
                logger.warning(f"Max orders ({self.max_orders}) reached, skipping new orders")
                return
            
            # Grid strategy logic
            if self.long_position == 0:
                # No long position - place entry order if we don't have too many buy orders
                long_buy_orders = [o for o in self.active_orders.values() 
                                 if o['position_type'] == 'long' and o['side'] == 'buy']
                
                if len(long_buy_orders) < 2:  # Allow up to 2 buy orders for better grid coverage
                    logger.info("No long position - placing long entry order")
                    entry_price = self.latest_price * (1 - self.grid_spacing)
                    order_quantity = self.calculate_order_quantity(entry_price)
                    result = await self.place_order('buy', entry_price, order_quantity, 'long')
                    if result:
                        logger.info(f"✅ Long entry order placed at ${entry_price:.6f}")
                else:
                    logger.debug(f"Long position=0 but {len(long_buy_orders)} buy orders exist, waiting for fill")
            else:
                # Have long position - place exit orders if we don't have enough sell orders
                long_sell_orders = [o for o in self.active_orders.values() 
                                  if o['position_type'] == 'long' and o['side'] == 'sell']
                
                if len(long_sell_orders) < 2:  # Allow up to 2 sell orders for better grid coverage
                    logger.info("Have long position - placing long exit order")
                    exit_price = self.latest_price * (1 + self.grid_spacing)
                    order_quantity = self.calculate_order_quantity(exit_price)
                    result = await self.place_order('sell', exit_price, order_quantity, 'long')
                    if result:
                        logger.info(f"✅ Long exit order placed at ${exit_price:.6f}")
                else:
                    logger.debug(f"Long orders sufficient: {len(long_sell_orders)} sell orders exist")
            
            # Short position management - simplified logic
            if self.short_position == 0:
                # No short position - place entry order if we don't have too many sell orders
                short_sell_orders = [o for o in self.active_orders.values() 
                                   if o['position_type'] == 'short' and o['side'] == 'sell']
                
                if len(short_sell_orders) < 2:  # Allow up to 2 sell orders for better grid coverage
                    logger.info("No short position - placing short entry order")
                    entry_price = self.latest_price * (1 + self.grid_spacing)
                    order_quantity = self.calculate_order_quantity(entry_price)
                    result = await self.place_order('sell', entry_price, order_quantity, 'short')
                    if result:
                        logger.info(f"✅ Short entry order placed at ${entry_price:.6f}")
                else:
                    logger.debug(f"Short position=0 but {len(short_sell_orders)} sell orders exist, waiting for fill")
            else:
                # Have short position - place exit orders if we don't have enough buy orders
                short_buy_orders = [o for o in self.active_orders.values() 
                                  if o['position_type'] == 'short' and o['side'] == 'buy']
                
                if len(short_buy_orders) < 2:  # Allow up to 2 buy orders for better grid coverage
                    logger.info("Have short position - placing short exit order")
                    exit_price = self.latest_price * (1 - self.grid_spacing)
                    order_quantity = self.calculate_order_quantity(exit_price)
                    result = await self.place_order('buy', exit_price, order_quantity, 'short')
                    if result:
                        logger.info(f"✅ Short exit order placed at ${exit_price:.6f}")
                else:
                    logger.debug(f"Short orders sufficient: {len(short_buy_orders)} buy orders exist")
                    
        except Exception as e:
            logger.error(f"Grid strategy failed: {e}")
    
    async def simulate_order_fills_in_dry_run(self):
        """Simulate order fills in dry run mode based on price movement"""
        if not self.dry_run or not self.active_orders:
            return
            
        current_time = time.time()
        orders_to_fill = []
        
        for order_id, order_info in self.active_orders.items():
            order_price = order_info['price']
            side = order_info['side']
            position_type = order_info['position_type']
            quantity = order_info['quantity']
            
            # Check if order should be filled based on current price
            should_fill = False
            
            if side == 'buy' and self.latest_price <= order_price:
                should_fill = True  # Buy order filled when price drops to or below order price
            elif side == 'sell' and self.latest_price >= order_price:
                should_fill = True  # Sell order filled when price rises to or above order price
            
            # Add some randomness to simulate partial market liquidity (30% chance of fill when price touches)
            if should_fill and (current_time - order_info['timestamp']) > 5:  # At least 5 seconds old
                import random
                if random.random() < 0.3:  # 30% chance of fill
                    orders_to_fill.append((order_id, order_info))
        
        # Process fills
        for order_id, order_info in orders_to_fill:
            side = order_info['side']
            position_type = order_info['position_type']
            quantity = order_info['quantity']
            price = order_info['price']
            
            logger.info(f"🎯 DRY RUN FILL - {side.upper()} {quantity} {position_type} @ ${price:.6f}")
            
            # Update positions
            if side == 'buy' and position_type == 'long':
                self.long_position += quantity
            elif side == 'sell' and position_type == 'long':
                self.long_position = max(0, self.long_position - quantity)
            elif side == 'sell' and position_type == 'short':
                self.short_position += quantity
            elif side == 'buy' and position_type == 'short':
                self.short_position = max(0, self.short_position - quantity)
            
            # Remove filled order
            self.active_orders.pop(order_id, None)
            
            logger.info(f"💰 Position update - Long: {self.long_position}, Short: {self.short_position}")
        
        if orders_to_fill:
            # Update order counters after fills
            self.check_orders_status()
    
    async def monitor_websocket_health(self):
        """Monitor WebSocket connection health and take corrective actions"""
        try:
            current_time = time.time()
            if current_time - self._last_ws_health_check < self._ws_health_check_interval:
                return  # Too soon for next health check
            
            self._last_ws_health_check = current_time
            
            # Check if we're receiving account updates
            if self._last_account_update_time is not None:
                time_since_update = current_time - self._last_account_update_time
                
                if time_since_update > 120:  # No updates for 2 minutes
                    self._ws_connection_failures += 1
                    logger.warning(f"⚠️ WebSocket health check failed: No updates for {time_since_update:.0f}s (failures: {self._ws_connection_failures}/{self._max_ws_connection_failures})")
                    
                    if self._ws_connection_failures >= self._max_ws_connection_failures:
                        logger.error("🚑 WebSocket appears to be unhealthy, using force cleanup mode")
                        
                        # Clear very old orders when WebSocket is unhealthy
                        very_old_orders = [
                            order_id for order_id, order_info in self.active_orders.items()
                            if current_time - order_info['timestamp'] > 180  # 3+ minutes old
                        ]
                        
                        if very_old_orders:
                            logger.info(f"🔄 WebSocket unhealthy: Clearing {len(very_old_orders)} old orders")
                            for order_id in very_old_orders:
                                self.active_orders.pop(order_id, None)
                else:
                    # WebSocket is healthy
                    if self._ws_connection_failures > 0:
                        logger.info(f"✅ WebSocket health recovered (last update: {time_since_update:.0f}s ago)")
                        self._ws_connection_failures = 0
            else:
                # No account updates received yet
                if self._ws_start_time and current_time - self._ws_start_time > 120:
                    logger.warning("⚠️ No WebSocket account updates received since startup")
                    self._ws_connection_failures += 1
        
        except Exception as e:
            logger.error(f"WebSocket health monitoring failed: {e}")
    
    async def validate_order_tracking(self):
        """Validate order tracking with conservative cleanup"""
        try:
            if self.dry_run:
                return
            
            current_time = time.time()
            
            # Conservative cleanup - only when we have excessive orders
            tracked_count = len(self.active_orders)
            if tracked_count > 8:  # Only when we have way too many
                logger.warning(f"🔍 Emergency cleanup: {tracked_count} tracked orders")
                # Only remove orders older than 10 minutes in emergency
                very_old_orders = [
                    (order_id, order_info) for order_id, order_info in self.active_orders.items()
                    if current_time - order_info['timestamp'] > 600  # 10+ minutes old
                ]
                
                if very_old_orders:
                    very_old_orders.sort(key=lambda x: x[1]['timestamp'])
                    for order_id, _ in very_old_orders[:3]:  # Remove max 3 at a time
                        logger.info(f"🔄 Emergency cleanup: removing very old order {order_id}")
                        self.active_orders.pop(order_id, None)
                else:
                    logger.warning(f"All {tracked_count} orders are recent - possible real orders, keeping them")
                
        except Exception as e:
            logger.error(f"Failed to validate order tracking: {e}")
    
    async def graceful_shutdown(self):
        """Graceful shutdown"""
        logger.info("🛑 Initiating graceful shutdown...")
        self.shutdown_requested = True
        
        try:
            cancelled_count = await self.cancel_all_orders()
            logger.info(f"✅ Shutdown complete - {cancelled_count} orders cancelled")
        except Exception as e:
            logger.error(f"Shutdown failed: {e}")
    
    async def run_websocket_mode(self):
        """Run WebSocket in background with enhanced error handling"""
        retry_delay = 3
        max_retries = 10  # Increased retries
        retry_count = 0
        
        while not self.shutdown_requested:
            try:
                logger.info("🌐 Starting WebSocket connection...")
                self.ws_connected = True
                retry_count = 0  # Reset on successful connection
                await self.ws_client.run_async()
                self.ws_connected = False
                logger.warning("WebSocket connection closed, reconnecting...")
            except Exception as e:
                self.ws_connected = False
                
                # Filter out non-critical errors
                error_msg = str(e).lower()
                is_critical = not any(keyword in error_msg for keyword in [
                    'ping', 'pong', 'unhandled message', 'connection reset', 
                    'connection closed', 'timeout', 'temporary failure'
                ])
                
                if is_critical:
                    retry_count += 1
                    logger.error(f"WebSocket critical error: {e}")
                else:
                    logger.debug(f"WebSocket non-critical error: {e}")
                
                if retry_count < max_retries:
                    wait_time = min(retry_delay * min(retry_count, 3), 30)  # Cap at 30s
                    logger.info(f"Retrying WebSocket in {wait_time}s (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning("❌ WebSocket max retries reached, continuing without WebSocket")
                    # Don't shutdown, continue with periodic price fetching
                    await asyncio.sleep(60)  # Wait before trying again
                    retry_count = 0  # Reset retry count
    
    async def run(self):
        """Main trading loop (simplified)"""
        mode_str = "DRY RUN" if self.dry_run else "LIVE TRADING"
        logger.info(f"🚀 Starting Simplified Grid Bot ({mode_str})")
        logger.info(f"Symbol: {self.symbol}, Leverage: {self.leverage}x, Grid: {self.grid_spacing*100:.2f}%")
        
        # Initialize WebSocket
        await self.init_websocket()
        
        # Start WebSocket in background
        ws_task = asyncio.create_task(self.run_websocket_mode())
        
        # Wait for initial price data
        logger.info("Waiting for initial price data...")
        timeout = 10
        start_time = time.time()
        
        while self.latest_price == 0 and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.5)
        
        if self.latest_price == 0:
            logger.error("❌ Failed to receive price data")
            ws_task.cancel()
            raise RuntimeError("Price data is required")
        
        logger.info(f"✅ Initial price: ${self.latest_price:.6f}")
        
        # Main trading loop
        try:
            while not self.shutdown_requested:
                try:
                    if self.price_updated or True:  # Run periodically
                        logger.info(f"Price: ${self.latest_price:.6f} (Bid: ${self.best_bid_price:.6f}, Ask: ${self.best_ask_price:.6f})")
                        logger.info(f"Positions: Long={self.long_position}, Short={self.short_position}")
                        
                        # Force cleanup of stale order tracking before displaying count
                        self.force_cleanup_stale_orders()
                        
                        # Periodic API sync (every 5 minutes) as backup to WebSocket
                        current_time = time.time()
                        if not hasattr(self, '_last_api_sync') or current_time - self._last_api_sync > 300:  # 5 minutes
                            logger.info("🔄 Performing periodic API sync...")
                            await self.sync_orders_from_api()
                            self._last_api_sync = current_time
                        
                        accurate_count = len(self.active_orders)
                        logger.info(f"Active orders: {accurate_count}")
                        
                        await self.adjust_grid_strategy()
                        self.price_updated = False
                    
                    # Sleep with responsive shutdown
                    for _ in range(UPDATE_INTERVAL * 2):
                        if self.shutdown_requested:
                            break
                        await asyncio.sleep(0.5)
                    
                except KeyboardInterrupt:
                    logger.info("Received interrupt signal")
                    self.shutdown_requested = True
                    break
                except Exception as e:
                    logger.error(f"Main loop error: {e}")
                    if not self.shutdown_requested:
                        await asyncio.sleep(5)
        finally:
            if self.shutdown_requested:
                await self.graceful_shutdown()
        
        # Cleanup
        logger.info("Cleaning up...")
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        
        if self.lighter:
            await self.lighter.cleanup()
        logger.info("✅ Bot stopped gracefully")

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Simplified Lighter Grid Bot')
    parser.add_argument('--dry-run', action='store_true', help='Run in simulation mode')
    parser.add_argument('--symbol', default=COIN_NAME, help=f'Trading symbol (default: {COIN_NAME})')
    parser.add_argument('--order-amount', type=float, default=DEFAULT_ORDER_AMOUNT, 
                       help=f'Order amount in USD (default: ${DEFAULT_ORDER_AMOUNT})')
    return parser.parse_args()

async def main():
    """Main function with signal handling"""
    args = parse_arguments()
    
    # Override symbol if provided
    global COIN_NAME
    if args.symbol != COIN_NAME:
        COIN_NAME = args.symbol
        logger.info(f"Using symbol: {COIN_NAME}")
    
    # Create bot instance
    bot = SimplifiedGridBot(dry_run=args.dry_run, order_amount=args.order_amount)
    
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
        
        # Skip confirmation for easier debugging
        logger.info("⚠️ DEBUG MODE: Skipping confirmation for easier debugging")
    
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
    print(f"🤖 Simplified Lighter Grid Bot ({mode_str})")
    print(f"📊 Symbol: {args.symbol}, Leverage: {LEVERAGE}x, Grid: {GRID_SPACING*100}%")
    print(f"💰 Order Amount: ${args.order_amount} USD per order")
    print("=" * 50)
    
    asyncio.run(main())
