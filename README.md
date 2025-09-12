# PyLighter - Lighter Protocol 网格交易机器人

专为 Lighter Protocol 去中心化交易所开发的 Python 网格交易机器人，实现高频自动化交易策略。

## 快速开始

### 安装依赖
```bash
uv sync
```

### 环境配置
创建 `.env` 文件：
```bash
LIGHTER_KEY=0x... # 你的钱包地址  
LIGHTER_SECRET=... # 你的 API KEY
API_KEY_INDEX=1   # API KEY 索引，需要和 API KEY 匹配（可选，默认为1）
```

### 网格策略快速启动
```bash
# 模拟测试（推荐先运行）
uv run grid_strategy.py --dry-run --symbol SUI

# 实盘交易
uv run grid_strategy.py --symbol SUI

# 自定义参数
uv run grid_strategy.py --symbol TON --dry-run --max-orders 10 --order-amount 20.0

# 其他支持币种
uv run grid_strategy.py --symbol TON --dry-run
uv run grid_strategy.py --symbol BTC --dry-run
```

### 命令行参数
```bash
# 查看所有参数
uv run grid_strategy.py --help

# 主要参数说明
--dry-run              # 模拟模式，无真实交易
--symbol SYMBOL        # 交易符号 (默认: TON)
--order-amount AMOUNT  # 每个订单金额USD (默认: $10.0)
--max-orders N         # 每个市场最大订单数 (默认: 50)
```

## 项目结构

```
pylighter/
├── pylighter/              # 核心 SDK
│   ├── client.py           # 主要客户端类
│   └── httpx.py            # HTTP 客户端
├── examples/               # 示例代码
├── docs/                   # 文档
├── grid_strategy.py        # 网格策略 (主要文件)
└── main.py                 # 主入口
```

## 核心功能

### 🤖 网格交易策略 (推荐)

**自动化高频交易机器人**，基于 Binance 网格策略完全重构：

#### 核心特性
- ✅ **0% 手续费优势**: Lighter Protocol 零手续费，每笔交易纯利润  
- ✅ **高频策略**: 0.03% 网格间距，100x 频率于传统交易所
- ✅ **双向持仓**: 同时做多/做空，最大化收益机会
- ✅ **智能风控**: 5x 杠杆，订单限制，自动清理
- ✅ **实时同步**: WebSocket 实时价格和订单状态
- ✅ **稳定重连**: 自动重连机制，确保 24/7 稳定运行

#### 支持币种
- **TON**: 默认适配币种 (杠杆5x, 网格0.03%)
- **SUI**: 高频策略优化
- **BTC**: 高价值币种支持
- **ETH**: 大资金池策略

#### 安全特性
```bash
# 信号处理 - Ctrl+C 优雅关闭
✅ 自动取消所有活跃订单
✅ 保留现有持仓 (防止意外损失)
✅ 完整状态清理

# 订单管理
✅ 可配置订单数限制 (默认50个/市场)
✅ 智能订单同步 (每5分钟)
✅ WebSocket 实时订单状态
✅ 自动过期订单清理 (30分钟)
✅ API调用频率控制 (防止接口限制)
```

### 📚 基础 SDK 功能

```python
from pylighter.client import Lighter

# 初始化客户端
lighter = Lighter(key="your_key", secret="your_secret")
await lighter.init_client()

# 下限价单
tx_info, tx_hash, error = await lighter.limit_order(
    ticker="SUI",
    amount=3.0,  # 正数=买入/做多，负数=卖出/做空
    price=4.25,
    tif='GTC'
)

# 获取账户信息
account_info = await lighter.get_account_info()

# 查看持仓
positions = await lighter.get_positions()

# 取消所有订单
await lighter.cancel_all_orders()
```

## 使用指南

### 🚀 网格策略启动流程

1. **环境准备**
```bash
# 克隆项目
git clone <repository_url>
cd pylighter

# 安装依赖
uv sync

# 配置环境变量
echo "LIGHTER_KEY=0x..." > .env
echo "LIGHTER_SECRET=..." >> .env
echo "API_KEY_INDEX=1" >> .env
```

2. **策略测试**
```bash
# 模拟模式测试 (无风险)
uv run grid_strategy.py --dry-run --symbol TON

# 自定义订单限制和金额
uv run grid_strategy.py --dry-run --symbol TON --max-orders 20 --order-amount 15.0

# 超保守模式 (少量订单)
uv run grid_strategy.py --dry-run --symbol BTC --max-orders 5 --order-amount 50.0

# 检查日志
tail -f log/grid_strategy.log
```

