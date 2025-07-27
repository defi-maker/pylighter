# 故障排除指南

## 常见错误及解决方案

### 认证错误

#### 错误 21120: 无效签名
```
Error: 21120 - Invalid signature
```

**可能原因:**
1. API Key 或私钥错误
2. API Key Index 不正确
3. 签名算法问题

**解决方案:**
```bash
# 1. 检查环境变量
cat .env
# 确认 LIGHTER_KEY 和 LIGHTER_SECRET 正确

# 2. 验证账户信息
uv run examples/get_info.py

# 3. 获取正确的 API Key Index
python -c "
import asyncio
from pylighter.client import Lighter
import os
from dotenv import load_dotenv

async def check_accounts():
    load_dotenv()
    lighter = Lighter(key=os.getenv('LIGHTER_KEY'), secret=os.getenv('LIGHTER_SECRET'))
    await lighter.init_client()
    
    # 查看账户信息
    accounts = await lighter.get_accounts_by_l1_address(os.getenv('LIGHTER_KEY'))
    print('Available accounts:', accounts)
    
    await lighter.cleanup()

asyncio.run(check_accounts())
"
```

#### 认证超时
```
Error: Authentication timeout
```

**解决方案:**
1. 检查网络连接
2. 验证系统时间是否正确
3. 重新初始化客户端

### 交易错误

#### 订单金额过小
```
Error: Order amount below minimum requirement
```

**解决方案:**
```python
# 正确计算最小交易量
async def calculate_min_amount(lighter, ticker):
    precision_info = await lighter.orderbook_details(ticker)
    min_base = float(precision_info['min_base_amount'])
    min_quote = float(precision_info['min_quote_amount'])
    current_price = float(precision_info['mark_price'])
    
    # 使用较大的数值
    min_required = max(min_base, min_quote / current_price)
    print(f"Minimum required amount for {ticker}: {min_required}")
    return min_required
```

#### 价格精度错误
```
Error: Invalid price precision
```

**解决方案:**
```python
# 使用正确的价格精度
price_precision = lighter.ticker_to_price_precision[ticker]
formatted_price = round(price, price_precision)
```

#### 余额不足
```
Error: Insufficient balance
```

**解决方案:**
1. 检查账户余额
2. 确认保证金充足（杠杆交易）
3. 减少交易数量

### 网络连接问题

#### 连接超时
```
Error: Connection timeout
```

**解决方案:**
```python
# 增加超时时间和重试机制
import asyncio
from aiohttp import ClientTimeout

async def robust_request(lighter, operation, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = await operation()
            return result
        except asyncio.TimeoutError:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # 指数退避
```

#### DNS 解析错误
```
Error: DNS resolution failed
```

**解决方案:**
1. 检查网络连接
2. 尝试使用不同的 DNS 服务器
3. 验证防火墙设置

### 策略运行问题

#### 网格策略卡住
**症状**: 策略长时间没有新订单

**诊断步骤:**
```bash
# 1. 检查日志
tail -f log/grid_ton_lighter.log

# 2. 检查网络连接
ping api.lighter.xyz

# 3. 检查持仓状态
uv run examples/get_info.py
```

**解决方案:**
1. 重启策略
2. 检查网络连接
3. 验证账户状态

#### 持仓数据不同步
**症状**: 显示的持仓与实际不符

**解决方案:**
```python
# 强制同步持仓
async def sync_positions(lighter):
    positions = await lighter.get_positions()
    print("Current positions:", positions)
    
    # 重新获取账户信息
    await lighter.init_client()
```

### 性能问题

#### 内存使用过高
**解决方案:**
```python
# 定期清理资源
import gc

async def periodic_cleanup():
    while True:
        await asyncio.sleep(300)  # 5分钟
        gc.collect()  # 强制垃圾回收
```

#### CPU 使用率过高
**解决方案:**
```python
# 增加延迟减少 CPU 使用
await asyncio.sleep(0.1)  # 在循环中添加短暂延迟
```

## 调试工具

### 启用详细日志
```python
import logging

# 设置详细日志级别
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 为特定模块启用调试
logger = logging.getLogger('pylighter')
logger.setLevel(logging.DEBUG)
```

### 网络请求调试
```python
# 打印所有 HTTP 请求
import aiohttp
import logging

# 启用 aiohttp 调试日志
logging.getLogger('aiohttp').setLevel(logging.DEBUG)
```

