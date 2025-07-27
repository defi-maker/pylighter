# API 参考文档

## Lighter 客户端类

### 初始化

```python
from pylighter.client import Lighter

lighter = Lighter(key="your_wallet_address", secret="your_private_key")
await lighter.init_client()
```

### 主要方法

#### 交易相关

##### `limit_order(ticker, amount, price, tif='GTC')`
下限价单

**参数:**
- `ticker` (str): 交易对符号，如 "TON", "XRP"
- `amount` (float): 交易数量，正数=买入/做多，负数=卖出/做空
- `price` (float): 限价价格
- `tif` (str): 订单有效期，默认 'GTC' (Good Till Cancelled)

**返回:**
- `tuple`: (tx_info, tx_hash, error)

**示例:**
```python
# 做多 3.2 TON，价格 3.15
tx_info, tx_hash, error = await lighter.limit_order("TON", 3.2, 3.15)

# 做空 3.2 TON，价格 3.20
tx_info, tx_hash, error = await lighter.limit_order("TON", -3.2, 3.20)
```

##### `market_order(ticker, amount)`
下市价单

##### `cancel_all_orders(ticker)`
取消指定币种的所有订单

#### 查询相关

##### `orderbook_orders(ticker, limit=100)`
获取订单簿数据

**返回:**
```python
{
    'bids': [{'price': '3.141980', 'remaining_base_amount': '1234'}, ...],
    'asks': [{'price': '3.144500', 'remaining_base_amount': '567'}, ...]
}
```

##### `orderbooks(ticker=None)`
获取交易对基本信息

##### `orderbook_details(ticker)`
获取交易对详细信息，包含最小交易量等约束

### 属性

- `ticker_to_idx`: 交易对名称到市场ID的映射
- `ticker_min_base`: 最小基础货币数量
- `ticker_min_quote`: 最小报价货币数量($10)
- `ticker_to_price_precision`: 价格精度
- `ticker_to_lot_precision`: 数量精度

## 错误处理

所有交易方法都返回 `(tx_info, tx_hash, error)` 元组：

```python
tx_info, tx_hash, error = await lighter.limit_order("TON", 3.2, 3.15)

if error is not None:
    print(f"交易失败: {error}")
else:
    print(f"交易成功: {tx_hash}")
```

## 常见错误码

- `21120`: 无效签名 - 检查私钥和API Key Index
- `400`: 参数错误 - 检查交易数量和价格是否符合最小值要求
- `网络错误`: 检查网络连接

## 最佳实践

1. **错误处理**: 始终检查返回的 error 参数
2. **数量验证**: 确保交易数量满足最小值要求
3. **价格精度**: 使用正确的价格精度
4. **资源清理**: 使用完毕后调用 `await lighter.cleanup()`

```python
try:
    lighter = Lighter(key=api_key, secret=api_secret)
    await lighter.init_client()
    
    # 执行交易
    tx_info, tx_hash, error = await lighter.limit_order("TON", 3.2, 3.15)
    
    if error is not None:
        print(f"交易失败: {error}")
    else:
        print(f"交易成功: {tx_hash}")
        
finally:
    await lighter.cleanup()
```