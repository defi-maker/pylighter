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
INITIAL_QUANTITY = 3        # Base quantity (will be adjusted)
LEVERAGE = 5                # Leverage for TON (conservative vs OKX's 50x)
POSITION_THRESHOLD = 60     # Position threshold
POSITION_LIMIT = 20         # Position limit
SYNC_TIME = 10              # Sync interval (seconds)
ORDER_FIRST_TIME = 10       # Order placement interval
UPDATE_INTERVAL = 5         # Price update interval
MAX_ACTIVE_ORDERS = 8       # Maximum active orders

# 💡 Lighter Protocol Ultra-High Frequency Advantage:
# - 0% Maker fees + 0% Taker fees = Pure profit on every trade!
# - 0.02% grid spacing = 100x more frequent than traditional exchanges
# - OKX needs 0.4% to cover fees, we only need 0.02% for scalping profits!
# - Expected trades: Every small price movement = potential profit

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
    
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.lighter = None
        self.ws_client = None
        self.symbol = COIN_NAME
        self.market_id = None
        self.grid_spacing = GRID_SPACING
        self.leverage = LEVERAGE
        
        # Shutdown control
        self.shutdown_requested = False
        
        # Market constraints
        self.min_quote_amount = 10.0
        self.price_precision = 6
        self.amount_precision = 1
        
        # Position tracking (enhanced with OKX-style order counting)
        self.long_position = 0
        self.short_position = 0
        self.long_initial_quantity = INITIAL_QUANTITY
        self.short_initial_quantity = INITIAL_QUANTITY
        
        # Order counting (OKX-style)
        self.buy_long_orders = 0.0    # Long buy orders count
        self.sell_long_orders = 0.0   # Long sell orders count
        self.sell_short_orders = 0.0  # Short sell orders count
        self.buy_short_orders = 0.0   # Short buy orders count
        
        # Price tracking
        self.latest_price = 0
        self.best_bid_price = None
        self.best_ask_price = None
        self.price_updated = False
        
        # Order tracking (simplified)
        self.active_orders = {}  # order_id -> order_info
        self.last_long_order_time = 0
        self.last_short_order_time = 0
        self.last_position_update_time = 0
        
        # WebSocket connection status
        self.ws_connected = False
        self.account_ws_client = None  # Official lighter WebSocket client for account updates
        
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
        
    async def fetch_market_constraints(self):
        """Fetch market constraints"""
        try:
            constraints = await self.lighter.get_market_constraints(self.symbol)
            self.min_quote_amount = constraints['min_quote_amount']
            self.price_precision = constraints['price_precision']
            self.amount_precision = constraints['amount_precision']
            logger.info(f"Constraints: min_quote=${self.min_quote_amount}, price_precision={self.price_precision}")
        except Exception as e:
            logger.warning(f"Failed to fetch constraints: {e}, using defaults")
            self.min_quote_amount = 10.0
            self.price_precision = 6
            self.amount_precision = 1
    
    async def init_websocket(self):
        """Initialize WebSocket client for price updates"""
        logger.info("Initializing WebSocket client...")
        try:
            async def handle_ping_pong(websocket, message_data):
                """Handle ping/pong messages with proper async response"""
                try:
                    if isinstance(message_data, dict):
                        message_type = message_data.get('type', '')
                        if message_type == 'ping':
                            # Send pong response immediately
                            pong_response = {"type": "pong"}
                            await websocket.send(json.dumps(pong_response))
                            logger.debug("Sent pong response to WebSocket ping")
                            return True
                        elif message_type == 'pong':
                            logger.debug("Received pong response from WebSocket")
                            return True
                    return False
                except Exception as e:
                    logger.debug(f"Error handling ping/pong: {e}")
                    return False
            
            def on_order_book_update(market_id, order_book):
                try:
                    # Enhanced ping/pong handling
                    if isinstance(order_book, dict):
                        message_type = order_book.get('type', '')
                        if message_type in ['ping', 'pong']:
                            # Create async task for ping/pong handling
                            if hasattr(self, 'ws_client') and hasattr(self.ws_client, '_websocket'):
                                asyncio.create_task(handle_ping_pong(self.ws_client._websocket, order_book))
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
                    # Filter out non-critical ping/pong messages
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ['ping', 'pong', 'unhandled message', 'connection']):
                        logger.debug(f"WebSocket keep-alive message (non-critical): {e}")
                    else:
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
    
    def update_initial_quantities(self):
        """Update quantities based on current price"""
        if self.latest_price > 0:
            base_quantity = self.lighter.calculate_min_quantity_for_quote_amount(
                self.latest_price, self.min_quote_amount, self.symbol
            )
            self.long_initial_quantity = base_quantity
            self.short_initial_quantity = base_quantity
            logger.info(f"Updated quantities based on price ${self.latest_price:.6f}: {base_quantity:.1f} {self.symbol}")
    
    async def update_positions(self):
        """Update current positions (simplified)"""
        # In a real implementation, you would fetch actual positions
        # For now, we track internally through order fills
        current_time = time.time()
        if current_time - self.last_position_update_time > SYNC_TIME:
            # Periodically reset for safety in dry run
            if self.dry_run:
                self.long_position = 0
                self.short_position = 0
            self.last_position_update_time = current_time
    
    def check_orders_status(self):
        """Check current order status and update counters (OKX-style)"""
        # Reset counters
        self.buy_long_orders = 0.0
        self.sell_long_orders = 0.0
        self.sell_short_orders = 0.0
        self.buy_short_orders = 0.0
        
        # Count active orders by type
        for order_id, order_info in self.active_orders.items():
            side = order_info.get('side', '')
            position_type = order_info.get('position_type', '')
            quantity = order_info.get('quantity', 0)
            
            if side == 'buy' and position_type == 'long':
                self.buy_long_orders += quantity
            elif side == 'sell' and position_type == 'long':
                self.sell_long_orders += quantity
            elif side == 'sell' and position_type == 'short':
                self.sell_short_orders += quantity
            elif side == 'buy' and position_type == 'short':
                self.buy_short_orders += quantity
        
        logger.debug(f"Order counts: Long(buy={self.buy_long_orders:.1f}, sell={self.sell_long_orders:.1f}), Short(sell={self.sell_short_orders:.1f}, buy={self.buy_short_orders:.1f})")
    
    async def place_order(self, side, price, quantity, position_type='long'):
        """Place an order (simplified)"""
        try:
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
                
                # Track order (simplified)
                self.active_orders[order_id] = {
                    'side': side,
                    'price': formatted_price,
                    'quantity': abs(quantity),
                    'position_type': position_type,
                    'timestamp': time.time(),
                    'tx_hash': str(tx_hash) if tx_hash else None
                }
                logger.info(f"✅ Order placed: {order_id}")
                
                # Update cooldowns
                if position_type == 'long':
                    self.last_long_order_time = time.time()
                else:
                    self.last_short_order_time = time.time()
                
                return order_id
            else:
                logger.error(f"Unexpected result format: {result}")
                return None
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None
    
    async def setup_account_orders_websocket(self):
        """Setup WebSocket subscription using official lighter.WsClient"""
        try:
            if self.dry_run:
                logger.info("🔄 DRY RUN - Would setup account orders WebSocket")
                return
                
            import lighter
            
            logger.info("🔌 Setting up account orders WebSocket using official WsClient...")
            
            def on_account_update(account_id, account_data):
                """Handle account updates from WebSocket"""
                try:
                    # Process account updates for order fills
                    asyncio.create_task(self.handle_account_update(account_id, account_data))
                except Exception as e:
                    logger.error(f"Error in account update handler: {e}")
            
            def on_order_book_update(market_id, order_book):
                """Handle order book updates (not used for order tracking)"""
                pass
            
            # Create custom WebSocket client that handles ping messages
            class PingHandlingWsClient(lighter.WsClient):
                async def handle_ping_message(self, websocket, message):
                    """Handle ping messages with proper pong response"""
                    try:
                        if isinstance(message, dict):
                            message_type = message.get('type', '')
                            if message_type == 'ping':
                                # Send pong response immediately
                                pong_response = {"type": "pong"}
                                await websocket.send(json.dumps(pong_response))
                                logger.debug("Account WebSocket: Sent pong response to ping")
                                return True
                            elif message_type == 'pong':
                                logger.debug("Account WebSocket: Received pong response")
                                return True
                        return False
                    except Exception as e:
                        logger.debug(f"Account WebSocket ping/pong error: {e}")
                        return False
                
                def handle_unhandled_message(self, message):
                    """Override to handle ping messages gracefully"""
                    try:
                        message_type = message.get('type', '') if isinstance(message, dict) else ''
                        if message_type in ['ping', 'pong']:
                            # Create async task for ping/pong handling if we have websocket access
                            if hasattr(self, '_websocket') and self._websocket:
                                asyncio.create_task(self.handle_ping_message(self._websocket, message))
                            else:
                                logger.debug(f"Account WebSocket: Received {message_type} (no websocket access)")
                            return
                        else:
                            # Log other unhandled messages but don't raise exception
                            logger.warning(f"Unhandled account WebSocket message: {message}")
                    except Exception as e:
                        logger.debug(f"Error handling unhandled message: {e}")
            
            # Create WebSocket client with account subscription
            self.account_ws_client = PingHandlingWsClient(
                order_book_ids=[],  # We don't need order book updates for order tracking
                account_ids=[self.lighter.account_idx],  # Subscribe to our account
                on_order_book_update=on_order_book_update,
                on_account_update=on_account_update,
            )
            
            # Start WebSocket in background
            async def run_account_websocket():
                max_retries = 5
                retry_count = 0
                
                while retry_count < max_retries and not self.shutdown_requested:
                    try:
                        logger.info("🌐 Starting account WebSocket connection...")
                        await self.account_ws_client.run_async()
                        retry_count = 0  # Reset on successful connection
                    except Exception as e:
                        error_msg = str(e).lower()
                        # Filter out ping/pong related errors
                        if any(keyword in error_msg for keyword in ['ping', 'pong', 'unhandled message']):
                            logger.debug(f"Account WebSocket keep-alive handling (non-critical): {e}")
                            retry_count = max(0, retry_count - 1)  # Don't count ping/pong errors
                        else:
                            logger.error(f"Account WebSocket error: {e}")
                            retry_count += 1
                        
                        if retry_count < max_retries:
                            wait_time = min(30, 5 * retry_count)
                            logger.info(f"⏳ Retrying account WebSocket in {wait_time}s")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.critical("🚨 Account WebSocket failed after max retries")
                            break
            
            # Start in background
            asyncio.create_task(run_account_websocket())
            logger.info("✅ Account WebSocket setup complete")
            
        except Exception as e:
            logger.error(f"Failed to setup account WebSocket: {e}")
    
    async def handle_account_update(self, account_id, account_data):
        """Handle account updates from official WebSocket client"""
        try:
            if str(account_id) != str(self.lighter.account_idx):
                return
                
            # Mark that we received an account update
            self._last_account_update_time = time.time()
            
            # Debug log the account update structure (only occasionally to reduce noise)
            if hasattr(self, '_debug_log_counter'):
                self._debug_log_counter += 1
            else:
                self._debug_log_counter = 0
                
            if self._debug_log_counter % 20 == 0:  # Log every 20th update
                logger.debug(f"Account update sample: {json.dumps(account_data, indent=2)}")
            
            # Check for order fills in account data
            message_type = account_data.get('type', '')
            
            if message_type == 'update/account_all':
                # Process position updates
                positions = account_data.get('positions', {})
                orders = account_data.get('orders', {})
                
                # Update positions for our market
                market_positions = positions.get(str(self.market_id), {})
                if market_positions:
                    long_size = float(market_positions.get('long_position_size', 0))
                    short_size = float(market_positions.get('short_position_size', 0))
                    
                    # Check for position changes (indicating fills)
                    if long_size != self.long_position or short_size != self.short_position:
                        logger.info(f"💰 Position update - Long: {self.long_position} → {long_size}, Short: {self.short_position} → {short_size}")
                        
                        # Clear related orders when position changes (indicating fills)
                        if long_size != self.long_position:
                            # Long position changed - clear related orders
                            long_orders_to_clear = [
                                order_id for order_id, order_info in self.active_orders.items()
                                if order_info['position_type'] == 'long'
                            ]
                            for order_id in long_orders_to_clear:
                                self.active_orders.pop(order_id, None)
                                logger.info(f"🔄 Cleared filled long order: {order_id}")
                        
                        if short_size != self.short_position:
                            # Short position changed - clear related orders
                            short_orders_to_clear = [
                                order_id for order_id, order_info in self.active_orders.items()
                                if order_info['position_type'] == 'short'
                            ]
                            for order_id in short_orders_to_clear:
                                self.active_orders.pop(order_id, None)
                                logger.info(f"🔄 Cleared filled short order: {order_id}")
                        
                        self.long_position = long_size
                        self.short_position = short_size
                
                # Process order updates - sync with WebSocket order data
                market_orders = orders.get(str(self.market_id), {})
                if market_orders:
                    # Count REAL active orders from WebSocket
                    real_active_orders = []
                    for order_id, order_info in market_orders.items():
                        status = order_info.get('status', '').lower()
                        if status in ['active', 'open', 'pending']:
                            real_active_orders.append(order_id)
                    
                    real_count = len(real_active_orders)
                    tracked_count = len(self.active_orders)
                    
                    logger.info(f"📋 WebSocket: {real_count} real orders, {tracked_count} tracked")
                    
                    # Sync our internal tracking with WebSocket reality
                    if real_count != tracked_count:
                        logger.warning(f"🔄 Order sync: WebSocket={real_count}, Tracked={tracked_count}")
                        
                        # If WebSocket shows fewer orders, clear excess tracking
                        if real_count < tracked_count:
                            excess_count = tracked_count - real_count
                            oldest_orders = sorted(
                                self.active_orders.items(),
                                key=lambda x: x[1]['timestamp']
                            )[:excess_count]
                            
                            for order_id, _ in oldest_orders:
                                self.active_orders.pop(order_id, None)
                                logger.info(f"🔄 Synced: Removed phantom order {order_id}")
                        
                        # If WebSocket shows more orders, it means some orders exist that we're not tracking
                        # This is normal - we only track orders we placed ourselves
                        elif real_count > tracked_count:
                            logger.info(f"📋 WebSocket shows {real_count - tracked_count} additional orders (normal)")
                            
        except Exception as e:
            logger.error(f"Failed to handle account update: {e}")
    
    async def get_order_status_via_websocket(self):
        """Get order status via WebSocket updates only (no deprecated API calls)"""
        try:
            if self.dry_run:
                return
                
            # Pure WebSocket-based tracking - no API calls needed
            # Order status is updated through handle_account_update
            logger.debug(f"WebSocket tracking: {len(self.active_orders)} active orders")
            
        except Exception as e:
            logger.error(f"Failed to check order status via WebSocket: {e}")
    
    async def handle_account_orders_update(self, data):
        """Legacy method - now handled by official WebSocket client"""
        pass
    
    async def process_order_update(self, order):
        """Legacy method - now handled by official WebSocket client"""
        pass
    
    async def cancel_all_orders(self):
        """Cancel all orders (simplified)"""
        try:
            if self.dry_run:
                logger.info("🔄 DRY RUN - Would cancel all orders")
                cancelled_count = len(self.active_orders)
                self.active_orders.clear()
                return cancelled_count
            
            logger.info("🚫 Cancelling all orders...")
            result = await self.lighter.cancel_all_orders()
            
            if result and len(result) >= 2:
                response, error = result
                if error is None:
                    cancelled_count = len(self.active_orders)
                    self.active_orders.clear()
                    logger.info(f"✅ {cancelled_count} orders cancelled")
                    return cancelled_count
            
            logger.warning("⚠️ Bulk cancellation may have failed")
            return 0
            
        except Exception as e:
            logger.error(f"Cancel all orders failed: {e}")
            return 0
    
    def should_place_long_order(self):
        """Check if we should place long orders"""
        current_time = time.time()
        
        # Reduced cooldown time for more responsive trading
        cooldown_time = 5  # Reduced from 10 seconds
        if current_time - self.last_long_order_time < cooldown_time:
            return False
        
        # Check if we already have long orders
        long_orders = [o for o in self.active_orders.values() 
                      if o['position_type'] == 'long']
        
        if self.long_position == 0:
            # Need entry order - check if we don't have any buy orders
            return len([o for o in long_orders if o['side'] == 'buy']) == 0
        else:
            # Need exit order - check if we don't have any sell orders
            return len([o for o in long_orders if o['side'] == 'sell']) == 0
    
    def should_place_short_order(self):
        """Check if we should place short orders"""
        current_time = time.time()
        
        # Reduced cooldown time for more responsive trading
        cooldown_time = 5  # Reduced from 10 seconds
        if current_time - self.last_short_order_time < cooldown_time:
            return False
        
        # Check if we already have short orders
        short_orders = [o for o in self.active_orders.values() 
                       if o['position_type'] == 'short']
        
        if self.short_position == 0:
            # Need entry order - check if we don't have any sell orders
            return len([o for o in short_orders if o['side'] == 'sell']) == 0
        else:
            # Need exit order - check if we don't have any buy orders
            return len([o for o in short_orders if o['side'] == 'buy']) == 0
    
    async def adjust_grid_strategy(self):
        """Main grid strategy logic (OKX-enhanced)"""
        try:
            # Update positions periodically
            await self.update_positions()
            
            # Update order status FIRST - this is critical for OKX-style logic
            self.check_orders_status()
            
            # Simulate order fills in dry run mode
            await self.simulate_order_fills_in_dry_run()
            
            # Only clean up EXTREMELY old orders (likely orphaned) - give orders time to fill
            current_time = time.time()
            expired_orders = [
                order_id for order_id, order_info in self.active_orders.items()
                if current_time - order_info['timestamp'] > 1800  # 30 minutes instead of 2 minutes
            ]
            for order_id in expired_orders:
                logger.info(f"🔄 Cleaning up very old order (likely orphaned): {order_id}")
                self.active_orders.pop(order_id, None)
            
            # Periodic order status validation
            if int(current_time) % 30 == 0:  # Every 30 seconds
                await self.validate_order_tracking()
            
            # Check if we need to place orders
            active_count = len(self.active_orders)
            if active_count >= MAX_ACTIVE_ORDERS:
                logger.warning(f"Too many active orders ({active_count}), cleaning up first")
                # Force cleanup if too many orders
                oldest_orders = sorted(self.active_orders.items(), key=lambda x: x[1]['timestamp'])[:2]
                for order_id, _ in oldest_orders:
                    logger.info(f"🔄 Force removing old order: {order_id}")
                    self.active_orders.pop(order_id, None)
                return
            
            # Long position management - improved logic to prevent duplicate orders
            if self.long_position == 0:
                # Check if we already have active long entry orders
                long_buy_orders = [o for o in self.active_orders.values() 
                                 if o['position_type'] == 'long' and o['side'] == 'buy']
                
                if len(long_buy_orders) == 0:
                    logger.info("No long position and no buy orders - placing long entry order")
                    entry_price = self.latest_price * (1 - self.grid_spacing)
                    result = await self.place_order('buy', entry_price, self.long_initial_quantity, 'long')
                    if result:
                        logger.info(f"✅ Long entry order placed at ${entry_price:.6f}")
                else:
                    logger.debug(f"Long position=0 but {len(long_buy_orders)} buy orders exist, waiting for fill")
            else:
                # Check if orders are valid (OKX logic)
                orders_valid = not (0 < self.buy_long_orders <= self.long_initial_quantity) or \
                               not (0 < self.sell_long_orders <= self.long_initial_quantity)
                if orders_valid:
                    logger.info("Long orders invalid, placing orders")
                    if self.long_position > 0:
                        # Place exit order (take profit) using full grid spacing
                        exit_price = self.latest_price * (1 + self.grid_spacing)  # Full grid spacing
                        result = await self.place_order('sell', exit_price, self.long_initial_quantity, 'long')
                        if result:
                            logger.info(f"✅ Long exit order placed at ${exit_price:.6f}")
                else:
                    logger.debug(f"Long orders valid: buy={self.buy_long_orders:.1f}, sell={self.sell_long_orders:.1f}")
            
            # Short position management - improved logic to prevent duplicate orders
            if self.short_position == 0:
                # Check if we already have active short entry orders
                short_sell_orders = [o for o in self.active_orders.values() 
                                   if o['position_type'] == 'short' and o['side'] == 'sell']
                
                if len(short_sell_orders) == 0:
                    logger.info("No short position and no sell orders - placing short entry order")
                    entry_price = self.latest_price * (1 + self.grid_spacing)
                    result = await self.place_order('sell', entry_price, self.short_initial_quantity, 'short')
                    if result:
                        logger.info(f"✅ Short entry order placed at ${entry_price:.6f}")
                else:
                    logger.debug(f"Short position=0 but {len(short_sell_orders)} sell orders exist, waiting for fill")
            else:
                # Check if orders are valid (OKX logic)
                orders_valid = not (0 < self.sell_short_orders <= self.short_initial_quantity) or \
                               not (0 < self.buy_short_orders <= self.short_initial_quantity)
                if orders_valid:
                    logger.info("Short orders invalid, placing orders")
                    if self.short_position > 0:
                        # Place exit order (take profit) using full grid spacing
                        exit_price = self.latest_price * (1 - self.grid_spacing)  # Full grid spacing
                        result = await self.place_order('buy', exit_price, self.short_initial_quantity, 'short')
                        if result:
                            logger.info(f"✅ Short exit order placed at ${exit_price:.6f}")
                else:
                    logger.debug(f"Short orders valid: sell={self.sell_short_orders:.1f}, buy={self.buy_short_orders:.1f}")
                    
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
    
    async def validate_order_tracking(self):
        try:
            if self.dry_run:
                return
                
            # WebSocket-only validation - check if we have recent account updates
            current_time = time.time()
            
            # If we haven't received account updates recently, our tracking might be stale
            if hasattr(self, '_last_account_update_time'):
                time_since_update = current_time - self._last_account_update_time
                if time_since_update > 60:  # No updates for 1 minute
                    logger.warning(f"⚠️ No account WebSocket updates for {time_since_update:.0f}s - tracking may be stale")
                    # Conservative cleanup - only remove very old orders
                    very_old_orders = [
                        order_id for order_id, order_info in self.active_orders.items()
                        if current_time - order_info['timestamp'] > 300  # 5+ minutes old
                    ]
                    for order_id in very_old_orders:
                        logger.info(f"🔄 Removing very old order (no WebSocket updates): {order_id}")
                        self.active_orders.pop(order_id, None)
            
            # Track internal consistency
            tracked_count = len(self.active_orders)
            if tracked_count > 4:  # If we have too many tracked orders
                logger.warning(f"🔍 Too many tracked orders ({tracked_count}), cleaning oldest")
                oldest_orders = sorted(self.active_orders.items(), key=lambda x: x[1]['timestamp'])[:2]
                for order_id, _ in oldest_orders:
                    logger.info(f"🔄 Removing oldest tracked order: {order_id}")
                    self.active_orders.pop(order_id, None)
                
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
                        logger.info(f"Active orders: {len(self.active_orders)}")
                        
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
    bot = SimplifiedGridBot(dry_run=args.dry_run)
    
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
    print(f"🤖 Simplified Lighter Grid Bot ({mode_str})")
    print(f"📊 Symbol: {args.symbol}, Leverage: {LEVERAGE}x, Grid: {GRID_SPACING*100}%")
    print("=" * 50)
    
    asyncio.run(main())
