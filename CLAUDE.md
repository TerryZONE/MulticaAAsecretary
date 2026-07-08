# MulticaAAsecretary — 会话须知

微博偶像数据 MCP Server（部署 Multica 平台）+ pilot 采集线。工具清单见 README.md。

## 两个数据面（别搞混）

- `pilot/data/archive.db` — **活数据**（采集线持续写入），已 gitignore 不进版本库；全局 sqlite MCP 指向这里
- `mcp-server/data/idol_monitor.db` — weibo-idol server 自建的追踪库（跟随 server.py 所在目录生成）

## 历史坑（2026-07-08 修复）

项目曾从 `~/Documents/Claude/MulticaAAsecretary/` 搬到 `company/` 下，全局 `~/.claude.json` 和本目录 `mcp-config.json` 里的 MCP 路径没跟着搬——导致 sqlite MCP 查了半个月空库、weibo-idol 每次启动失败还在旧址重建孤儿目录。**再搬目录时必须同步改这两处 MCP 配置。**

## 怎么跑 / 验证

- MCP server 本地起：`cd mcp-server && uv run server.py`；依赖 MediaCrawler（需另行 clone）
- 日采集：`node pilot/daily_collect.js`（分批轮换访客身份：每批 5 账号 + 20s 间歇，破解单身份 feed 配额）
- 验证数据是否在写：`sqlite3 pilot/data/archive.db "select count(*) from posts"` 前后对比

## 雷区

- Cookie 在 `config.json`，失效先跑 `weibo_check_login` 确认再排查代码
- `pilot/data/` 永远不进版本库（raw_json 会把仓库撑爆）
- 采集频率参数（批大小/间歇）是实测踩出来的配额线，改之前先看 git log 里的调参记录
