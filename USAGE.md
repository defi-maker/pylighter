# 网格策略使用指南

## 命令行选项

```bash
uv run grid_strategy_ton.py --help
```

输出：
```
usage: grid_strategy_ton.py [-h] [--dry-run] [--symbol SYMBOL]

Lighter Protocol Grid Trading Bot

options:
  -h, --help       show this help message and exit
  --dry-run        Run in simulation mode without placing real orders
  --symbol SYMBOL  Trading symbol (default: TON)
```

## 使用方式

### 1. 模拟测试（推荐）
```bash
# 使用 TON 进行模拟测试
uv run grid_strategy_ton.py --dry-run

# 使用 XRP 进行模拟测试
uv run grid_strategy_ton.py --symbol XRP --dry-run
```

**模拟测试特点：**
- ✅ 使用真实 WebSocket 价格数据
- ✅ 完整策略逻辑验证
- ✅ 显示所有订单参数
- ✅ 无真实资金风险
- ✅ 与实盘完全相同的代码路径

### 2. 实盘交易
```bash
# 使用 TON 进行实盘交易
uv run grid_strategy_ton.py

# 使用 XRP 进行实盘交易
uv run grid_strategy_ton.py --symbol XRP
```

**安全确认：**
- 程序会要求输入 'YES' 确认实盘交易
- 确保账户有足够余额
- 确保 WebSocket 连接稳定

## WebSocket 要求

### 必须连接成功
- WebSocket 连接是强制性的，不会降级到轮询模式
- 如果 WebSocket 无法连接，程序会直接退出
- 30秒内必须收到初始价格数据

### 自动重连
- WebSocket 断开时会自动重连
- 使用指数退避策略（5秒->7.5秒->11.25秒...最多30秒）
- 无限重连直到成功

## 日志输出示例

### Dry Run 模式：
```
🤖 Lighter Protocol Grid Trading Bot (DRY RUN)
📊 Symbol: TON, Leverage: 5x, Grid: 0.1%
🧪 Starting in DRY RUN mode - no real orders will be placed
🌐 Starting WebSocket connection...
📡 WebSocket mode enabled - real-time price updates
✅ Initial price received: $3.153240
🔄 DRY RUN - BUY order: 3.2 TON @ $3.146789 (Quote: $10.07)
```

### Live Trading 模式：
```
🤖 Lighter Protocol Grid Trading Bot (LIVE TRADING)  
⚠️  IMPORTANT: This performs REAL trading with REAL money!
📊 Symbol: TON, Leverage: 5x, Grid: 0.1%
💰 Starting in LIVE TRADING mode - real money will be used!
Type 'YES' to confirm live trading: YES
📈 REAL - Placing BUY order: 3.2 TON @ $3.146789
```

## 错误处理

### WebSocket 初始化失败
```
❌ Failed to initialize WebSocket client: [error details]
RuntimeError: WebSocket initialization is mandatory for this strategy
```

### 价格数据超时
```
❌ Failed to receive initial price data from WebSocket within 30 seconds
RuntimeError: WebSocket price data is mandatory for this strategy
```

### 网络断开
```
⚠️ WebSocket disconnected, waiting for reconnection...
🌐 Starting WebSocket connection...
```

## 最佳实践

1. **始终先运行 dry-run**：
   ```bash
   uv run grid_strategy_ton.py --dry-run
   ```

2. **验证网络连接**：
   - 确保能连接到 Lighter Protocol WebSocket
   - 测试网络稳定性

3. **小额测试**：
   - 首次实盘使用最小可能的资金
   - 观察策略行为是否符合预期

4. **监控日志**：
   - 观察 WebSocket 连接状态
   - 检查订单执行情况
   - 关注风险控制触发

## 与参考代码的一致性

✅ **WebSocket 实时价格**：与 Binance 参考代码完全一致  
✅ **双向网格策略**：相同的策略逻辑  
✅ **无降级模式**：确保 WebSocket 连接质量  
✅ **命令行控制**：干净的 dry-run vs live 选择