3. **实盘部署**
```bash
# 启动实盘交易 (需要输入 YES 确认)
uv run grid_strategy.py --symbol TON

# 自定义风险参数
uv run grid_strategy.py --symbol TON --max-orders 30 --order-amount 20.0

# 高频小单策略
uv run grid_strategy.py --symbol SUI --max-orders 100 --order-amount 5.0

# 优雅停止 (Ctrl+C)
# 自动取消订单并保留持仓
```

### 📊 监控和管理

```bash
# 实时监控日志
tail -f log/grid_strategy.log

# 查看策略运行状态
grep "📋 Orders" log/grid_strategy.log | tail -10

# 检查错误和警告
grep -E "(ERROR|WARNING)" log/grid_strategy.log | tail -5
```

## ⚠️ 重要提醒

### 🔐 安全风险
- **真实资金交易**: 请先小额测试，熟悉策略后再增加资金
- **私钥安全**: 妥善保管私钥，使用 `.env` 文件，不要提交到代码库
- **网络风险**: 确保网络连接稳定，避免在不稳定网络环境下运行

### 📋 交易风险
- **市场风险**: 网格策略适合震荡行情，单边行情可能导致亏损
- **杠杆风险**: 5x 杠杆会放大收益和损失，请谨慎使用
- **技术风险**: 程序故障可能导致意外损失，建议监控运行状态

### 🛠️ 技术要求
- **Python 版本**: 需要 Python ≥3.13
- **依赖管理**: 使用 `uv` 包管理器
- **API 访问**: 需要有效的 Lighter Protocol 账户和 API 密钥

## 🔧 故障排除

### 常见问题

**Q: 如何调整订单数量控制风险？**
```bash
# 保守策略 - 少量订单
uv run grid_strategy.py --symbol TON --max-orders 10

# 积极策略 - 更多订单（需要充足资金）
uv run grid_strategy.py --symbol TON --max-orders 50

# 查看当前订单状态
grep "Active orders:" log/grid_strategy.log | tail -5
```

**Q: 订单达到限制无法下单？**
```bash
# 检查当前订单计数
grep "Max.*orders reached" log/grid_strategy.log | tail -5

# 程序会自动在5分钟内同步并恢复下单
# 或手动调整限制参数重启
uv run grid_strategy.py --symbol TON --max-orders 100
```

**Q: WebSocket 连接频繁断开**
```bash
# 检查网络连接稳定性
ping mainnet.zklighter.elliot.ai

# 查看 WebSocket 重连日志
grep "Retrying WebSocket" log/grid_strategy.log
```

**Q: 订单无法成交**
```bash
# 检查市场流动性和价格设置
grep "Order placed" log/grid_strategy.log | tail -5

# 查看订单同步状态
grep "📋 Orders" log/grid_strategy.log | tail -10
```

**Q: 程序意外退出**
```bash
# 查看错误日志
grep "ERROR" log/grid_strategy.log | tail -10

# 检查 API 密钥配置
cat .env
```

## 📊 技术架构

### 核心组件
- **`pylighter/client.py`**: 主要 API 客户端，封装 Lighter Protocol REST API
- **`pylighter/httpx.py`**: HTTP 客户端，处理网络请求和错误重试
- **`grid_strategy.py`**: 网格交易策略核心实现

### 设计特点
- **异步架构**: 全异步设计，支持高并发 WebSocket 和 API 调用
- **错误恢复**: 自动重连和错误重试机制
- **状态管理**: 精确的订单和持仓状态跟踪
- **日志系统**: 详细的运行日志，便于监控和调试

## 📖 更多资源

### 参考文档
- [Lighter Protocol 官方文档](https://docs.lighter.xyz/)
- [项目内文档](docs/) - API 参考和策略指南
- [示例代码](examples/) - 实用示例和测试脚本

### 社区支持
- 查看 [issues](https://github.com/your-repo/issues) 获取帮助
- 参考 [CLAUDE.md](CLAUDE.md) 了解开发信息

---

**免责声明**: 本工具仅供学习和研究使用，请自行承担交易风险。开发者不对使用本工具造成的任何损失负责。
