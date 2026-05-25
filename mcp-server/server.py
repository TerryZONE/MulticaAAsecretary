"""
Weibo Idol MCP Server - 偶像领域微博监控工具

通过 MCP 协议为 AI Agent 提供微博数据抓取能力。
直接调用微博移动端 API (m.weibo.cn)，复用 MediaCrawler 的 cookie。
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Ensure imports work regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from tools.weibo_client import WeiboAPIClient
from tools.search import search_weibo
from tools.creator import (
    get_creator_info,
    get_creator_posts,
    get_all_creator_posts,
    get_post_detail,
)
from tools.comments import get_post_comments, get_post_comments_with_sub
from tools.images import download_post_images
from tools.tracker import (
    add_tracked_creator,
    list_tracked_creators,
    remove_tracked_creator,
    get_follower_trend,
    get_daily_digest,
    record_snapshot,
)
from db.store import Database

# Setup logging
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("weibo-idol-mcp")

# Paths
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
DB_PATH = BASE_DIR / "data" / "idol_monitor.db"
MEDIACRAWLER_DIR = BASE_DIR.parent / "MediaCrawler"

# Global state
server = Server("weibo-idol-mcp")
db: Database = None
client: WeiboAPIClient = None


def load_config() -> dict:
    """Load configuration from config.json"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"cookies": "", "tracked_creators": []}


