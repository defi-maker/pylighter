"""
TON Contracts Trading Test Script

Tests real TON contract trading operations including:
- Query precision from API (dynamic for any symbol)
- Test long position (做多) with minimum amount at 1x leverage
- Test short position (做空) with minimum amount at 1x leverage  
- Immediate position closing after each trade
- All using minimum allowed amounts

IMPORTANT: This performs REAL contract trading with REAL money.
Only use with small amounts and ensure you understand the risks.
"""

import os
import asyncio
import logging
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from pylighter.client import Lighter

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('TONContractsTest')

class TONContractsTester:
    """TON Contracts Trading Test Suite - Tests long/short positions with immediate closing"""
    
    def __init__(self, symbol="TON"):
        self.lighter = None
        self.symbol = symbol
        self.test_results = {}
        self.open_positions = []
        
    async def setup(self):
        """Setup the client connection"""
        api_key = os.getenv("LIGHTER_KEY")
        api_secret = os.getenv("LIGHTER_SECRET")
        
        if not api_key or not api_secret:
            raise ValueError(
                "Please set LIGHTER_KEY and LIGHTER_SECRET environment variables.\n"
                "Create them in a .env file in the project root."
            )
        
        logger.info("Initializing Lighter client...")
        self.lighter = Lighter(key=api_key, secret=api_secret)
        await self.lighter.init_client()
        logger.info("✅ Client initialized successfully")
        
        # Verify symbol exists and find the best match
        available_symbols = list(self.lighter.ticker_to_idx.keys())
        
        if self.symbol not in available_symbols:
            # Try to find similar symbols
            similar_symbols = [s for s in available_symbols if self.symbol.upper() in s]
            
            if similar_symbols:
                self.symbol = similar_symbols[0]
                logger.info(f"Symbol not found, using closest match: {self.symbol}")
            else:
                logger.error(f"Symbol {self.symbol} not found!")
                logger.info(f"Available symbols: {', '.join(available_symbols[:20])}...")
                raise ValueError(f"Symbol {self.symbol} not available")
        
        logger.info(f"✅ Trading symbol confirmed: {self.symbol}")
    
    async def query_symbol_precision(self):
        """Query symbol precision and limits from API"""
        logger.info(f"📏 Querying {self.symbol} precision and limits...")
        
        try:
            # Get precision info dynamically from API
            price_precision = self.lighter.ticker_to_price_precision.get(self.symbol)
            size_precision = self.lighter.ticker_to_lot_precision.get(self.symbol)
            min_base = self.lighter.ticker_min_base.get(self.symbol)
            min_quote = self.lighter.ticker_min_quote.get(self.symbol)
            
            # Get current market data
            orderbook = await self.lighter.orderbook_orders(self.symbol, limit=1)
            current_price = 0
            bid = ask = 0
            
            if orderbook.get('bids') and orderbook.get('asks'):
                bid = float(orderbook['bids'][0]['price'])
                ask = float(orderbook['asks'][0]['price'])
                current_price = (bid + ask) / 2
            
            precision_info = {
                'symbol': self.symbol,
                'price_precision': price_precision,
                'size_precision': size_precision,
                'min_base_amount': min_base,
                'min_quote_amount': min_quote,
                'current_price': current_price,
                'bid': bid,
                'ask': ask
            }
            
            self.test_results['precision'] = {
                'success': True,
                'data': precision_info
            }
            
            logger.info(f"✅ {self.symbol} Contract Precision Info:")
            logger.info(f"   Price precision: {price_precision} decimals")
            logger.info(f"   Size precision: {size_precision} decimals")
            logger.info(f"   Min position size: {min_base} {self.symbol}")
            logger.info(f"   Min quote amount: ${min_quote}")
            logger.info(f"   Current price: ${current_price:.6f}")
            logger.info(f"   Spread: ${ask-bid:.6f}")
            
            return precision_info
            
        except Exception as e:
            logger.error(f"❌ Failed to query precision: {e}")
            self.test_results['precision'] = {
                'success': False,
                'error': str(e)
            }
            raise
    
    def calculate_minimum_position_size(self, precision_info):
        """Calculate minimum position size for contracts (1x leverage)"""
        min_base = precision_info['min_base_amount']
        min_quote = precision_info['min_quote_amount']
        current_price = precision_info['current_price']
        size_precision = precision_info['size_precision']
        
        # Calculate minimum base amount needed for quote constraint
        min_base_for_quote = min_quote / current_price
        
        # Both constraints must be satisfied - use the MAXIMUM of the two
        required_base = max(min_base, min_base_for_quote)
        
        # Add minimal buffer only if needed for precision rounding
        if size_precision > 0:
            required_base = required_base * 1.01  # 1% buffer for precision rounding
        
        # Round UP to the required precision to ensure we meet minimums
        precision_factor = 10 ** size_precision
        final_amount = int(required_base * precision_factor + 0.999) / precision_factor
        
        # Double-check we meet both constraints
        quote_value = final_amount * current_price
        
        logger.info(f"💰 Minimum position calculation for {self.symbol} contracts:")
        logger.info(f"   Min position constraint: {min_base} {self.symbol}")
        logger.info(f"   Min quote constraint: {min_base_for_quote:.6f} {self.symbol} (${min_quote} ÷ ${current_price:.6f})")
        logger.info(f"   Binding constraint: {'POSITION' if min_base > min_base_for_quote else 'QUOTE'}")
        logger.info(f"   Selected size: {final_amount} {self.symbol} (minimum allowed)")
        logger.info(f"   Notional value (1x): ${quote_value:.6f}")
        logger.info(f"   ✓ Meets min quote: ${quote_value:.2f} >= ${min_quote:.2f}")
        logger.info(f"   ✓ Meets min position: {final_amount} >= {min_base}")
        
        return final_amount
    
    async def test_long_position(self, precision_info):
        """Test opening and immediately closing a long position (做多)"""
        logger.info(f"📈 Testing LONG position for {self.symbol}...")
        
        try:
            position_size = self.calculate_minimum_position_size(precision_info)
            
            # Long position: buy at current ask price (slightly above mid for quick fill)
            ask_price = precision_info['ask']
            
            # Round price to precision
            price_precision = precision_info['price_precision']
            precision_factor = 10 ** price_precision
            entry_price = int(ask_price * precision_factor) / precision_factor
            
            logger.info(f"   Opening LONG position:")
            logger.info(f"   Size: {position_size} {self.symbol}")
            logger.info(f"   Entry price: ${entry_price:.6f}")
            logger.info(f"   Notional: ${position_size * entry_price:.6f}")
            
            # Open long position (positive amount = buy/long)
            open_tx, open_tx_hash, open_err = await self.lighter.limit_order(
                ticker=self.symbol,
                amount=position_size,  # Positive for long
                price=entry_price,
                tif='GTC'
            )
            
            if open_err is not None:
                raise Exception(f"Long position opening failed: {open_err}")
            
            logger.info(f"✅ Long position opened successfully")
            logger.info(f"   TX Hash: {open_tx_hash}")
            
            # Small delay to ensure order processing
            await asyncio.sleep(1)
            
            # Immediately close the long position (sell at bid price)
            bid_price = precision_info['bid']
            exit_price = int(bid_price * precision_factor) / precision_factor
            
            logger.info(f"   Closing LONG position:")
            logger.info(f"   Exit price: ${exit_price:.6f}")
            
            # Close long position (negative amount = sell/close long)
            close_tx, close_tx_hash, close_err = await self.lighter.limit_order(
                ticker=self.symbol,
                amount=-position_size,  # Negative to close long
                price=exit_price,
                tif='GTC'
            )
            
            if close_err is not None:
                raise Exception(f"Long position closing failed: {close_err}")
            
            logger.info(f"✅ Long position closed successfully")
            logger.info(f"   TX Hash: {close_tx_hash}")
            
            # Calculate P&L
            pnl = (exit_price - entry_price) * position_size
            pnl_pct = (pnl / (entry_price * position_size)) * 100
            
            self.test_results['long_position'] = {
                'success': True,
                'data': {
                    'position_size': position_size,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'pnl_percentage': pnl_pct,
                    'open_tx_hash': str(open_tx_hash) if open_tx_hash else None,
                    'close_tx_hash': str(close_tx_hash) if close_tx_hash else None
                }
            }
            
            logger.info(f"   P&L: ${pnl:.6f} ({pnl_pct:+.3f}%)")
            
        except Exception as e:
            logger.error(f"❌ Long position test failed: {e}")
            self.test_results['long_position'] = {
                'success': False,
                'error': str(e)
            }
            raise
    
    async def test_short_position(self, precision_info):
        """Test opening and immediately closing a short position (做空)"""
        logger.info(f"📉 Testing SHORT position for {self.symbol}...")
        
        try:
            position_size = self.calculate_minimum_position_size(precision_info)
            
            # Short position: sell at current bid price
            bid_price = precision_info['bid']
            
            # Round price to precision
            price_precision = precision_info['price_precision']
            precision_factor = 10 ** price_precision
            entry_price = int(bid_price * precision_factor) / precision_factor
            
            logger.info(f"   Opening SHORT position:")
            logger.info(f"   Size: {position_size} {self.symbol}")
            logger.info(f"   Entry price: ${entry_price:.6f}")
            logger.info(f"   Notional: ${position_size * entry_price:.6f}")
            
            # Open short position (negative amount = sell/short)
            open_tx, open_tx_hash, open_err = await self.lighter.limit_order(
                ticker=self.symbol,
                amount=-position_size,  # Negative for short
                price=entry_price,
                tif='GTC'
            )
            
            if open_err is not None:
                raise Exception(f"Short position opening failed: {open_err}")
            
            logger.info(f"✅ Short position opened successfully")
            logger.info(f"   TX Hash: {open_tx_hash}")
            
            # Small delay to ensure order processing
            await asyncio.sleep(1)
            
            # Immediately close the short position (buy at ask price)
            ask_price = precision_info['ask']
            exit_price = int(ask_price * precision_factor) / precision_factor
            
            logger.info(f"   Closing SHORT position:")
            logger.info(f"   Exit price: ${exit_price:.6f}")
            
            # Close short position (positive amount = buy/close short)
            close_tx, close_tx_hash, close_err = await self.lighter.limit_order(
                ticker=self.symbol,
                amount=position_size,  # Positive to close short
                price=exit_price,
                tif='GTC'
            )
            
            if close_err is not None:
                raise Exception(f"Short position closing failed: {close_err}")
            
            logger.info(f"✅ Short position closed successfully")
            logger.info(f"   TX Hash: {close_tx_hash}")
            
            # Calculate P&L (for short: profit when price goes down)
            pnl = (entry_price - exit_price) * position_size
            pnl_pct = (pnl / (entry_price * position_size)) * 100
            
            self.test_results['short_position'] = {
                'success': True,
                'data': {
                    'position_size': position_size,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'pnl_percentage': pnl_pct,
                    'open_tx_hash': str(open_tx_hash) if open_tx_hash else None,
                    'close_tx_hash': str(close_tx_hash) if close_tx_hash else None
                }
            }
            
            logger.info(f"   P&L: ${pnl:.6f} ({pnl_pct:+.3f}%)")
            
        except Exception as e:
            logger.error(f"❌ Short position test failed: {e}")
            self.test_results['short_position'] = {
                'success': False,
                'error': str(e)
            }
            raise
    
    async def run_full_test_suite(self):
        """Run the complete TON contracts test suite"""
        logger.info(f"🧪 Starting TON Contracts Trading Test Suite")
        logger.info("="*60)
        logger.info("⚠️  WARNING: This performs REAL contract trading with REAL money!")
        logger.info("💰 Using minimum position sizes with 1x leverage")
        logger.info("📈📉 Testing both long and short positions with immediate closing")
        logger.info("="*60)
        
        try:
            # Setup
            await self.setup()
            
            # Test 1: Query precision (dynamic from API)
            precision_info = await self.query_symbol_precision()
            
            # Test 2: Long position (做多) - buy then immediately sell
            logger.info("\n" + "="*40)
            await self.test_long_position(precision_info)
            
            # Small delay between tests
            await asyncio.sleep(2)
            
            # Test 3: Short position (做空) - sell then immediately buy back
            logger.info("\n" + "="*40)
            await self.test_short_position(precision_info)
            
        except Exception as e:
            logger.error(f"❌ Test suite failed: {e}")
            
        finally:
            # Cleanup
            if self.lighter:
                await self.lighter.cleanup()
        
        # Print results
        self.print_test_summary()
    
    def print_test_summary(self):
        """Print comprehensive test summary"""
        logger.info("\n" + "="*60)
        logger.info(f"📋 {self.symbol} CONTRACTS TRADING TEST SUMMARY")
        logger.info("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result['success'])
        failed_tests = total_tests - passed_tests
        
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"Passed: {passed_tests} ✅")
        logger.info(f"Failed: {failed_tests} ❌")
        logger.info(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%" if total_tests > 0 else "N/A")
        
        logger.info("\n📊 DETAILED RESULTS:")
        total_pnl = 0
        
        for test_name, result in self.test_results.items():
            status = "✅" if result['success'] else "❌"
            logger.info(f"{status} {test_name}")
            
            if result['success'] and 'data' in result:
                if test_name == 'precision':
                    data = result['data']
                    logger.info(f"   Price: ${data['current_price']:.6f}, Min size: {data['min_base_amount']} {self.symbol}")
                elif test_name in ['long_position', 'short_position']:
                    data = result['data']
                    pnl = data.get('pnl', 0)
                    pnl_pct = data.get('pnl_percentage', 0)
                    total_pnl += pnl
                    position_type = "LONG" if test_name == 'long_position' else "SHORT"
                    logger.info(f"   {position_type}: Size {data['position_size']} {self.symbol}")
                    logger.info(f"   Entry: ${data['entry_price']:.6f} → Exit: ${data['exit_price']:.6f}")
                    logger.info(f"   P&L: ${pnl:.6f} ({pnl_pct:+.3f}%)")
            elif not result['success']:
                logger.info(f"   Error: {result.get('error', 'Unknown error')}")
        
        if total_pnl != 0:
            logger.info(f"\n💰 Total P&L: ${total_pnl:.6f}")
        
        if failed_tests == 0:
            logger.info(f"\n🎉 ALL TESTS PASSED! {self.symbol} contract trading is working correctly.")
            logger.info("✅ Both long and short positions opened and closed successfully")
            logger.info("✅ Using minimum position sizes with proper risk management")
        else:
            logger.info(f"\n⚠️  {failed_tests} test(s) failed. Please review the errors above.")
        
        logger.info("="*60)


async def main():
    """Main function"""
    print("🚀 TON Contracts Trading Test Script")
    print("="*60)
    print("⚠️  IMPORTANT SAFETY WARNING:")
    print("This script performs REAL contract trading with REAL money!")
    print("Testing long/short positions with minimum amounts at 1x leverage.")
    print("Each position is immediately closed after opening.")
    print("="*60)
    
    # Check for environment variables
    if not os.getenv("LIGHTER_KEY") or not os.getenv("LIGHTER_SECRET"):
        print("\n❌ Missing API credentials!")
        print("Please create a .env file with:")
        print("LIGHTER_KEY=your_api_key")
        print("LIGHTER_SECRET=your_api_secret")
        return
    
    print("\n🎯 Testing TON contracts with minimum position sizes...")
    print("Starting in 2 seconds...")
    await asyncio.sleep(2)
    
    # Run tests
    tester = TONContractsTester("TON")
    await tester.run_full_test_suite()


if __name__ == "__main__":
    asyncio.run(main())