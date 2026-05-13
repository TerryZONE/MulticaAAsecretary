"""
微博搜索工具
"""

import re
from typing import Dict, List

from .weibo_client import WeiboAPIClient


def _clean_html(text: str) -> str:
    """Remove HTML tags from text."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text)


def _extract_post_info(card: Dict) -> Dict:
    """Extract useful info from a search result card."""
    mblog = card.get("mblog", {})
    if not mblog:
        return None

    user = mblog.get("user", {})
    return {
        "post_id": mblog.get("id", ""),
        "mid": mblog.get("mid", ""),
        "text": _clean_html(mblog.get("text", "")),
        "created_at": mblog.get("created_at", ""),
        "source": mblog.get("source", ""),
        "reposts_count": mblog.get("reposts_count", 0),
        "comments_count": mblog.get("comments_count", 0),
        "attitudes_count": mblog.get("attitudes_count", 0),
        "author": {
            "id": str(user.get("id", "")),
            "nickname": user.get("screen_name", ""),
            "verified": user.get("verified", False),
            "verified_reason": user.get("verified_reason", ""),
            "followers_count": user.get("followers_count", 0),
        },
        "pics": [pic.get("url", "") for pic in mblog.get("pics", [])],
    }


async def search_weibo(
    client: WeiboAPIClient,
    keyword: str,
    page: int = 1,
    search_type: str = "default",
) -> Dict:
    """
    Search Weibo by keyword and return structured results.
    """
    raw_data = await client.search(keyword, page, search_type)

    # Extract cards from search results
    cards = raw_data.get("cards", [])
    posts = []

    for card in cards:
        if card.get("card_type") == 9:
            post = _extract_post_info(card)
            if post:
                posts.append(post)
        # Handle card groups (nested results)
        card_group = card.get("card_group", [])
        for sub_card in card_group:
            if sub_card.get("card_type") == 9:
                post = _extract_post_info(sub_card)
                if post:
                    posts.append(post)

    return {
        "keyword": keyword,
        "page": page,
        "search_type": search_type,
        "total_results": len(posts),
        "posts": posts,
    }
