"""
评论获取工具（含子评论/楼中楼）
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


def _parse_comment(comment: Dict) -> Dict:
    """Parse a single comment into structured format."""
    user = comment.get("user", {})
    return {
        "comment_id": str(comment.get("id", "")),
        "text": _clean_html(comment.get("text", "")),
        "created_at": comment.get("created_at", ""),
        "like_count": comment.get("like_count", 0),
        "source": comment.get("source", ""),
        "author": {
            "id": str(user.get("id", "")),
            "nickname": user.get("screen_name", ""),
        },
        "reply_count": comment.get("total_number", 0),
        "has_sub_comments": bool(comment.get("comments")),
    }


async def get_post_comments(
    client: WeiboAPIClient,
    post_id: str,
    max_count: int = 20,
) -> Dict:
    """Get comments for a specific post (first-level only)."""
    comments = []
    max_id = 0
    max_id_type = 0

    while len(comments) < max_count:
        try:
            data = await client.get_post_comments(post_id, max_id, max_id_type)
        except Exception as e:
            if "还没有人评论" in str(e):
                break
            raise

        comment_list = data.get("data", [])
        if not comment_list:
            break

        for comment in comment_list:
            parsed = _parse_comment(comment)
            comments.append(parsed)
            if len(comments) >= max_count:
                break

        # Pagination
        max_id = data.get("max_id", 0)
        max_id_type = data.get("max_id_type", 0)
        if max_id == 0:
            break

        await asyncio.sleep(1.0)  # Rate limiting

    return {
        "post_id": post_id,
        "total_comments": len(comments),
        "comments": comments,
    }


async def get_post_comments_with_sub(
    client: WeiboAPIClient,
    post_id: str,
    max_count: int = 50,
) -> Dict:
    """
    Get comments for a post INCLUDING sub-comments (楼中楼/回复).
    Sub-comments are nested under their parent comment.
    """
    comments = []
    max_id = 0
    max_id_type = 0
    total_with_sub = 0

    while total_with_sub < max_count:
        try:
            data = await client.get_post_comments(post_id, max_id, max_id_type)
        except Exception as e:
            if "还没有人评论" in str(e):
                break
            raise

        comment_list = data.get("data", [])
        if not comment_list:
            break

        for comment in comment_list:
            parsed = _parse_comment(comment)

            # Extract sub-comments if present
            sub_comments_raw = comment.get("comments", [])
            if sub_comments_raw and isinstance(sub_comments_raw, list):
                parsed["sub_comments"] = [
                    _parse_comment(sub) for sub in sub_comments_raw
                ]
                total_with_sub += 1 + len(parsed["sub_comments"])
            else:
                parsed["sub_comments"] = []
                total_with_sub += 1

            comments.append(parsed)
            if total_with_sub >= max_count:
                break

        # Pagination
        max_id = data.get("max_id", 0)
        max_id_type = data.get("max_id_type", 0)
        if max_id == 0:
            break

        await asyncio.sleep(1.0)

    return {
        "post_id": post_id,
        "total_comments": len(comments),
        "total_with_sub_comments": total_with_sub,
        "comments": comments,
    }
