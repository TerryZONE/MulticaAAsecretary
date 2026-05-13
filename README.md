# MulticaAAsecretary

偶像资讯专家 AI Agent — 基于微博数据的 MCP Server，部署在 [Multica](https://multica.ai) 平台。

## 功能

通过 15 个 MCP 工具提供完整的微博数据能力：

| 类别 | 工具 | 说明 |
|------|------|------|
| 搜索 | `weibo_search` | 关键词搜索（综合/实时/热门/视频） |
| 帖子 | `weibo_post_detail` | 帖子完整详情（含长文全文） |
| 帖子 | `weibo_download_images` | 高清图片下载（绕过防盗链） |
| 博主 | `weibo_creator_info` | 博主基本信息 |
| 博主 | `weibo_creator_posts` | 最近N条帖子 |
| 博主 | `weibo_all_creator_posts` | 全量历史帖子 |
| 评论 | `weibo_post_comments` | 一级评论 |
| 评论 | `weibo_post_comments_full` | 含子评论/楼中楼 |
| 状态 | `weibo_check_login` | Cookie 有效性检查 |
| 追踪 | `add_tracked_creator` | 添加追踪博主 |
| 追踪 | `remove_tracked_creator` | 移除追踪博主 |
| 追踪 | `list_tracked_creators` | 列出追踪列表 |
| 分析 | `get_follower_trend` | 粉丝变化趋势 |
| 分析 | `get_daily_digest` | 每日摘要 |
| 快照 | `record_snapshot` | 数据快照 |

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/TerryZONE/MulticaAAsecretary.git
cd MulticaAAsecretary
```

### 2. 安装 MediaCrawler（底层爬虫依赖）

```bash
git clone https://github.com/NanmiCoder/MediaCrawler.git
```

### 3. 安装 MCP Server 依赖

```bash
cd mcp-server
pip install mcp httpx aiosqlite pydantic
```

### 4. 配置微博 Cookie

```bash
cd ..
python3 setup_cookies.py --cookie "你的微博cookie"
```

获取 cookie 方法：打开 m.weibo.cn → F12 → Network → 任意请求 → Cookie

### 5. 启动 MCP Server

```bash
cd mcp-server
python3 server.py
```

## 项目结构

```
MulticaAAsecretary/
├── mcp-server/           # MCP Server 主体
│   ├── server.py         # 入口，注册 15 个工具
│   ├── tools/
│   │   ├── weibo_client.py  # 微博 API 客户端
│   │   ├── search.py        # 搜索工具
│   │   ├── creator.py       # 博主信息/帖子
│   │   ├── comments.py      # 评论（含子评论）
│   │   ├── images.py        # 图片下载
│   │   └── tracker.py       # 追踪/快照/日报
│   ├── db/
│   │   └── store.py         # SQLite 持久化
│   └── pyproject.toml
├── skill/
│   └── SKILL.md          # Multica Agent Skill 定义
├── setup_cookies.py      # Cookie 配置工具
├── .mcp.json             # Claude Code MCP 配置
└── MediaCrawler/         # (需单独克隆) 底层爬虫
```

## Multica 部署

1. 在 Multica 创建 Agent，选择 Claude Code runtime
2. 从 GitHub 导入 `skill/SKILL.md` 作为 Skill
3. 配置 MCP Server 指向 `mcp-server/server.py`
4. 设置 Autopilot 定时任务

## License

仅供学习研究使用，不得用于商业目的。
