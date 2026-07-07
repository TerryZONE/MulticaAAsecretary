#!/usr/bin/env python3
"""把 daily_YYYY-MM-DD.json 入库 archive.db。每日采集后运行：python3 ingest.py [日期，默认今天]

职责：
1. 新帖入 posts（含 raw_json，若采集器提供）；已存在的帖子刷新互动数与 last_seen
2. 改名写入 accounts.name + name_history
3. 疑删检测：某账号 7 日内已存档、id 大于本次页面最旧 id、却不在本次页面的帖子 → 标记 deleted_suspect
4. 快照由采集器直接写 snapshots.csv，此处同步进 snapshots 表
"""
import csv
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data" / "archive.db"


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    daily_path = ROOT / "data" / f"daily_{day}.json"
    if not daily_path.exists():
        print(json.dumps({"ok": False, "error": f"{daily_path.name} 不存在"}))
        return 1
    d = json.loads(daily_path.read_text())
    con = sqlite3.connect(DB)

    n_new, n_upd, n_renamed, n_suspect = 0, 0, 0, 0
    for acc in d.get("accounts", []):
        uid = acc["uid"]
        # 改名
        if acc.get("renamed"):
            con.execute("UPDATE accounts SET name=?, last_seen=? WHERE uid=?", (acc["renamed"]["to"], day, uid))
            con.execute("INSERT OR IGNORE INTO name_history(uid,name,seen_date) VALUES(?,?,?)", (uid, acc["renamed"]["to"], day))
            n_renamed += 1
        else:
            con.execute("UPDATE accounts SET last_seen=? WHERE uid=?", (day, uid))

        page_ids = []
        for p in acc.get("new_posts", []):
            page_ids.append(int(p["id"]))
            exists = con.execute("SELECT 1 FROM posts WHERE post_id=?", (p["id"],)).fetchone()
            if exists:
                con.execute(
                    "UPDATE posts SET reposts=?,comments=?,likes=?,last_seen=? WHERE post_id=?",
                    (p.get("reposts"), p.get("comments"), p.get("likes"), day, p["id"]),
                )
                n_upd += 1
            else:
                con.execute(
                    """INSERT INTO posts(post_id,uid,created_at,text,is_long,reposts,comments,likes,pics,
                       rt_user,rt_text,raw_json,first_fetched,last_seen)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p["id"], uid, p.get("date"), p.get("text"), 0,
                     p.get("reposts"), p.get("comments"), p.get("likes"), p.get("pics"),
                     (p.get("rt") or {}).get("user"), (p.get("rt") or {}).get("text"),
                     json.dumps(p.get("raw"), ensure_ascii=False) if p.get("raw") else None,
                     day, day),
                )
                n_new += 1

        # 疑删检测：近 7 日入库、id 在本次页面窗口内、却未出现
        if page_ids:
            floor = min(page_ids)
            week_ago = (datetime.fromisoformat(day) - timedelta(days=7)).date().isoformat()
            rows = con.execute(
                """SELECT post_id FROM posts WHERE uid=? AND first_fetched>=? AND deleted_suspect IS NULL
                   AND CAST(post_id AS INTEGER)>=?""",
                (uid, week_ago, floor),
            ).fetchall()
            missing = [r[0] for r in rows if int(r[0]) not in page_ids]
            for pid in missing:
                con.execute("UPDATE posts SET deleted_suspect=? WHERE post_id=?", (day, pid))
                n_suspect += 1

    # snapshots.csv 当日行同步进表
    n_snap = 0
    with open(ROOT / "snapshots.csv") as f:
        for r in csv.DictReader(f):
            if r["date"] != day or not r["uid"].isdigit():
                continue
            try:
                fol = int(r["followers_est"]) if r["followers_est"] else None
            except ValueError:
                fol = None
            con.execute(
                "INSERT OR REPLACE INTO snapshots(uid,date,followers_raw,followers,statuses) VALUES(?,?,?,?,?)",
                (r["uid"], r["date"], r["followers_raw"], fol, r.get("statuses_count") or None),
            )
            n_snap += 1

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    con.close()
    print(json.dumps({"ok": True, "date": day, "new_posts": n_new, "updated": n_upd,
                      "renamed": n_renamed, "deleted_suspect": n_suspect, "snapshots": n_snap,
                      "posts_total": total}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
