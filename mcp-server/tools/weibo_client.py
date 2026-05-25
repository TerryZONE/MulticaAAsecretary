"""
轻量级微博 API 客户端

支持两套 API：
- 移动端 m.weibo.cn（默认）
- 桌面端 weibo.com/ajax/（fallback，部分账号移动端被限制时自动切换）

使用 MediaCrawler 登录后保存的 cookie 进行认证。
"""

import asyncio
import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlencode

import httpx


class WeiboAPIClient:
    """Weibo API client with mobile + desktop fallback."""

    def __init__(self, cookies: str = "", proxy: Optional[str] = None):
        self._host = "https://m.weibo.cn"
        self._desktop_host = "https://weibo.com"
        self._cookies = cookies
        self._proxy = proxy
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://m.weibo.cn/",
        }
        self._desktop_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://weibo.com/",
        }
        if cookies:
            self._headers["Cookie"] = cookies
            self._desktop_headers["Cookie"] = cookies

    def update_cookies(self, cookies: str):
        """Update the cookie string."""
        self._cookies = cookies
        self._headers["Cookie"] = cookies
        self._desktop_headers["Cookie"] = cookies

    async def _request(self, method: str, url: str, **kwargs) -> Dict:
        """Make an HTTP request and return parsed JSON data."""
        headers = kwargs.pop("headers", self._headers)
        async with httpx.AsyncClient(proxy=self._proxy, verify=True) as http_client:
            response = await http_client.request(
                method, url, headers=headers, timeout=30, **kwargs
            )

        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        ok_code = data.get("ok")
        if ok_code == 1:
            return data.get("data", {})
        else:
            raise Exception(f"API error: {data.get('msg', 'unknown error')}")

    async def _desktop_request(self, method: str, url: str, **kwargs) -> Dict:
        """Make request to desktop API (weibo.com/ajax/)."""
        async with httpx.AsyncClient(proxy=self._proxy, verify=True) as http_client:
            response = await http_client.request(
                method, url, headers=self._desktop_headers, timeout=30, **kwargs
            )

        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        ok_code = data.get("ok")
        if ok_code == 1:
            return data.get("data", data)
        else:
            raise Exception(f"Desktop API error: {data.get('msg', 'unknown error')}")

    async def _get(self, uri: str, params: Optional[Dict] = None) -> Dict:
        """GET request to m.weibo.cn API."""
        url = f"{self._host}{uri}"
        if params:
            url = f"{url}?{urlencode(params)}"
        return await self._request("GET", url)

    async def search(self, keyword: str, page: int = 1, search_type: str = "default") -> Dict:
        """
        Search Weibo by keyword.
        search_type: default=1, real_time=61, popular=60, video=64
        """
        type_map = {"default": 1, "real_time": 61, "popular": 60, "video": 64}
        type_value = type_map.get(search_type, 1)

        uri = "/api/container/getIndex"
        containerid = f"100103type={type_value}&q={keyword}"
        params = {
            "containerid": containerid,
            "page_type": "searchall",
            "page": page,
        }
        return await self._get(uri, params)

    async def get_creator_info(self, creator_id: str) -> Dict:
        """Get creator profile information. Falls back to desktop API if mobile fails."""
        try:
            uri = "/api/container/getIndex"
            containerid = f"100505{creator_id}"
            params = {
                "jumpfrom": "weibocom",
                "type": "uid",
                "value": creator_id,
                "containerid": containerid,
            }
            return await self._get(uri, params)
        except Exception:
            # Fallback to desktop API
            return await self._get_creator_info_desktop(creator_id)

    async def _get_creator_info_desktop(self, creator_id: str) -> Dict:
        """Get creator info via desktop API (weibo.com/ajax/)."""
        url = f"{self._desktop_host}/ajax/profile/info?uid={creator_id}"
        data = await self._desktop_request("GET", url)
        user = data.get("user", data)
        # Normalize to match mobile API format
        return {
            "userInfo": {
                "id": user.get("id"),
                "screen_name": user.get("screen_name"),
                "followers_count": user.get("followers_count"),
                "follow_count": user.get("friends_count"),
                "statuses_count": user.get("statuses_count"),
                "description": user.get("description", ""),
                "profile_image_url": user.get("profile_image_url", ""),
                "verified": user.get("verified", False),
                "verified_reason": user.get("verified_reason", ""),
            }
        }

    async def get_creator_container_id(self, creator_id: str) -> str:
        """Get the container ID for fetching creator's posts (107603 prefix)."""
        # The posts container ID is always 107603 + user_id for Weibo mobile API
        return f"107603{creator_id}"

    async def get_creator_posts(
        self, creator_id: str, container_id: str, since_id: str = "0"
    ) -> Dict:
        """Get posts from a creator."""
        uri = "/api/container/getIndex"
        params = {
            "jumpfrom": "weibocom",
            "type": "uid",
            "value": creator_id,
            "containerid": container_id,
            "since_id": since_id,
        }
        return await self._get(uri, params)

    async def get_post_comments(
        self, post_id: str, max_id: int = 0, max_id_type: int = 0
    ) -> Dict:
        """Get comments for a post. Falls back to desktop API if mobile fails."""
        try:
            return await self._get_post_comments_mobile(post_id, max_id, max_id_type)
        except Exception as e:
            if "还没有人评论" in str(e):
                return {"data": [], "max_id": 0}
            # Fallback to desktop API
            try:
                return await self._get_post_comments_desktop(post_id, max_id)
            except Exception:
                raise e

    async def _get_post_comments_mobile(
        self, post_id: str, max_id: int = 0, max_id_type: int = 0
    ) -> Dict:
        """Get comments via mobile API."""
        uri = "/comments/hotflow"
        params = {
            "id": post_id,
            "mid": post_id,
            "max_id_type": max_id_type,
        }
        if max_id > 0:
            params["max_id"] = max_id

        headers = {**self._headers, "Referer": f"https://m.weibo.cn/detail/{post_id}"}

        url = f"{self._host}{uri}?{urlencode(params)}"
        async with httpx.AsyncClient(proxy=self._proxy, verify=True) as http_client:
            response = await http_client.get(url, headers=headers, timeout=30)

        data = response.json()
        if data.get("ok") == 1:
            return data.get("data", {})
        else:
            msg = data.get("msg", "")
            if "还没有人评论" in msg:
                return {"data": [], "max_id": 0}
            raise Exception(f"API error: {msg}")

    async def _get_post_comments_desktop(
        self, post_id: str, max_id: int = 0
    ) -> Dict:
        """Get comments via desktop API (weibo.com/ajax/statuses/buildComments)."""
        params = {
            "id": post_id,
            "is_show_bulletin": 2,
            "is_mix": 0,
            "count": 20,
            "flow": 0,
        }
        if max_id > 0:
            params["max_id"] = max_id

        url = f"{self._desktop_host}/ajax/statuses/buildComments?{urlencode(params)}"
        async with httpx.AsyncClient(proxy=self._proxy, verify=True) as http_client:
            response = await http_client.request(
                "GET", url, headers=self._desktop_headers, timeout=30
            )

        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")

        data = response.json()
        if data.get("ok") != 1:
            raise Exception(f"Desktop API error: {data.get('msg', '')}")

        raw_data = data.get("data", {})
        # Desktop API returns {"data": [...], "max_id": N} or just a list
        if isinstance(raw_data, list):
            comments = raw_data
            max_id_new = 0
        else:
            comments = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else []
            max_id_new = raw_data.get("max_id", 0) if isinstance(raw_data, dict) else 0

        return {"data": comments, "max_id": max_id_new, "max_id_type": 0}

    async def check_login(self) -> bool:
        """Check if the current cookies are valid."""
        try:
            url = f"{self._host}/api/config"
            async with httpx.AsyncClient(proxy=self._proxy, verify=True) as http_client:
                response = await http_client.get(
                    url, headers=self._headers, timeout=15
                )
            data = response.json()
            return data.get("data", {}).get("login", False)
        except Exception:
            return False

    async def get_post_detail(self, post_id: str) -> Dict:
        """Get post detail by post ID. Returns full text for long posts."""
        url = f"{self._host}/detail/{post_id}"
        async with httpx.AsyncClient(proxy=self._proxy, verify=True) as http_client:
            response = await http_client.get(url, headers=self._headers, timeout=30)

        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")

        match = re.search(
            r'var \$render_data = (\[.*?\])\[0\]', response.text, re.DOTALL
        )
        if match:
            render_data = json.loads(match.group(1))
            return render_data[0].get("status", {})
        return {}

    async def get_all_creator_posts(
        self, creator_id: str, max_count: int = 200, crawl_interval: float = 2.0
    ) -> List[Dict]:
        """
        Get ALL posts by a creator (paginated until exhausted or max_count reached).
        Falls back to desktop API if mobile fails.
        """
        try:
            result = await self._get_all_creator_posts_mobile(
                creator_id, max_count, crawl_interval
            )
            if result:
                return result
        except Exception:
            pass
        # Fallback to desktop API
        return await self._get_all_creator_posts_desktop(
            creator_id, max_count, crawl_interval
        )

    async def _get_all_creator_posts_mobile(
        self, creator_id: str, max_count: int = 200, crawl_interval: float = 2.0
    ) -> List[Dict]:
        """Get all posts via mobile API (m.weibo.cn)."""
        container_id = f"107603{creator_id}"
        result = []
        since_id = ""
        crawler_total_count = 0

        while len(result) < max_count:
            data = await self.get_creator_posts(creator_id, container_id, since_id)
            if not data:
                break

            cards = data.get("cards", [])
            if not cards:
                break

            posts = [c for c in cards if c.get("card_type") == 9]
            result.extend(posts)

            since_id = data.get("cardlistInfo", {}).get("since_id", "0")
            if not since_id or since_id == "0":
                break

            crawler_total_count += 10
            total = data.get("cardlistInfo", {}).get("total", 0)
            if total <= crawler_total_count:
                break

            await asyncio.sleep(crawl_interval)

        return result[:max_count]

    async def _get_all_creator_posts_desktop(
        self, creator_id: str, max_count: int = 200, crawl_interval: float = 2.0
    ) -> List[Dict]:
        """Get all posts via desktop API (weibo.com/ajax/statuses/mymblog)."""
        result = []
        page = 1

        while len(result) < max_count:
            url = (
                f"{self._desktop_host}/ajax/statuses/mymblog"
                f"?uid={creator_id}&page={page}&feature=0"
            )
            try:
                data = await self._desktop_request("GET", url)
            except Exception:
                break

            posts = data.get("list", [])
            if not posts:
                break

            # Normalize desktop posts to match mobile card format
            for post in posts:
                card = {
                    "card_type": 9,
                    "mblog": post,
                    "_source": "desktop",
                }
                result.append(card)

            # Check if there are more pages
            if not data.get("since_id") and len(posts) < 20:
                break

            page += 1
            await asyncio.sleep(crawl_interval)

        return result[:max_count]

    async def download_image(self, image_url: str) -> Optional[bytes]:
        """
        Download a Weibo image via proxy to bypass hotlink protection.
        Uses i1.wp.com as image proxy.
        """
        if not image_url:
            return None

        # Remove protocol prefix
        url_without_protocol = image_url
        if image_url.startswith("https://"):
            url_without_protocol = image_url[8:]
        elif image_url.startswith("http://"):
            url_without_protocol = image_url[7:]

        # Replace thumbnail size with 'large' for high-res
        parts = url_without_protocol.split("/")
        reconstructed = ""
        for i, part in enumerate(parts):
            if i == 1:
                reconstructed += "large/"
            elif i == len(parts) - 1:
                reconstructed += part
            else:
                reconstructed += part + "/"

        # Use WordPress image proxy to bypass hotlink protection
        proxy_url = f"https://i1.wp.com/{reconstructed}"

        async with httpx.AsyncClient(proxy=self._proxy, verify=True) as http_client:
            try:
                response = await http_client.get(proxy_url, timeout=60)
                response.raise_for_status()
                return response.content
            except Exception:
                return None
