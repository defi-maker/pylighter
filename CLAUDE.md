# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is `pylighter`, a Python SDK wrapper for the Lighter Protocol - a decentralized perpetual futures exchange. The project provides a simplified async client interface on top of the official `lighter-sdk` for interacting with Lighter's REST API and trading functionality.

## Development Environment

- **Python Version**: Requires Python ≥3.13
- **Package Manager**: Uses `uv` for dependency management
- **Dependencies**: Core dependencies include `httpx`, `lighter-sdk`, `orjson`, and `python-dotenv`

## Common Commands

**IMPORTANT**: This project uses `uv` package manager. Always use `uv run` to execute Python scripts.

```bash
# Install dependencies
uv sync

# Run the main example
uv run main.py

# Run individual examples
uv run examples/create_cancel_order.py
uv run examples/create_market_order.py
uv run examples/get_info.py
uv run examples/ws.py

# Run tests
uv run test.py

# Run strategies
uv run strategies/example_grid_usage.py
uv run strategies/backtest_runner.py

# Run TON Grid Trading Strategy (IMPORTANT!)
uv run grid_strategy_ton.py --dry-run      # Dry run mode (recommended for testing)
uv run grid_strategy_ton.py --symbol TON   # Live trading mode (requires confirmation)

# Run price simulator
uv run strategies/price_simulator.py

# Validate client structure (no credentials needed)
uv run validate_client_structure.py

# Test real environment (requires API credentials)
uv run test_real_environment.py
```

## Architecture

### Core Components

- **`pylighter/client.py`**: Main `Lighter` class providing simplified async methods for all API endpoints
  - Wraps the official `lighter-sdk.SignerClient` for authenticated operations
  - Handles market ID lookups, precision conversions, and order management
  - Provides methods for account info, trading, market data, and transaction history

- **`pylighter/httpx.py`**: Custom `HTTPClient` class built on `httpx`
  - Handles HTTP requests with automatic retries and error handling
  - Uses `orjson` for fast JSON parsing
  - Provides custom `HTTPException` for detailed error reporting

### Key Features

The `Lighter` client provides:
- **Authentication**: Automatic API key and account index management
- **Market Data**: Order books, recent trades, candlesticks, exchange stats
- **Trading**: Limit orders, market orders, order cancellation with precision handling
- **Account Management**: Account info, positions, PnL, transaction history
- **WebSocket Support**: Real-time data streaming (see examples)

### Configuration

- Uses `.env` file for API credentials (`LIGHTER_KEY`, `LIGHTER_SECRET`)
- Supports both testnet (`https://testnet.zklighter.elliot.ai`) and mainnet (`https://mainnet.zklighter.elliot.ai`)
- Market precision and minimum amounts are automatically fetched during client initialization

### Error Handling

- Custom `HTTPException` class captures HTTP errors with status codes and headers
- Automatic retry logic in HTTP client
- Input validation for order amounts against minimum requirements

## Examples Structure

The `examples/` directory contains practical usage examples:
- **Setup**: `system_setup.py` for initial account configuration
- **Trading**: `create_cancel_order.py`, `create_market_order.py`
- **Data**: `get_info.py` for account and market information
- **Real-time**: `ws.py`, `ws_async.py` for WebSocket connections
- **Batch Operations**: `send_tx_batch.py` for multiple transactions

## Strategies Structure

The `strategies/` directory contains automated trading strategies:
- **Base Framework**: `base_strategy.py` - Abstract base class for all strategies
- **Grid Trading**: `grid_strategy.py` - Complete grid trading implementation
- **Mock Trading**: `mock_client.py` - Mock client for backtesting without real API calls
- **Price Simulation**: `price_simulator.py` - Generate realistic price data for testing
- **Backtesting**: `backtest_runner.py` - Comprehensive backtesting framework
- **Examples**: `example_grid_usage.py` - Demonstrates strategy usage and backtesting

## Testing and Validation

The project includes comprehensive testing tools:

### Client Structure Validation
- **`validate_client_structure.py`**: Validates that all expected methods and attributes are present
- Runs without requiring API credentials
- Checks method signatures and async compatibility

### Real Environment Testing
- **`test_real_environment.py`**: Tests all client functionality against real Lighter Protocol API
- Requires `LIGHTER_KEY` and `LIGHTER_SECRET` environment variables
- Performs only READ operations - no trading or orders are placed
- Tests all major API endpoints comprehensively

