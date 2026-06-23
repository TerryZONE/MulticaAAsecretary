#!/usr/bin/env python3
"""
偶像数据看板 — 极简瀑布流
直接读取 SQLite 数据库，单文件运行，无需额外依赖。
"""

import json
import sqlite3
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp-server", "data", "idol_monitor.db")
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp-server", "data", "images")
PORT = 8899


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query_posts(creator_id=None, page=1, per_page=20):
    db = get_db()
    offset = (page - 1) * per_page
    if creator_id:
        rows = db.execute(
            "SELECT * FROM posts WHERE creator_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (creator_id, per_page, offset)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM posts ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def query_creators():
    db = get_db()
    rows = db.execute("""
        SELECT t.creator_id, t.nickname, 
               COUNT(p.post_id) as post_count,
               MAX(p.created_at) as latest_post
        FROM tracked_creators t
        LEFT JOIN posts p ON t.creator_id = p.creator_id
        GROUP BY t.creator_id
    """).fetchall()
    db.close()
    return [dict(r) for r in rows]


def query_comments(post_id):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM comments WHERE post_id=? ORDER BY created_at ASC",
        (post_id,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def query_stats():
    db = get_db()
    stats = {}
    stats['total_posts'] = db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    stats['total_comments'] = db.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    stats['total_creators'] = db.execute("SELECT COUNT(*) FROM tracked_creators").fetchone()[0]
    # count images
    total_images = 0
    if os.path.exists(IMAGES_DIR):
        for d in os.listdir(IMAGES_DIR):
            dp = os.path.join(IMAGES_DIR, d)
            if os.path.isdir(dp):
                total_images += len(os.listdir(dp))
    stats['total_images'] = total_images
    db.close()
    return stats


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>偶像数据看板</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f7; color: #1d1d1f; }
.header { background: #fff; border-bottom: 1px solid #e5e5e5; padding: 16px 24px; position: sticky; top: 0; z-index: 100; }
.header h1 { font-size: 20px; font-weight: 600; }
.stats { display: flex; gap: 24px; margin-top: 8px; font-size: 13px; color: #86868b; }
.stats span { display: flex; align-items: center; gap: 4px; }
.filters { padding: 12px 24px; background: #fff; border-bottom: 1px solid #e5e5e5; display: flex; gap: 8px; flex-wrap: wrap; }
.filter-btn { padding: 6px 14px; border-radius: 16px; border: 1px solid #d2d2d7; background: #fff; font-size: 13px; cursor: pointer; transition: all 0.2s; }
.filter-btn:hover { border-color: #0071e3; color: #0071e3; }
.filter-btn.active { background: #0071e3; color: #fff; border-color: #0071e3; }
.feed { max-width: 640px; margin: 24px auto; padding: 0 16px; }
.card { background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); transition: box-shadow 0.2s; }
.card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.card-author { font-size: 14px; font-weight: 600; }
.card-time { font-size: 12px; color: #86868b; }
.card-text { font-size: 14px; line-height: 1.6; margin-bottom: 10px; word-break: break-word; }
.card-images { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; margin-bottom: 10px; border-radius: 8px; overflow: hidden; }
.card-images.single { grid-template-columns: 1fr; max-width: 360px; }
.card-images.double { grid-template-columns: 1fr 1fr; }
.card-images img { width: 100%; aspect-ratio: 1; object-fit: cover; cursor: pointer; }
.card-stats { display: flex; gap: 16px; font-size: 12px; color: #86868b; }
.card-comments { margin-top: 10px; padding-top: 10px; border-top: 1px solid #f0f0f0; }
.comment { font-size: 13px; margin-bottom: 6px; line-height: 1.5; }
.comment-author { font-weight: 600; color: #0071e3; }
.comment-more { font-size: 12px; color: #0071e3; cursor: pointer; margin-top: 4px; }
.loading { text-align: center; padding: 24px; color: #86868b; font-size: 14px; }
.empty { text-align: center; padding: 48px; color: #86868b; }
.modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 1000; justify-content: center; align-items: center; }
.modal.show { display: flex; }
.modal img { max-width: 90%; max-height: 90%; object-fit: contain; }
</style>
</head>
<body>
<div class="header">
    <h1>偶像数据看板</h1>
    <div class="stats" id="stats"></div>
</div>
<div class="filters" id="filters"></div>
<div class="feed" id="feed"></div>
<div class="loading" id="loading">加载中...</div>
<div class="modal" id="modal" onclick="this.classList.remove('show')">
    <img id="modal-img" src="">
</div>

<script>
let currentCreator = null;
let currentPage = 1;
let isLoading = false;
let hasMore = true;

async function fetchJSON(url) {
    const res = await fetch(url);
    return res.json();
}

async function loadStats() {
    const stats = await fetchJSON('/api/stats');
    document.getElementById('stats').innerHTML = 
        `<span>📝 ${stats.total_posts} 帖子</span>` +
        `<span>💬 ${stats.total_comments} 评论</span>` +
        `<span>🖼️ ${stats.total_images} 图片</span>` +
        `<span>👤 ${stats.total_creators} 博主</span>`;
}

async function loadFilters() {
    const creators = await fetchJSON('/api/creators');
    const container = document.getElementById('filters');
    let html = '<button class="filter-btn active" onclick="filterBy(null, this)">全部</button>';
    creators.forEach(c => {
        html += `<button class="filter-btn" onclick="filterBy('${c.creator_id}', this)">${c.nickname} (${c.post_count})</button>`;
    });
    container.innerHTML = html;
}

function filterBy(creatorId, btn) {
    currentCreator = creatorId;
    currentPage = 1;
    hasMore = true;
    document.getElementById('feed').innerHTML = '';
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadPosts();
}

function renderCard(post) {
    const images = post.images || [];
    const comments = post.comments || [];
    const gridClass = images.length === 1 ? 'single' : images.length === 2 ? 'double' : '';
    
    let imagesHtml = '';
    if (images.length > 0) {
        imagesHtml = `<div class="card-images ${gridClass}">` +
            images.slice(0, 9).map(url => `<img src="${url}" onclick="showImage(this.src)" loading="lazy">`).join('') +
            `</div>`;
    }
    
    let commentsHtml = '';
    if (comments.length > 0) {
        commentsHtml = '<div class="card-comments">' +
            comments.slice(0, 3).map(c => 
                `<div class="comment"><span class="comment-author">${c.author_nickname}</span>: ${c.text_content}</div>`
            ).join('') +
            (comments.length > 3 ? `<div class="comment-more" onclick="expandComments(this, '${post.post_id}')">查看全部 ${post.comments_count || comments.length} 条评论</div>` : '') +
            '</div>';
    }
    
    return `<div class="card">
        <div class="card-header">
            <span class="card-author">${post.nickname || post.creator_id}</span>
            <span class="card-time">${post.created_at}</span>
        </div>
        <div class="card-text">${post.text_content || ''}</div>
        ${imagesHtml}
        <div class="card-stats">
            <span>❤️ ${post.attitudes_count || 0}</span>
            <span>💬 ${post.comments_count || 0}</span>
            <span>🔄 ${post.reposts_count || 0}</span>
        </div>
        ${commentsHtml}
    </div>`;
}

async function loadPosts() {
    if (isLoading || !hasMore) return;
    isLoading = true;
    document.getElementById('loading').style.display = 'block';
    
    let url = `/api/posts?page=${currentPage}&per_page=20`;
    if (currentCreator) url += `&creator_id=${currentCreator}`;
    
    const posts = await fetchJSON(url);
    
    if (posts.length === 0) {
        hasMore = false;
        document.getElementById('loading').textContent = '没有更多了';
    } else {
        const feed = document.getElementById('feed');
        posts.forEach(post => {
            feed.insertAdjacentHTML('beforeend', renderCard(post));
        });
        currentPage++;
    }
    
    isLoading = false;
    if (hasMore) document.getElementById('loading').style.display = 'none';
}

function showImage(src) {
    document.getElementById('modal-img').src = src;
    document.getElementById('modal').classList.add('show');
}

async function expandComments(el, postId) {
    el.textContent = '加载中...';
    const comments = await fetchJSON(`/api/comments?post_id=${postId}`);
    const container = el.parentElement;
    if (comments.length === 0) {
        container.innerHTML = '<div class="comment" style="color:#86868b">评论未抓取，需要归档补充</div>';
    } else {
        container.innerHTML = comments.map(c => 
            `<div class="comment"><span class="comment-author">${c.author_nickname || '匿名'}</span>: ${c.text_content}</div>`
        ).join('');
    }
}

// Infinite scroll
window.addEventListener('scroll', () => {
    if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 500) {
        loadPosts();
    }
});

// Init
loadStats();
loadFilters();
loadPosts();
</script>
</body>
</html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/' or path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))

        elif path == '/api/stats':
            self.json_response(query_stats())

        elif path == '/api/creators':
            self.json_response(query_creators())

        elif path == '/api/posts':
            creator_id = params.get('creator_id', [None])[0]
            page = int(params.get('page', [1])[0])
            per_page = int(params.get('per_page', [20])[0])
            posts = query_posts(creator_id, page, per_page)
            
            # Enrich with nickname, images, and top comments
            db = get_db()
            for post in posts:
                # Get nickname
                row = db.execute("SELECT nickname FROM tracked_creators WHERE creator_id=?", (post['creator_id'],)).fetchone()
                post['nickname'] = row['nickname'] if row else post['creator_id']
                
                # Get local image paths
                img_dir = os.path.join(IMAGES_DIR, post['post_id'])
                if os.path.isdir(img_dir):
                    post['images'] = [f"/images/{post['post_id']}/{f}" for f in sorted(os.listdir(img_dir)) if not f.startswith('.')]
                else:
                    post['images'] = []
                
                # Get top 5 comments
                comments = db.execute(
                    "SELECT author_nickname, text_content FROM comments WHERE post_id=? ORDER BY like_count DESC LIMIT 5",
                    (post['post_id'],)
                ).fetchall()
                post['comments'] = [dict(c) for c in comments]
            db.close()
            self.json_response(posts)

        elif path == '/api/comments':
            post_id = params.get('post_id', [None])[0]
            if post_id:
                comments = query_comments(post_id)
                self.json_response(comments)
            else:
                self.json_response([])

        elif path.startswith('/images/'):
            # Serve local images
            rel_path = path[len('/images/'):]
            file_path = os.path.join(IMAGES_DIR, rel_path)
            if os.path.isfile(file_path):
                self.send_response(200)
                ext = file_path.rsplit('.', 1)[-1].lower()
                content_types = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'}
                self.send_header('Content-Type', content_types.get(ext, 'application/octet-stream'))
                self.end_headers()
                with open(file_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)

        else:
            self.send_error(404)

    def json_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode('utf-8'))

    def log_message(self, format, *args):
        pass  # Suppress request logs


if __name__ == '__main__':
    print(f"偶像数据看板启动: http://localhost:{PORT}")
    print(f"数据库: {DB_PATH}")
    print("按 Ctrl+C 停止")
    server = HTTPServer(('0.0.0.0', PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
