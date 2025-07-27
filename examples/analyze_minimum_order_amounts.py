"""
Check minimum order amounts for all available symbols
"""

import asyncio
from pylighter.client import Lighter
import os
from dotenv import load_dotenv

load_dotenv()

async def check_all_minimums():
    api_key = os.getenv("LIGHTER_KEY")
    api_secret = os.getenv("LIGHTER_SECRET")
    
    lighter = Lighter(key=api_key, secret=api_secret)
    await lighter.init_client()
    
    print("🔍 Checking minimum constraints for all symbols...")
    print()
    
    results = []
    
    # Check all available symbols
    for symbol in sorted(lighter.ticker_to_idx.keys()):
        try:
            min_base = lighter.ticker_min_base.get(symbol, 0)
            min_quote = lighter.ticker_min_quote.get(symbol, 0)
            
            # Get current price
            orderbook = await lighter.orderbook_orders(symbol, limit=1)
            current_price = 0
            if orderbook.get('bids') and orderbook.get('asks'):
                bid = float(orderbook['bids'][0]['price'])
                ask = float(orderbook['asks'][0]['price'])
                current_price = (bid + ask) / 2
            
            if current_price > 0:
                min_base_for_quote = min_quote / current_price
                real_minimum = max(min_base, min_base_for_quote)
                quote_value = real_minimum * current_price
                
                results.append({
                    'symbol': symbol,
                    'min_base': min_base,
                    'min_quote': min_quote,
                    'price': current_price,
                    'real_minimum': real_minimum,
                    'quote_value': quote_value
                })
        
        except Exception as e:
            print(f"❌ Error checking {symbol}: {e}")
            continue
    
    # Sort by quote value (cheapest first)
    results.sort(key=lambda x: x['quote_value'])
    
    print(f"📊 All symbols ranked by minimum order value:")
    print(f"{'Symbol':<8} {'Min Base':<12} {'Price':<12} {'Real Min':<12} {'USD Value':<12}")
    print("-" * 60)
    
    for r in results:
        print(f"{r['symbol']:<8} {r['min_base']:<12.1f} ${r['price']:<11.6f} {r['real_minimum']:<12.1f} ${r['quote_value']:<11.2f}")
    
    await lighter.cleanup()
    
    print(f"\n🎯 Best options for grid trading (lowest minimum values):")
    for r in results[:5]:
        print(f"   {r['symbol']}: {r['real_minimum']:.1f} tokens (~${r['quote_value']:.2f})")

if __name__ == "__main__":
    asyncio.run(check_all_minimums())