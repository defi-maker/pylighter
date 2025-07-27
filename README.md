# Lighter Protocol Python SDK

一个用于 Lighter Protocol 去中心化交易所的 Python SDK，支持现货和合约交易。

## 快速开始

### 安装依赖
```bash
uv sync
```

### 环境配置
创建 `.env` 文件：
```bash
LIGHTER_KEY=0x... # 你的钱包地址
LIGHTER_SECRET=... # 你的私钥
```

### 基础使用
```python
from pylighter.client import Lighter

# 初始化客户端
lighter = Lighter(key="your_key", secret="your_secret")
await lighter.init_client()

# 下限价单
tx_info, tx_hash, error = await lighter.limit_order(
    ticker="TON",
    amount=3.2,  # 正数=买入/做多，负数=卖出/做空
    price=3.15,
    tif='GTC'
)
```

## 项目结构

```
lighter_py/
├── pylighter/           # 核心 SDK
│   ├── client.py       # 主要客户端类
│   └── httpx.py        # HTTP 客户端
├── examples/           # 示例代码
├── docs/              # 文档
├── strategies/        # 交易策略 (已清理)
├── grid_strategy_ton.py # 网格策略 (主要)
└── main.py            # 主入口
```

## 主要功能

### 1. 基础交易 
- 限价单/市价单
- 订单取消
- 账户查询
- 持仓管理

### 2. 网格策略
基于参考的网格策略，完全适配 Binance 策略逻辑：

```bash
# 模拟测试（推荐先运行）
uv run grid_strategy_ton.py --dry-run

# 实盘交易
uv run grid_strategy_ton.py

# 使用其他币种
uv run grid_strategy_ton.py --symbol XRP --dry-run
```

**特点:**
- 使用 TON 币种，基于统一的 $10 最小交易额
- 5倍杠杆，风险可控
- 0.1% 网格间距
- 双向持仓策略
- 智能风险控制

### 3. 分析工具
- 市场数据查询
- 最小交易量分析
- 币种成本比较
- 订单簿分析

## 完整文档

### 核心文档
- [API 参考](docs/api-reference.md) - 完整 API 文档
- [网格策略指南](docs/grid-strategy-guide.md) - 网格策略详解
- [示例指南](docs/examples-guide.md) - 示例代码说明

### 参考信息
- [支持币种](docs/supported-tokens.md)
- [常见问题](docs/faq.md)
- [故障排除](docs/troubleshooting.md)

## 示例代码

### 分析支持币种
```bash
uv run examples/analyze_minimum_order_amounts.py
```

### 测试合约交易
```bash
uv run examples/ton_contract_trading.py
```

### 多币种交易
```bash
uv run examples/multi_symbol_trading.py
```

## 重要提醒

- **真实资金交易**: 请先小额测试再增加资金
- **风险控制**: 使用合理的杠杆比例
- **网络稳定**: 确保网络连接稳定
- **API 限制**: 注意交易频率限制

## 安全最佳实践

1. **环境变量**: 使用环境变量存储敏感信息
2. **测试优先**: 优先使用模拟模式测试策略
3. **资金管理**: 合理分配交易资金
4. **监控机制**: 实时监控策略运行状态

## 获取帮助

- 查看 [examples/](examples/) 目录获取示例代码
- 阅读 [docs/](docs/) 目录获取详细文档
- 参考 [CLAUDE.md](CLAUDE.md) 了解项目信息

## 技术特色

- **低成本交易**: 基于 Lighter Protocol 去中心化交易所
- **智能策略**: 完整实现网格交易策略
- **API 集成**: 原生支持 Lighter Protocol API

---

**免责声明**: 本 SDK 仅供学习和研究使用，使用时请注意风险控制。