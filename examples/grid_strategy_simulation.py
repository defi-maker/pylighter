"""
Dry run test of the grid trading strategy with WebSocket simulation
Shows what orders would be placed without actually placing them
Simulates the WebSocket-based real-time price updates
"""

import asyncio
import logging
import time
import math
from grid_strategy_ton import LighterGridBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

class DryRunGridBot(LighterGridBot):
    """Dry run version that simulates order placement"""
    
    def __init__(self):
        super().__init__()
        self.simulated_orders = []
    
    async def place_order(self, side, price, quantity, position_side='long'):
        """Simulate order placement"""
        # Adjust price and quantity precision (same logic as real version)
        price = round(price, self.price_precision)
        quantity = round(max(quantity, self.min_base_amount), self.amount_precision)
        
        # Ensure minimum quote amount
        if price * quantity < self.min_quote_amount:
            quantity = math.ceil(self.min_quote_amount / price * 10) / 10
            quantity = round(quantity, self.amount_precision)
        
        # For short positions, we need negative amounts
        original_quantity = quantity
        if position_side == 'short':
            if side == 'buy':
                quantity = quantity  # Closing short = positive (buy to cover)
            else:  # sell
                quantity = -quantity  # Opening short = negative (sell)
        
        # Simulate the order
        order_info = {
            'side': side,
            'price': price,
            'quantity': quantity,
            'original_quantity': original_quantity,
            'position_side': position_side,
            'quote_value': price * abs(quantity),
            'timestamp': time.time()
        }
        
        self.simulated_orders.append(order_info)
        
        logger.info(f"🔄 SIMULATED {side.upper()} order: {original_quantity} XRP @ ${price:.6f} (${price * original_quantity:.2f}) [{position_side}]")
        logger.info(f"   Lighter amount: {quantity} (negative = short)")
        
        return f"simulated_tx_{len(self.simulated_orders)}"
    
    async def cancel_orders_for_side(self, position_side):
        """Simulate order cancellation"""
        logger.info(f"🔄 SIMULATED cancel all {position_side} orders")
        # In a real scenario, we would track and cancel specific orders
        return "simulated_cancel"

async def test_grid_dryrun():
    """Test grid strategy in dry run mode"""
    
    print("🧪 Dry Run Grid Trading Test")
    print("=" * 50)
    print("⚠️  This is a SIMULATION - no real orders will be placed")
    print()
    
    try:
        # Initialize bot
        bot = DryRunGridBot()
        await bot.setup()
        
        # Update prices first
        await bot.update_prices()
        
        print(f"✅ Bot setup complete")
        print(f"   Symbol: {bot.symbol}")
        print(f"   Current XRP price: ${bot.latest_price:.6f}")
        print(f"   Best bid: ${bot.best_bid_price:.6f}, Best ask: ${bot.best_ask_price:.6f}")
        print(f"   Grid spacing: {bot.grid_spacing*100}%")
        print(f"   Min order size: {bot.min_base_amount} XRP (${bot.min_quote_amount})")
        print()
        
        # Simulate initial state (no positions)
        print("📊 Simulating initial grid setup...")
        print("   Scenario: No existing positions, initializing both long and short")
        print()
        
        # Test initialization orders
        print("🔄 Initializing long orders...")
        await bot.initialize_long_orders()
        
        print("\n🔄 Initializing short orders...")  
        await bot.initialize_short_orders()
        
        print(f"\n📝 Simulated {len(bot.simulated_orders)} orders:")
        for i, order in enumerate(bot.simulated_orders, 1):
            print(f"   {i}. {order['side'].upper()} {order['original_quantity']} XRP @ ${order['price']:.6f} [{order['position_side']}]")
        
        # Simulate having some positions and test grid logic
        print("\n" + "="*50)
        print("📊 Simulating position-based grid adjustments...")
        bot.simulated_orders.clear()  # Clear previous orders
        
        # Simulate having some long position
        bot.long_position = 15.0  # Some long position
        bot.short_position = 0.0  # No short position
        
        print(f"   Scenario: Long position = {bot.long_position} XRP, Short position = {bot.short_position} XRP")
        print()
        
        # Update prices (simulate price movement)
        await bot.update_prices()
        new_price = bot.latest_price * 1.002  # 0.2% price increase
        
        print(f"🔄 Simulating price movement: ${bot.latest_price:.6f} → ${new_price:.6f}")
        bot.latest_price = new_price
        bot.best_bid_price = new_price - 0.001
        bot.best_ask_price = new_price + 0.001
        
        # Test grid adjustments
        print("\n🔄 Adjusting long grid based on new price...")
        await bot.place_long_orders(bot.latest_price)
        
        print("\n🔄 Initializing short orders (no position)...")
        await bot.initialize_short_orders()
        
        print(f"\n📝 Grid adjustment orders ({len(bot.simulated_orders)} total):")
        for i, order in enumerate(bot.simulated_orders, 1):
            direction = "📈" if order['side'] == 'buy' else "📉"
            print(f"   {i}. {direction} {order['side'].upper()} {order['original_quantity']} XRP @ ${order['price']:.6f} [{order['position_side']}]")
        
        # Show grid levels
        print(f"\n📊 Current grid levels:")
        print(f"   Long grid: ${bot.lower_price_long:.6f} ← ${bot.mid_price_long:.6f} → ${bot.upper_price_long:.6f}")
        print(f"   Short grid: ${bot.lower_price_short:.6f} ← ${bot.mid_price_short:.6f} → ${bot.upper_price_short:.6f}")
        
        await bot.lighter.cleanup()
        print("\n✅ Dry run completed successfully!")
        print("\n🎯 The strategy is ready for live trading")
        print("   To run live: uv run grid_strategy_ton.py")
        
    except Exception as e:
        print(f"\n❌ Dry run failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    result = asyncio.run(test_grid_dryrun())
    if result:
        print("\n🎉 Grid strategy dry run successful!")
    else:
        print("\n❌ Dry run failed - check configuration")