### Backtesting Framework
- **`strategies/backtest_runner.py`**: Complete backtesting system for trading strategies
- **`strategies/mock_client.py`**: Mock client for safe testing without real API calls
- **`strategies/price_simulator.py`**: Generates realistic market data for testing

## Important Notes

- **ALWAYS use `uv run` instead of `python` for running scripts** ⚠️
- Always call `await lighter.init_client()` after instantiation to initialize market metadata
- Always call `await lighter.cleanup()` to properly close HTTP and WebSocket connections
- Market IDs are handled automatically - pass ticker symbols (e.g., "BTC-USD") to trading methods
- Order amounts and prices are automatically converted to the required precision
- Use validation scripts to verify client functionality before deploying to production

## Grid Trading Strategy Notes

### Recent Fixes Applied
- ✅ Fixed WebSocket callback type mismatch (market_id comes as string, stored as int)
- ✅ Fixed cancel_order method (no cancel_all_orders method exists, only individual cancel_order)
- ✅ Implemented mandatory WebSocket connection (no polling fallback)
- ✅ Added command line arguments (--dry-run, --symbol)
- ✅ Fixed Ctrl+C signal handling (shutdown_requested flag + responsive main loop)
- ✅ Added comprehensive startup/shutdown handling aligned with Binance reference
- ✅ Fixed order management issues (real cancellation, order ID tracking, spam prevention)
- ✅ Added order limits and automatic cleanup (max 8 orders, periodic cleanup)
- ✅ Fixed get_open_orders to use WebSocket-tracked data (not problematic REST API)

### Key Features
- **WebSocket Only**: Mandatory real-time price updates via WebSocket
- **Grid Spacing**: 0.1% (configurable in GRID_SPACING constant)
- **Leverage**: 5x for TON (lower risk than other assets)
- **Minimum Order**: $10 quote amount standard
- **Dual Positions**: Long/short positions with separate grid management

### Command Line Usage
```bash
# Dry run mode (safe testing)
uv run grid_strategy_ton.py --dry-run

# Live trading (requires confirmation)
uv run grid_strategy_ton.py

# Custom symbol
uv run grid_strategy_ton.py --symbol BTC --dry-run
```

## Program Startup and Shutdown Handling

### Startup Process (Aligned with Binance Reference)

The program performs comprehensive startup analysis similar to the Binance reference implementation:

#### 1. **Position Analysis** (`analyze_startup_state`)
```python
# Checks existing positions at startup
self.long_position, self.short_position = await self.get_positions()
logger.info(f"Startup positions: Long={self.long_position}, Short={self.short_position}")
```

#### 2. **Order Status Synchronization**
```python
# Resets and synchronizes order tracking
await self.get_open_orders()
self.check_orders_status()
```

#### 3. **Existing Position Management**
- ✅ **Detects existing positions** and logs warnings
- ✅ **Grid strategy takes over** existing positions automatically
- ✅ **Continues trading** with existing positions integrated into grid logic

**Startup Log Example:**
```
📊 Analyzing startup state...
Startup positions: Long=0, Short=0
⚠️ Existing positions detected! (if positions exist)
   Long position: 15.5
   Short position: 0
   Grid strategy will manage these existing positions
```

### Shutdown Process (Three-Layer Protection)

#### 1. **Graceful Shutdown** (`graceful_shutdown`) - **RECOMMENDED**
- **Trigger**: `Ctrl+C`, `SIGTERM` signal
- **Behavior**: 
  - ✅ Cancels all active orders
  - ✅ **Preserves existing positions** (aligned with Binance reference)
  - ✅ Cleans up WebSocket connections
  - ✅ Logs shutdown completion

```bash
# User presses Ctrl+C
INFO:root:Received interrupt signal, shutting down...
INFO:root:🛑 Initiating graceful shutdown...
INFO:root:Option 1: Cancel all active orders and preserve positions
INFO:root:✅ Graceful shutdown completed
```

#### 2. **Emergency Stop** (`emergency_stop`) - **AUTOMATIC**
- **Trigger**: Program exceptions, critical errors
- **Behavior**: 
  - ⚡ Immediate order cancellation attempt
  - 📝 Critical error logging
  - 🔍 Manual verification prompt

#### 3. **Complete Position Closure** (`close_all_positions`) - **MANUAL ONLY**
- **Trigger**: Manual function call (not automatic)
- **Behavior**: 
  - 💰 Market orders to close all positions
  - ⚠️ **Use with extreme caution**

### Signal Handling

```python
# Comprehensive signal handling (aligned with Binance reference)
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # System termination
```

