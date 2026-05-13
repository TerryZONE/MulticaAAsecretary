"""
博主追踪和数据快照工具
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from db.store import Database
from .weibo_client import WeiboAPIClient
from .creator import get_creator_info, get_creator_posts


def _parse_weibo_datetime(dt_str: str) -> str:
    """Parse Weibo datetime string to ISO format date string.
    
    Input formats:
    - 'Wed May 13 13:26:16 +0800 2026'
    - '1小时前', '刚刚', '今天 12:30'
    """
    if not dt_str:
        return ""
    
    # Handle relative time
    now = datetime.now()
    if "刚刚" in dt_str:
        return now.isoformat()
    if "分钟前" in dt_str:
        try:
            minutes = int(dt_str.replace("分钟前", "").strip())
            return (now - timedelta(minutes=minutes)).isoformat()
        except ValueError:
            return now.isoformat()
    if "小时前" in dt_str:
        try:
            hours = int(dt_str.replace("小时前", "").strip())
            return (now - timedelta(hours=hours)).isoformat()
        except ValueError:
            return now.isoformat()
    if "今天" in dt_str:
        time_part = dt_str.replace("今天", "").strip()
        return f"{now.date().isoformat()} {time_part}"
    if "昨天" in dt_str:
        time_part = dt_str.replace("昨天", "").strip()
        yesterday = now - timedelta(days=1)
        return f"{yesterday.date().isoformat()} {time_part}"
    
    # Handle standard format: 'Wed May 13 13:26:16 +0800 2026'
    try:
        parsed = datetime.strptime(dt_str, "%a %b %d %H:%M:%S %z %Y")
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    
    # Handle format without timezone: 'Mon Jan 01 12:00:00 2026'
    try:
        parsed = datetime.strptime(dt_str, "%a %b %d %H:%M:%S %Y")
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    
    # Fallback: return as-is
    return dt_str


async def add_tracked_creator(
    db: Database,
    creator_id: str,
    nickname: str,
    note: str = "",
) -> Dict:
    """Add a creator to the tracking list."""
    await db.execute(
        """
        INSERT OR REPLACE INTO tracked_creators (creator_id, nickname, note, added_at)
        VALUES (?, ?, ?, ?)
        """,
        (creator_id, nickname, note, datetime.now().isoformat()),
    )
    return {
        "status": "success",
        "message": f"已添加追踪博主: {nickname} (ID: {creator_id})",
    }


async def remove_tracked_creator(db: Database, creator_id: str) -> Dict:
    """Remove a creator from the tracking list."""
    await db.execute(
        "DELETE FROM tracked_creators WHERE creator_id = ?", (creator_id,)
    )
    return {
        "status": "success",
        "message": f"已移除追踪博主 (ID: {creator_id})",
    }


async def list_tracked_creators(db: Database) -> Dict:
    """List all tracked creators."""
    rows = await db.fetchall(
        """
        SELECT creator_id, nickname, note, added_at,
               (SELECT followers_count FROM follower_snapshots
                WHERE creator_id = tc.creator_id
                ORDER BY snapshot_time DESC LIMIT 1) as latest_followers
        FROM tracked_creators tc
        ORDER BY added_at DESC
        """
    )
    creators = []
    for row in rows:
        creators.append({
            "creator_id": row[0],
            "nickname": row[1],
            "note": row[2],
            "added_at": row[3],
            "latest_followers": row[4],
        })

    return {
        "total": len(creators),
        "creators": creators,
    }


async def get_follower_trend(
    db: Database,
    creator_id: str,
    days: int = 7,
) -> Dict:
    """Get follower count trend for a tracked creator."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = await db.fetchall(
        """
        SELECT snapshot_time, followers_count, follow_count, statuses_count
        FROM follower_snapshots
        WHERE creator_id = ? AND snapshot_time >= ?
        ORDER BY snapshot_time ASC
        """,
        (creator_id, since),
    )

    data_points = []
    for row in rows:
        data_points.append({
            "time": row[0],
            "followers_count": row[1],
            "follow_count": row[2],
            "statuses_count": row[3],
        })

    # Calculate change
    change = 0
    if len(data_points) >= 2:
        change = data_points[-1]["followers_count"] - data_points[0]["followers_count"]

    # Get nickname
    nickname_row = await db.fetchone(
        "SELECT nickname FROM tracked_creators WHERE creator_id = ?", (creator_id,)
    )
    nickname = nickname_row[0] if nickname_row else creator_id

    return {
        "creator_id": creator_id,
        "nickname": nickname,
        "days": days,
        "data_points": data_points,
        "follower_change": change,
        "total_snapshots": len(data_points),
    }


