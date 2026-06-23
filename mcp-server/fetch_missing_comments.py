"""
补抓恋恋Renren（微博ID: 7117031969）缺失评论数据
针对 posts 表中 comments_count > 0 但 comments 表中无记录的帖子
"""
import sys, json, sqlite3, asyncio, time
from datetime import datetime

sys.path.insert(0, '/Users/qingtingcheng/Documents/Claude/MulticaAAsecretary/mcp-server')
from tools.weibo_client import WeiboAPIClient

CREATOR_ID = '7117031969'
DB_PATH = '/Users/qingtingcheng/Documents/Claude/MulticaAAsecretary/mcp-server/data/idol_monitor.db'
CONFIG_PATH = '/Users/qingtingcheng/Documents/Claude/MulticaAAsecretary/mcp-server/config.json'


def parse_weibo_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return date_str


def get_missing_posts(db):
    cursor = db.cursor()
    cursor.execute('''
        SELECT p.post_id, p.comments_count, p.created_at
        FROM posts p
        WHERE p.creator_id = ?
          AND p.comments_count > 0
          AND p.post_id NOT IN (SELECT DISTINCT post_id FROM comments WHERE post_id IS NOT NULL)
        ORDER BY p.created_at DESC
    ''', (CREATOR_ID,))
    return cursor.fetchall()


def save_comments(db, post_id, comments):
    cursor = db.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    for c in comments:
        try:
            comment_id = str(c.get('id', ''))
            if not comment_id:
                continue
            text = c.get('text', '') or ''
            # Strip HTML tags simply
            import re
            text = re.sub(r'<[^>]+>', '', text)
            user = c.get('user') or {}
            author_id = str(user.get('id', '')) if user else ''
            author_nickname = user.get('screen_name', '') if user else ''
            created_at_raw = c.get('created_at', '')
            created_at = parse_weibo_date(created_at_raw) if created_at_raw else now
            like_count = c.get('like_count', 0) or 0

            cursor.execute('''
                INSERT OR IGNORE INTO comments
                    (comment_id, post_id, creator_id, text_content, author_id, author_nickname, created_at, like_count, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (comment_id, post_id, CREATOR_ID, text, author_id, author_nickname, created_at, like_count, now))
            if cursor.rowcount > 0:
                saved += 1
        except Exception as e:
            print(f'  [warn] Failed to save comment {c.get("id")}: {e}')
    db.commit()
    return saved


async def fetch_all_comments_for_post(client, post_id):
    """Fetch all comment pages for a post."""
    all_comments = []
    max_id = 0
    max_id_type = 0

    while True:
        try:
            result = await client.get_post_comments(post_id, max_id=max_id, max_id_type=max_id_type)
        except Exception as e:
            print(f'  [error] API error for post {post_id}: {e}')
            break

        if not result or not isinstance(result, dict):
            break

        # API returns {'data': [...], 'max_id': ..., 'max_id_type': ...}
        comments = result.get('data', [])
        if not comments:
            break

        all_comments.extend(comments)

        max_id = result.get('max_id', 0)
        max_id_type = result.get('max_id_type', 0)

        if not max_id:
            break

        await asyncio.sleep(1.5)

    return all_comments


async def main():
    config = json.load(open(CONFIG_PATH))
    client = WeiboAPIClient(cookies=config['cookies'])

    # Verify login
    if not await client.check_login():
        print('ERROR: Cookie expired. Please update config.json.')
        return

    db = sqlite3.connect(DB_PATH)

    missing = get_missing_posts(db)
    print(f'Posts missing comments: {len(missing)}')
    total_saved = 0
    failed_posts = []

    for idx, (post_id, expected_count, created_at) in enumerate(missing):
        print(f'[{idx+1}/{len(missing)}] post_id={post_id} expected={expected_count} date={created_at}')

        try:
            comments = await fetch_all_comments_for_post(client, post_id)
            saved = save_comments(db, post_id, comments)
            total_saved += saved
            print(f'  fetched={len(comments)} saved={saved}')
        except Exception as e:
            print(f'  [error] {e}')
            failed_posts.append(post_id)

        # Rate limiting
        await asyncio.sleep(2)

        # Every 30 posts, pause 30 seconds
        if (idx + 1) % 30 == 0:
            print(f'  [rate limit] Pausing 30s after {idx+1} posts...')
            await asyncio.sleep(30)

    db.close()

    print(f'\n=== Done ===')
    print(f'Total new comments saved: {total_saved}')
    if failed_posts:
        print(f'Failed posts ({len(failed_posts)}): {failed_posts}')


if __name__ == '__main__':
    asyncio.run(main())