### 交易参数验证
```python
async def validate_order_params(lighter, ticker, amount, price):
    """验证订单参数是否符合要求"""
    try:
        # 检查精度
        price_precision = lighter.ticker_to_price_precision[ticker]
        amount_precision = lighter.ticker_to_lot_precision[ticker] 
        
        # 检查最小值
        min_base = lighter.ticker_min_base[ticker]
        min_quote = lighter.ticker_min_quote[ticker]
        
        print(f"Price precision: {price_precision}")
        print(f"Amount precision: {amount_precision}")
        print(f"Min base: {min_base}")
        print(f"Min quote: {min_quote}")
        print(f"Required quote value: {abs(amount) * price}")
        
        # 验证参数
        assert abs(amount) >= min_base, f"Amount too small: {amount} < {min_base}"
        assert abs(amount) * price >= min_quote, f"Quote value too small: {abs(amount) * price} < {min_quote}"
        
        print("✅ Order parameters valid")
        return True
        
    except Exception as e:
        print(f"❌ Parameter validation failed: {e}")
        return False
```

## 监控脚本

### 健康检查脚本
```python
#!/usr/bin/env python3
"""
健康检查脚本 - 定期检查策略运行状态
"""

import asyncio
import time
from pylighter.client import Lighter
import os
from dotenv import load_dotenv

async def health_check():
    load_dotenv()
    lighter = Lighter(key=os.getenv("LIGHTER_KEY"), secret=os.getenv("LIGHTER_SECRET"))
    
    try:
        await lighter.init_client()
        
        # 检查连接
        markets = await lighter.orderbooks()
        print(f"✅ API connection OK - {len(markets)} markets available")
        
        # 检查账户
        positions = await lighter.get_positions()
        print(f"✅ Account access OK - {len(positions)} positions")
        
        # 检查订单
        orders = await lighter.get_orders("TON")
        print(f"✅ Orders OK - {len(orders)} active orders")
        
        return True
        
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False
        
    finally:
        await lighter.cleanup()

if __name__ == "__main__":
    asyncio.run(health_check())
```

### 日志分析脚本
```bash
#!/bin/bash
# 分析网格策略日志

LOG_FILE="log/grid_ton_lighter.log"

echo "=== 最近的错误 ==="
grep -i "error\|exception\|failed" $LOG_FILE | tail -10

echo "=== 交易统计 ==="
grep "ORDER" $LOG_FILE | wc -l | xargs echo "总订单数:"
grep "BUY" $LOG_FILE | wc -l | xargs echo "买单数:"
grep "SELL" $LOG_FILE | wc -l | xargs echo "卖单数:"

echo "=== 最近的价格 ==="
grep "Price:" $LOG_FILE | tail -5

echo "=== 持仓变化 ==="
grep "Position sync" $LOG_FILE | tail -5
```

## 紧急处理

### 紧急停止策略
```bash
# 1. 停止进程
pkill -f "grid_strategy_ton.py"

# 2. 取消所有订单
python -c "
import asyncio
from pylighter.client import Lighter
import os
from dotenv import load_dotenv

async def emergency_cancel():
    load_dotenv()
    lighter = Lighter(key=os.getenv('LIGHTER_KEY'), secret=os.getenv('LIGHTER_SECRET'))
    await lighter.init_client()
    
    # 取消所有 TON 订单
    result = await lighter.cancel_all_orders('TON')
    print(f'Cancelled all orders: {result}')
    
    await lighter.cleanup()

asyncio.run(emergency_cancel())
"
```

### 数据备份
```bash
# 备份重要日志和配置
mkdir -p backup/$(date +%Y%m%d_%H%M%S)
cp log/*.log backup/$(date +%Y%m%d_%H%M%S)/
cp .env backup/$(date +%Y%m%d_%H%M%S)/
cp grid_strategy_ton.py backup/$(date +%Y%m%d_%H%M%S)/
```

## 获取支持

如果以上方法都无法解决问题：

1. **收集信息**:
   - 错误日志
   - 系统环境信息
   - 复现步骤

2. **检查文档**:
   - [API 参考](api-reference.md)
   - [FAQ](faq.md)
   - [示例代码](examples-guide.md)

3. **社区支持**:
   - 查看 GitHub Issues
   - 参考官方文档
   - 联系技术支持

---

**记住**: 在处理任何问题时，首先确保资金安全，必要时先停止策略运行。