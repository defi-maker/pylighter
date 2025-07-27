# 示例代码指南

## 概述

`examples/` 目录包含了各种使用场景的示例代码，帮助你快速上手 Lighter Protocol SDK。

## 示例列表

### 🔍 分析工具

#### `analyze_minimum_order_amounts.py`
分析所有支持币种的最小交易量和成本

**运行:**
```bash
uv run examples/analyze_minimum_order_amounts.py
```

**输出示例:**
```
📊 All symbols ranked by minimum order value:
Symbol   Min Base     Price        Real Min     USD Value   
------------------------------------------------------------
TON      2.0          $3.139745    3.2          $10.00      
XRP      20.0         $3.231130    20.0         $64.62      
...
```

**用途:**
- 选择最优交易币种
- 了解不同币种的交易成本
- 评估策略适用性

#### `grid_strategy_simulation.py`
网格策略模拟测试

**运行:**
```bash
uv run examples/grid_strategy_simulation.py
```

**功能:**
- 模拟网格策略的完整流程
- 展示订单下单逻辑
- 测试网格调整机制
- 无真实资金风险

### 📈 交易示例

#### `ton_contract_trading.py`
TON 合约交易完整示例

**功能:**
- 查询市场精度和约束
- 计算最小交易量
- 执行多空合约交易
- 立即平仓操作

**使用场景:**
- 学习合约交易基础
- 测试 API 连接
- 验证交易逻辑

#### `multi_symbol_trading.py`
多币种交易示例

**功能:**
- 支持多个币种交易
- 动态选择最优币种
- 批量操作演示

### 🛠️ 基础工具

#### `create_cancel_order.py`
订单创建和取消示例

#### `create_market_order.py`
市价单交易示例

#### `get_info.py`
获取账户和市场信息

## 使用模式

### 1. 学习模式
按顺序运行示例，了解 SDK 功能：

```bash
# 1. 查看基本信息
uv run examples/get_info.py

# 2. 分析市场数据
uv run examples/analyze_minimum_order_amounts.py

# 3. 模拟交易策略
uv run examples/grid_strategy_simulation.py

# 4. 小额真实交易测试
uv run examples/ton_contract_trading.py
```

### 2. 开发模式
基于示例代码开发自己的策略：

```python
# 复制示例作为模板
cp examples/ton_contract_trading.py my_strategy.py

# 修改参数和逻辑
# 在示例基础上构建
```

### 3. 生产模式
使用完整的网格策略：

```bash
# 先模拟测试
uv run examples/grid_strategy_simulation.py

# 确认无误后运行实盘
uv run grid_strategy_ton.py
```

## 示例代码结构

### 标准模板
```python
"""
示例描述和用途说明
"""

import asyncio
from pylighter.client import Lighter
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

async def main():
    # 初始化客户端
    lighter = Lighter(
        key=os.getenv("LIGHTER_KEY"),
        secret=os.getenv("LIGHTER_SECRET")
    )
    
    try:
        await lighter.init_client()
        
        # 主要逻辑
        # ...
        
    except Exception as e:
        print(f"错误: {e}")
    finally:
        # 清理资源
        await lighter.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
```

### 错误处理模式
```python
# 交易操作
tx_info, tx_hash, error = await lighter.limit_order("TON", 3.2, 3.15)

if error is not None:
    print(f"交易失败: {error}")
    return
    
print(f"交易成功: {tx_hash}")
```

### 数据查询模式
```python
# 获取市场数据
orderbook = await lighter.orderbook_orders("TON", limit=5)

if orderbook.get('bids') and orderbook.get('asks'):
    best_bid = float(orderbook['bids'][0]['price'])
    best_ask = float(orderbook['asks'][0]['price'])
    print(f"买一: ${best_bid:.6f}, 卖一: ${best_ask:.6f}")
```

## 自定义示例

### 创建新示例
1. 复制最相似的现有示例
2. 修改主要逻辑部分
3. 更新文档字符串
4. 测试和验证

### 示例模板
```python
"""
[示例名称] - [功能描述]

用途:
- [主要用途1]
- [主要用途2]

注意事项:
- [重要提示]
"""

import asyncio
import logging
from pylighter.client import Lighter
# ... 其他导入

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def your_function():
    """你的主要功能函数"""
    # 实现逻辑
    pass

async def main():
    """主函数"""
    # 按照标准模板实现
    pass

if __name__ == "__main__":
    asyncio.run(main())
```

## 最佳实践

### 1. 安全实践
- 使用环境变量存储敏感信息
- 小额测试后再增加资金
- 始终使用 try/finally 清理资源

### 2. 调试实践
- 启用详细日志输出
- 检查所有错误返回值
- 使用模拟模式验证逻辑

### 3. 性能实践
- 合理设置更新间隔
- 避免频繁的 API 调用
- 批量处理多个操作

## 故障排除

### 常见问题
1. **认证失败**: 检查 `.env` 文件中的密钥
2. **网络错误**: 确认网络连接和防火墙设置
3. **交易失败**: 验证交易参数是否符合最小值要求
4. **精度错误**: 使用正确的价格和数量精度

### 调试步骤
1. 先运行 `get_info.py` 验证基本连接
2. 使用模拟模式测试逻辑
3. 检查日志输出找出问题根源
4. 参考 API 文档确认参数格式