def save_config(cfg: dict):
    """Save configuration to config.json"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # === 搜索 ===
        Tool(
            name="weibo_search",
            description="按关键词搜索微博帖子。返回搜索结果列表，包含帖子内容、作者、互动数据等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                    "page": {
                        "type": "integer",
                        "description": "页码，默认第1页",
                        "default": 1,
                    },
                    "search_type": {
                        "type": "string",
                        "enum": ["default", "real_time", "popular", "video"],
                        "description": "搜索类型：default(综合), real_time(实时), popular(热门), video(视频)",
                        "default": "default",
                    },
                },
                "required": ["keyword"],
            },
        ),
        # === 帖子详情 ===
        Tool(
            name="weibo_post_detail",
            description="通过帖子ID获取微博帖子的完整详情。对于长文会自动获取全文内容（不截断）。返回完整文本、作者信息、互动数据、图片列表等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "post_id": {
                        "type": "string",
                        "description": "微博帖子ID（mid）",
                    },
                },
                "required": ["post_id"],
            },
        ),
        # === 博主信息 ===
        Tool(
            name="weibo_creator_info",
            description="获取微博博主的基本信息，包括昵称、粉丝数、关注数、简介、认证信息等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "creator_id": {
                        "type": "string",
                        "description": "博主的微博用户ID（数字ID）",
                    },
                },
                "required": ["creator_id"],
            },
        ),
        # === 博主帖子（最近） ===
        Tool(
            name="weibo_creator_posts",
            description="获取指定博主的最新帖子列表（默认最近20条）。返回帖子内容、发布时间、互动数据。",
            inputSchema={
                "type": "object",
                "properties": {
                    "creator_id": {
                        "type": "string",
                        "description": "博主的微博用户ID（数字ID）",
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "最多获取帖子数量，默认20",
                        "default": 20,
                    },
                },
                "required": ["creator_id"],
            },
        ),
        # === 博主全部帖子 ===
        Tool(
            name="weibo_all_creator_posts",
            description="获取博主的全部历史帖子（翻页遍历所有帖子）。适合做全量数据分析。注意：帖子多的博主耗时较长。",
            inputSchema={
                "type": "object",
                "properties": {
                    "creator_id": {
                        "type": "string",
                        "description": "博主的微博用户ID（数字ID）",
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "最多获取帖子数量，默认200，最大500",
                        "default": 200,
                    },
                },
                "required": ["creator_id"],
            },
        ),
        # === 帖子评论（基础） ===
        Tool(
            name="weibo_post_comments",
            description="获取某条微博帖子的一级评论列表。",
            inputSchema={
                "type": "object",
                "properties": {
                    "post_id": {
                        "type": "string",
                        "description": "微博帖子ID（mid）",
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "最多获取评论数量，默认20",
                        "default": 20,
                    },
                },
                "required": ["post_id"],
            },
        ),
        # === 帖子评论（含子评论） ===
        Tool(
            name="weibo_post_comments_full",
            description="获取某条微博帖子的评论列表，包含子评论（楼中楼/回复）。子评论嵌套在父评论下。",
            inputSchema={
                "type": "object",
                "properties": {
                    "post_id": {
                        "type": "string",
                        "description": "微博帖子ID（mid）",
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "最多获取评论总数（含子评论），默认50",
                        "default": 50,
                    },
                },
                "required": ["post_id"],
            },
        ),
        # === 图片下载 ===
        Tool(
            name="weibo_download_images",
            description="下载微博帖子中的图片到本地。图片通过代理下载以绕过防盗链。保存到 data/images/{post_id}/ 目录。",
            inputSchema={
                "type": "object",
                "properties": {
                    "post_id": {
                        "type": "string",
                        "description": "微博帖子ID",
                    },
                    "image_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "图片URL列表。可从 weibo_post_detail 或 weibo_creator_posts 的 pics 字段获取。",
                    },
                },
                "required": ["post_id", "image_urls"],
            },
        ),
        # === 登录状态检查 ===
        Tool(
            name="weibo_check_login",
            description="检查当前微博Cookie是否有效（是否处于登录状态）。如果返回未登录，需要更新Cookie。",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # === 追踪管理 ===
        Tool(
            name="add_tracked_creator",
            description="添加一个博主到追踪列表。添加后会定期记录其粉丝数、新帖子等数据。",
            inputSchema={
                "type": "object",
                "properties": {
                    "creator_id": {
                        "type": "string",
                        "description": "博主的微博用户ID（数字ID）",
                    },
                    "nickname": {
                        "type": "string",
                        "description": "博主昵称（方便识别）",
                    },
                    "note": {
                        "type": "string",
                        "description": "备注信息",
                        "default": "",
                    },
                },
                "required": ["creator_id", "nickname"],
            },
        ),
        Tool(
            name="remove_tracked_creator",
            description="从追踪列表中移除一个博主。",
            inputSchema={
                "type": "object",
                "properties": {
                    "creator_id": {
                        "type": "string",
                        "description": "博主的微博用户ID（数字ID）",
                    },
                },
                "required": ["creator_id"],
            },
        ),
        Tool(
            name="list_tracked_creators",
            description="列出当前所有追踪中的博主及其基本信息。",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_follower_trend",
            description="获取某个追踪博主的粉丝数变化趋势（最近N天）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "creator_id": {
                        "type": "string",
                        "description": "博主的微博用户ID",
                    },
                    "days": {
                        "type": "integer",
                        "description": "查看最近多少天的数据，默认7天",
                        "default": 7,
                    },
                },
                "required": ["creator_id"],
            },
        ),
        Tool(
            name="get_daily_digest",
            description="获取追踪博主的每日摘要：今天的新帖子、新评论、粉丝变化等。可指定某个博主或获取全部追踪博主的摘要。",
            inputSchema={
                "type": "object",
                "properties": {
                    "creator_id": {
                        "type": "string",
                        "description": "博主的微博用户ID。留空则获取所有追踪博主的摘要。",
                        "default": "",
                    },
                },
            },
        ),
        Tool(
            name="record_snapshot",
            description="立即为所有追踪博主记录一次数据快照（粉丝数、最新帖子等）。通常由定时任务调用。",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global db, client

    try:
        if name == "weibo_search":
            result = await search_weibo(
                client,
                keyword=arguments["keyword"],
                page=arguments.get("page", 1),
                search_type=arguments.get("search_type", "default"),
            )
        elif name == "weibo_post_detail":
            result = await get_post_detail(client, arguments["post_id"])
        elif name == "weibo_creator_info":
            result = await get_creator_info(client, arguments["creator_id"])
        elif name == "weibo_creator_posts":
            result = await get_creator_posts(
                client,
                creator_id=arguments["creator_id"],
                max_count=arguments.get("max_count", 20),
            )
        elif name == "weibo_all_creator_posts":
            max_count = min(arguments.get("max_count", 200), 500)
            result = await get_all_creator_posts(
                client,
                creator_id=arguments["creator_id"],
                max_count=max_count,
            )
        elif name == "weibo_post_comments":
            result = await get_post_comments(
                client,
                post_id=arguments["post_id"],
                max_count=arguments.get("max_count", 20),
            )
        elif name == "weibo_post_comments_full":
            result = await get_post_comments_with_sub(
                client,
                post_id=arguments["post_id"],
                max_count=arguments.get("max_count", 50),
            )
        elif name == "weibo_download_images":
            result = await download_post_images(
                client,
                post_id=arguments["post_id"],
                image_urls=arguments["image_urls"],
            )
        elif name == "weibo_check_login":
            logged_in = await client.check_login()
            result = {
                "logged_in": logged_in,
                "message": "Cookie有效，已登录" if logged_in else "Cookie无效或已过期，请更新Cookie",
            }
        elif name == "add_tracked_creator":
            result = await add_tracked_creator(
                db,
                creator_id=arguments["creator_id"],
                nickname=arguments["nickname"],
                note=arguments.get("note", ""),
            )
        elif name == "remove_tracked_creator":
            result = await remove_tracked_creator(db, arguments["creator_id"])
        elif name == "list_tracked_creators":
            result = await list_tracked_creators(db)
        elif name == "get_follower_trend":
            result = await get_follower_trend(
                db,
                creator_id=arguments["creator_id"],
                days=arguments.get("days", 7),
            )
        elif name == "get_daily_digest":
            result = await get_daily_digest(
                db,
                client,
                creator_id=arguments.get("creator_id", ""),
            )
        elif name == "record_snapshot":
            result = await record_snapshot(db, client)
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    except Exception as e:
        logger.error(f"Tool {name} failed: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


async def main():
    global db, client

    # Initialize database
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = Database(str(DB_PATH))
    await db.initialize()

    # Load config and initialize Weibo client
    cfg = load_config()
    cookies = cfg.get("cookies", "")
    if not cookies:
        logger.warning("No cookies configured. Please set cookies in config.json first.")
        logger.warning("You can get cookies by running MediaCrawler with QR code login first.")

    client = WeiboAPIClient(cookies=cookies)

    logger.info("Weibo Idol MCP Server starting...")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
