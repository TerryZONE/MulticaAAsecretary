# Weibo Idol MCP Server

偶像领域微博监控 MCP Server，为 multica agent 提供微博数据抓取和分析工具。

## 功能

- `weibo_search` — 按关键词搜索微博
- `weibo_creator_posts` — 获取指定博主的最新帖子
- `weibo_post_comments` — 获取某条帖子的评论
- `weibo_creator_info` — 获取博主基本信息（粉丝数、关注数等）
- `list_tracked_creators` — 列出当前追踪的博主
- `add_tracked_creator` — 添加追踪博主
- `get_daily_digest` — 获取博主当天新帖/评论摘要
- `get_follower_trend` — 获取粉丝数变化趋势

## 使用

```bash
cd mcp-server
uv run server.py
```

## 配置

在 `config.json` 中配置追踪的博主列表和 cookie。
