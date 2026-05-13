"""
SQLite 数据持久化层

存储追踪博主列表、粉丝数快照、帖子历史等数据。
"""

import aiosqlite


class Database:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection = None

    async def initialize(self):
        """Initialize database connection and create tables."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()

    async def _create_tables(self):
        """Create all required tables."""
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tracked_creators (
                creator_id TEXT PRIMARY KEY,
                nickname TEXT NOT NULL,
                note TEXT DEFAULT '',
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS follower_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id TEXT NOT NULL,
                followers_count INTEGER NOT NULL,
                follow_count INTEGER DEFAULT 0,
                statuses_count INTEGER DEFAULT 0,
                snapshot_time TEXT NOT NULL,
                FOREIGN KEY (creator_id) REFERENCES tracked_creators(creator_id)
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_creator_time
                ON follower_snapshots(creator_id, snapshot_time);

            CREATE TABLE IF NOT EXISTS posts (
                post_id TEXT PRIMARY KEY,
                creator_id TEXT NOT NULL,
                text_content TEXT,
                created_at TEXT,
                reposts_count INTEGER DEFAULT 0,
                comments_count INTEGER DEFAULT 0,
                attitudes_count INTEGER DEFAULT 0,
                raw_json TEXT DEFAULT '',
                fetched_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (creator_id) REFERENCES tracked_creators(creator_id)
            );

            CREATE INDEX IF NOT EXISTS idx_posts_creator_date
                ON posts(creator_id, created_at);

            CREATE TABLE IF NOT EXISTS comments (
                comment_id TEXT PRIMARY KEY,
                post_id TEXT NOT NULL,
                creator_id TEXT,
                text_content TEXT,
                author_id TEXT,
                author_nickname TEXT,
                created_at TEXT,
                like_count INTEGER DEFAULT 0,
                fetched_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (post_id) REFERENCES posts(post_id)
            );

            CREATE INDEX IF NOT EXISTS idx_comments_post
                ON comments(post_id, created_at);
            """
        )
        await self._conn.commit()

    async def execute(self, sql: str, params: tuple = ()) -> bool:
        """Execute a SQL statement. Returns True if rows were affected."""
        cursor = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cursor.rowcount > 0

    async def fetchall(self, sql: str, params: tuple = ()) -> list:
        """Execute a query and return all rows."""
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    async def fetchone(self, sql: str, params: tuple = ()):
        """Execute a query and return one row."""
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()

    async def close(self):
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