async def get_daily_digest(
    db: Database,
    client: WeiboAPIClient,
    creator_id: str = "",
) -> Dict:
    """Get daily digest for tracked creators."""
    if creator_id:
        creators = await db.fetchall(
            "SELECT creator_id, nickname FROM tracked_creators WHERE creator_id = ?",
            (creator_id,),
        )
    else:
        creators = await db.fetchall(
            "SELECT creator_id, nickname FROM tracked_creators"
        )

    if not creators:
        return {"message": "没有追踪的博主", "digests": []}

    digests = []
    today = datetime.now().date().isoformat()

    for cid, nickname in creators:
        digest = {"creator_id": cid, "nickname": nickname}

        # Get today's new posts from DB
        new_posts = await db.fetchall(
            """
            SELECT post_id, text_content, created_at, reposts_count,
                   comments_count, attitudes_count
            FROM posts
            WHERE creator_id = ? AND date(created_at) = ?
            ORDER BY created_at DESC
            """,
            (cid, today),
        )
        digest["new_posts_today"] = len(new_posts)
        digest["posts"] = [
            {
                "post_id": p[0],
                "text": p[1][:100] if p[1] else "",
                "created_at": p[2],
                "reposts": p[3],
                "comments": p[4],
                "likes": p[5],
            }
            for p in new_posts
        ]

        # Get follower change today
        today_snapshots = await db.fetchall(
            """
            SELECT followers_count, snapshot_time
            FROM follower_snapshots
            WHERE creator_id = ? AND date(snapshot_time) = ?
            ORDER BY snapshot_time
            """,
            (cid, today),
        )
        if len(today_snapshots) >= 2:
            digest["follower_change_today"] = (
                today_snapshots[-1][0] - today_snapshots[0][0]
            )
        else:
            digest["follower_change_today"] = 0

        digests.append(digest)

    return {
        "date": today,
        "total_creators": len(digests),
        "digests": digests,
    }


async def record_snapshot(db: Database, client: WeiboAPIClient) -> Dict:
    """Record a data snapshot for all tracked creators."""
    creators = await db.fetchall(
        "SELECT creator_id, nickname FROM tracked_creators"
    )

    if not creators:
        return {"message": "没有追踪的博主", "snapshots": 0}

    results = []
    now = datetime.now().isoformat()

    for cid, nickname in creators:
        try:
            # Get creator info (followers, etc.)
            info = await get_creator_info(client, cid)

            # Record follower snapshot
            await db.execute(
                """
                INSERT INTO follower_snapshots
                (creator_id, followers_count, follow_count, statuses_count, snapshot_time)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    info.get("followers_count", 0),
                    info.get("follow_count", 0),
                    info.get("statuses_count", 0),
                    now,
                ),
            )

            # Get recent posts and save new ones
            posts_data = await get_creator_posts(client, cid, max_count=10)
            new_posts = 0
            for post in posts_data.get("posts", []):
                # Parse and normalize the datetime
                created_at = _parse_weibo_datetime(post["created_at"])
                # Insert or ignore (dedup by post_id)
                inserted = await db.execute(
                    """
                    INSERT OR IGNORE INTO posts
                    (post_id, creator_id, text_content, created_at,
                     reposts_count, comments_count, attitudes_count, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        post["post_id"],
                        cid,
                        post["text"],
                        created_at,
                        post["reposts_count"],
                        post["comments_count"],
                        post["attitudes_count"],
                        "",  # raw_json placeholder
                    ),
                )
                if inserted:
                    new_posts += 1

            results.append({
                "creator_id": cid,
                "nickname": nickname,
                "followers": info.get("followers_count", 0),
                "new_posts_found": new_posts,
                "status": "success",
            })

            await asyncio.sleep(2.0)  # Rate limiting between creators

        except Exception as e:
            results.append({
                "creator_id": cid,
                "nickname": nickname,
                "status": "error",
                "error": str(e),
            })

    return {
        "snapshot_time": now,
        "total_creators": len(creators),
        "results": results,
    }
