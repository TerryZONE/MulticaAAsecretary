"""
从 MediaCrawler 的浏览器数据中提取微博 cookie，
或者手动设置 cookie 到 config.json。

用法:
    # 手动设置 cookie（从浏览器开发者工具复制）
    python3 setup_cookies.py --cookie "SUB=xxx; SUBP=yyy; ..."

    # 通过 MediaCrawler 登录后自动提取（需要先运行一次 MediaCrawler 登录）
    python3 setup_cookies.py --from-browser
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "mcp-server" / "config.json"
BROWSER_DATA_DIR = Path(__file__).parent / "MediaCrawler" / "browser_data" / "wb_user_data_dir"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"cookies": "", "tracked_creators": []}


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def set_cookie_manual(cookie_str: str):
    """Set cookie string directly."""
    cfg = load_config()
    cfg["cookies"] = cookie_str.strip()
    save_config(cfg)
    print(f"✅ Cookie 已保存到 {CONFIG_PATH}")
    print(f"   Cookie 长度: {len(cookie_str)} 字符")


def extract_from_browser():
    """Try to extract cookies from Chromium's cookie database."""
    cookie_db = BROWSER_DATA_DIR / "Default" / "Cookies"
    if not cookie_db.exists():
        # Try Network directory
        cookie_db = BROWSER_DATA_DIR / "Default" / "Network" / "Cookies"

    if not cookie_db.exists():
        print("❌ 找不到浏览器 cookie 数据库")
        print(f"   尝试路径: {BROWSER_DATA_DIR / 'Default'}")
        print()
        print("请先运行 MediaCrawler 登录微博:")
        print("  cd MediaCrawler && python main.py --platform wb --lt qrcode --type search --keywords test")
        print()
        print("或者手动设置 cookie:")
        print('  python3 setup_cookies.py --cookie "SUB=xxx; SUBP=yyy"')
        sys.exit(1)

    try:
        conn = sqlite3.connect(str(cookie_db))
        cursor = conn.execute(
            """
            SELECT name, value FROM cookies
            WHERE host_key LIKE '%weibo%'
            ORDER BY name
            """
        )
        cookies = cursor.fetchall()
        conn.close()

        if not cookies:
            print("❌ 浏览器数据库中没有找到微博相关的 cookie")
            print("   请先通过 MediaCrawler 登录微博")
            sys.exit(1)

        cookie_str = "; ".join(f"{name}={value}" for name, value in cookies)
        set_cookie_manual(cookie_str)
        print(f"   提取到 {len(cookies)} 个 cookie 项")

    except Exception as e:
        print(f"❌ 提取 cookie 失败: {e}")
        print()
        print("Chromium cookie 数据库可能被加密。")
        print("建议手动从浏览器复制 cookie:")
        print("  1. 打开 m.weibo.cn 并登录")
        print("  2. F12 → Network → 任意请求 → Headers → Cookie")
        print('  3. python3 setup_cookies.py --cookie "复制的cookie"')
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="设置微博 Cookie")
    parser.add_argument("--cookie", type=str, help="直接设置 cookie 字符串")
    parser.add_argument(
        "--from-browser", action="store_true", help="从 MediaCrawler 浏览器数据提取"
    )
    args = parser.parse_args()

    if args.cookie:
        set_cookie_manual(args.cookie)
    elif args.from_browser:
        extract_from_browser()
    else:
        parser.print_help()
        print()
        print("示例:")
        print('  python3 setup_cookies.py --cookie "SUB=_2A25xxx; SUBP=0033xxx"')
        print("  python3 setup_cookies.py --from-browser")


if __name__ == "__main__":
    main()
