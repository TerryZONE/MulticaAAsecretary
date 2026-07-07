#!/usr/bin/env python3
"""初始化偶像档案库 archive.db 并迁移现有 network.csv / snapshots.csv。幂等，可重复执行。

设计原则：
- 采集求全（posts 存 raw_json），加工靠后
- 档案永不删：posts 只增不删；对方删博后我们仍保留，deleted_suspect 标记疑似被删日期
- 流水（posts/snapshots）与档案（profiles）正交：前者按时间，后者按人
"""
import csv
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data" / "archive.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  uid TEXT PRIMARY KEY,
  name TEXT,                 -- 当前昵称（会变，历史进 name_history）
  type TEXT, city TEXT, priority INTEGER,
  note TEXT,
  first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS name_history (
  uid TEXT, name TEXT, seen_date TEXT,
  PRIMARY KEY (uid, name)
);
CREATE TABLE IF NOT EXISTS posts (
  post_id TEXT PRIMARY KEY,
  uid TEXT,
  created_at TEXT,           -- 微博原始时间串（历史数据未转ISO则保留原样）
  text TEXT,
  is_long INTEGER DEFAULT 0, -- 1=长文被截断，全文需补采
  reposts INTEGER, comments INTEGER, likes INTEGER, pics INTEGER,
  rt_user TEXT, rt_text TEXT,
  raw_json TEXT,             -- 完整 mblog 对象，后续任何维度加工的原料
  first_fetched TEXT,
  last_seen TEXT,
  deleted_suspect TEXT       -- 疑似被删的检测日期（NULL=正常可见）
);
CREATE INDEX IF NOT EXISTS idx_posts_uid ON posts(uid);
CREATE TABLE IF NOT EXISTS snapshots (
  uid TEXT, date TEXT,
  followers_raw TEXT, followers INTEGER, statuses INTEGER,
  PRIMARY KEY (uid, date)
);
CREATE TABLE IF NOT EXISTS profiles (
  uid TEXT PRIMARY KEY,
  style TEXT,                -- 风格系别：王道/暗黑/元气/摇滚/和风/病娇…
  agency TEXT,               -- 厂牌/事务所归属
  role TEXT,                 -- 成员：担当/队长/兼任；团体：定位一句话
  fan_structure TEXT,        -- 粉丝结构观察：规模档/性别倾向/消费力信号
  commercial TEXT,           -- 商业化历史 JSON 数组 [{date,event,source}]
  incidents TEXT,            -- 舆情/争议 JSON 数组 [{date,event,source}]
  notes TEXT,                -- 其他观察
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT, city TEXT,
  kind TEXT,                 -- 演出/新团/解散/招募/商务/舆情/其他
  title TEXT, detail TEXT,
  source_uid TEXT, source_post TEXT,
  created_at TEXT
);
"""


def main():
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    today = date.today().isoformat()

    # 迁移 network.csv -> accounts + name_history
    n_acc = 0
    with open(ROOT / "network.csv") as f:
        for r in csv.DictReader(f):
            if not r["uid"].isdigit():
                continue
            con.execute(
                """INSERT INTO accounts(uid,name,type,city,priority,note,first_seen,last_seen)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(uid) DO UPDATE SET name=excluded.name,type=excluded.type,
                     city=excluded.city,priority=excluded.priority,note=excluded.note,last_seen=excluded.last_seen""",
                (r["uid"], r["name"], r["type"], r["city"], int(r["priority"] or 9), r.get("note", ""), today, today),
            )
            con.execute("INSERT OR IGNORE INTO name_history(uid,name,seen_date) VALUES(?,?,?)", (r["uid"], r["name"], today))
            n_acc += 1

    # 迁移 snapshots.csv -> snapshots
    n_snap = 0
    with open(ROOT / "snapshots.csv") as f:
        for r in csv.DictReader(f):
            if not r["uid"].isdigit():
                continue
            try:
                fol = int(r["followers_est"]) if r["followers_est"] else None
            except ValueError:
                fol = None
            try:
                sta = int(r["statuses_count"]) if r.get("statuses_count") else None
            except ValueError:
                sta = None
            con.execute(
                "INSERT OR REPLACE INTO snapshots(uid,date,followers_raw,followers,statuses) VALUES(?,?,?,?,?)",
                (r["uid"], r["date"], r["followers_raw"], fol, sta),
            )
            n_snap += 1

    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ["accounts", "name_history", "posts", "snapshots", "profiles", "events"]}
    con.close()
    print(json.dumps({"ok": True, "migrated_accounts": n_acc, "migrated_snapshots": n_snap, "tables": counts}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
