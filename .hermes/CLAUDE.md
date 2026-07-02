# MulticaAAsecretary

偶像资讯专家 AI Agent。微博监控 MCP Server。追踪偶像团体动态（演出、舞台、综艺），自动推送。

## 技术栈
- Python 3（MCP Server）
- 微博监控
- MCP 协议

## 目录结构
- `mcp-server/` — MCP 服务端
- `dashboard.py` — 仪表盘
- `start_mcp.py` — 启动入口
- `setup_cookies.py` — Cookie 设置
- `mcp-config.json`, `.mcp.json` — MCP 配置

## 引用关系
- **被调用** — 通过 MCP 协议被 Hermes Agent 调用

## Git
- remote: https://github.com/TerryZONE/MulticaAAsecretary.git (master)