### Comparison with Binance Reference

| Feature | **Binance Reference** | **Lighter Implementation** | **Alignment** |
|---------|----------------------|---------------------------|---------------|
| **Startup Position Check** | ✅ `get_position()` | ✅ `get_positions()` | ✅ Fully Aligned |
| **Startup Order Sync** | ✅ `check_orders_status()` | ✅ `check_orders_status()` | ✅ Fully Aligned |
| **Existing Position Management** | ✅ Strategy takeover | ✅ Strategy takeover | ✅ Fully Aligned |
| **Graceful Shutdown** | ✅ Cancel orders, keep positions | ✅ Cancel orders, keep positions | ✅ Fully Aligned |
| **Signal Handling** | ✅ SIGINT/SIGTERM | ✅ SIGINT/SIGTERM | ✅ Fully Aligned |

### User Operation Guide

#### **Starting the Bot**
1. **Dry Run Mode** (Recommended for testing):
   ```bash
   uv run grid_strategy_ton.py --dry-run
   ```

2. **Live Trading Mode**:
   ```bash
   uv run grid_strategy_ton.py
   ```
   - ⚠️ Requires typing 'YES' to confirm
   - ⚠️ Will manage existing positions
   - ⚠️ Places real orders with real money

#### **Stopping the Bot**

1. **Recommended Method** - Graceful Shutdown:
   ```bash
   # Press Ctrl+C (FIXED - now works properly)
   # Bot will cancel orders but preserve positions
   # Signal handling: shutdown_requested flag + responsive main loop
   ```

2. **Emergency Situations**:
   - Program exceptions trigger automatic emergency stop
   - Manual verification required for order cancellation

3. **Complete Exit** (Manual):
   - Positions remain open after graceful shutdown
   - Use trading platform to manually close positions if needed

### Safety Features

1. **Multi-Layer Protection**: Graceful → Emergency → Force cleanup
2. **Position Preservation**: Default behavior preserves positions (prevents accidental losses)
3. **State Synchronization**: Complete startup state analysis
4. **User Confirmation**: Live mode requires explicit 'YES' confirmation
5. **Comprehensive Logging**: All shutdown actions are logged with timestamps

### Order Management Features

#### **Spam Prevention & Limits**
- ✅ **Maximum Orders**: Limited to 8 active orders at any time
- ✅ **Order ID Tracking**: All orders tracked for proper cancellation
- ✅ **Automatic Cleanup**: Periodic cleanup every 60 seconds
- ✅ **Order Cooldowns**: 10-second cooldown between order placements

#### **Real Order Cancellation**
- ✅ **Bulk Cancellation**: Primary method uses `await self.lighter.cancel_all_orders()` (official SDK)
- ✅ **Individual Fallback**: Falls back to `await self.lighter.cancel_order(symbol, order_id)` if bulk fails
- ✅ **Trades API Tracking**: Uses `trades` API for real-time order status updates
- ✅ **Error Handling**: Comprehensive error handling for both bulk and individual cancellation methods

### **Order Status Tracking System (ENHANCED)**

- ✅ **WebSocket Account Orders**: Primary method uses `account_orders` WebSocket subscription
- ✅ **Real-time Updates**: Instant order status changes (filled, cancelled, partial fills)
- ✅ **Trades API Fallback**: Uses `await self.lighter.trades()` if WebSocket disconnected
- ✅ **Real Order ID Tracking**: Extracts real order IDs from transaction event_info
- ✅ **Position Updates**: Automatic position updates when orders are filled
- ✅ **Order State Management**: Tracks order info (side, quantity, price, type)
- ✅ **Duplicate Prevention**: Prevents processing same fills multiple times

### Known API Limitations

- ⚠️ **accountActiveOrders 403 Error**: The `accountActiveOrders` endpoint consistently returns 403 Forbidden
- ✅ **Alternative Solution**: Strategy now uses `trades` API for order status tracking
- ✅ **Full Functionality**: All core features work normally with trades API tracking

### Important Notes

- ✅ **Startup**: Program automatically detects and manages existing positions
- ✅ **Normal Shutdown**: `Ctrl+C` now actually cancels orders and keeps positions (FIXED)
- ✅ **Order Management**: No more order accumulation - automatic limits and cleanup
- ⚠️ **Position Management**: Existing positions are integrated into grid strategy
- ⚠️ **Live Trading**: Always confirm you want to manage real positions before starting
- 🔍 **Manual Verification**: Check your trading platform after shutdown to verify order cancellation