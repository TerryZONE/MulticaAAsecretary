"""
博主信息和帖子获取工具
"""

import asyncio
import re
from typing import Dict, List

from .weibo_client import WeiboAPIClient


def _clean_html(text: str) -> str:
    """Remove HTML tags from text."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text)


def _parse_count(value) -> int:
    """Parse count values like '20.2万' or '1.4万' to integers."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value.endswith("万"):
            try:
                return int(float(value[:-1]) * 10000)
            except ValueError:
                return 0
        if value.endswith("亿"):
            try:
                return int(float(value[:-1]) * 100000000)
            except ValueError:
                return 0
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _extract_user_info(user_data: Dict) -> Dict:
    """Extract structured user info from API response."""
    user_info = user_data.get("userInfo", {})
    return {
        "id": str(user_info.get("id", "")),
        "nickname": user_info.get("screen_name", ""),
        "description": user_info.get("description", ""),
        "gender": user_info.get("gender", ""),
        "followers_count": _parse_count(user_info.get("followers_count", 0)),
        "followers_count_raw": str(user_info.get("followers_count", "")),
        "follow_count": _parse_count(user_info.get("follow_count", 0)),
        "statuses_count": _parse_count(user_info.get("statuses_count", 0)),
        "verified": user_info.get("verified", False),
        "verified_reason": user_info.get("verified_reason", ""),
        "avatar_hd": user_info.get("avatar_hd", ""),
        "profile_url": user_info.get("profile_url", ""),
        "mbrank": user_info.get("mbrank", 0),  # 会员等级
        "urank": user_info.get("urank", 0),  # 用户等级
    }


async def get_creator_info(client: WeiboAPIClient, creator_id: str) -> Dict:
    """Get creator profile information."""
    raw_data = await client.get_creator_info(creator_id)
    return _extract_user_info(raw_data)


async def get_creator_posts(
    client: WeiboAPIClient,
    creator_id: str,
    max_count: int = 20,
) -> Dict:
    """Get recent posts from a creator."""
    # The posts container ID is always 107603 + user_id
    container_id = f"107603{creator_id}"

    posts = []
    since_id = "0"
    crawl_count = 0

    while len(posts) < max_count:
        data = await client.get_creator_posts(creator_id, container_id, since_id)

        if not data:
            break

        cards = data.get("cards", [])
        if not cards:
            break

        for card in cards:
            if card.get("card_type") != 9:
                continue
            mblog = card.get("mblog", {})
            if not mblog:
                continue

            user = mblog.get("user", {})
            post = {
                "post_id": mblog.get("id", ""),
                "mid": mblog.get("mid", ""),
                "text": _clean_html(mblog.get("text", "")),
                "raw_text": mblog.get("text", ""),
                "created_at": mblog.get("created_at", ""),
                "source": mblog.get("source", ""),
                "reposts_count": mblog.get("reposts_count", 0),
                "comments_count": mblog.get("comments_count", 0),
                "attitudes_count": mblog.get("attitudes_count", 0),
                "pics": [pic.get("url", "") for pic in mblog.get("pics", [])],
                "is_long_text": mblog.get("isLongText", False),
            }
            posts.append(post)

            if len(posts) >= max_count:
                break

        # Get next page
        since_id = data.get("cardlistInfo", {}).get("since_id", "0")
        if not since_id or since_id == "0":
            break

        crawl_count += 1
        if crawl_count > 5:  # Safety limit
            break

        await asyncio.sleep(1.5)  # Rate limiting

    return {
        "creator_id": creator_id,
        "total_posts": len(posts),
        "posts": posts,
    }


async def get_all_creator_posts(
    client: WeiboAPIClient,
    creator_id: str,
    max_count: int = 200,
) -> Dict:
    """Get ALL posts by a creator (up to max_count). Iterates through all pages."""
    raw_cards = await client.get_all_creator_posts(
        creator_id, max_count=max_count, crawl_interval=2.0
    )

    posts = []
    for card in raw_cards:
        mblog = card.get("mblog", {})
        if not mblog:
            continue
        post = {
            "post_id": mblog.get("id", ""),
            "mid": mblog.get("mid", ""),
            "text": _clean_html(mblog.get("text", "")),
            "created_at": mblog.get("created_at", ""),
            "source": mblog.get("source", ""),
            "reposts_count": mblog.get("reposts_count", 0),
            "comments_count": mblog.get("comments_count", 0),
            "attitudes_count": mblog.get("attitudes_count", 0),
            "pics": [pic.get("url", "") for pic in mblog.get("pics", [])],
            "is_long_text": mblog.get("isLongText", False),
        }
        posts.append(post)

    return {
        "creator_id": creator_id,
        "total_posts": len(posts),
        "posts": posts,
    }


async def get_post_detail(
    client: WeiboAPIClient,
    post_id: str,
) -> Dict:
    """Get full post detail by ID. Includes full text for long posts."""
    raw = await client.get_post_detail(post_id)
    if not raw:
        return {"error": f"Post {post_id} not found or unable to parse"}

    user = raw.get("user", {})
    pics = raw.get("pics", [])

    return {
        "post_id": raw.get("id", post_id),
        "mid": raw.get("mid", ""),
        "text": _clean_html(raw.get("text", "")),
        "raw_text": raw.get("text", ""),
        "created_at": raw.get("created_at", ""),
        "source": raw.get("source", ""),
        "reposts_count": raw.get("reposts_count", 0),
        "comments_count": raw.get("comments_count", 0),
        "attitudes_count": raw.get("attitudes_count", 0),
        "is_long_text": raw.get("isLongText", False),
        "pics": [pic.get("url", "") if isinstance(pic, dict) else pic for pic in pics],
        "author": {
            "id": str(user.get("id", "")),
            "nickname": user.get("screen_name", ""),
            "verified": user.get("verified", False),
            "verified_reason": user.get("verified_reason", ""),
            "followers_count": _parse_count(user.get("followers_count", 0)),
        },
    }
