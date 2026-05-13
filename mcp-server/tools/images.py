"""
微博图片下载工具
"""

import asyncio
import os
from pathlib import Path
from typing import Dict, List

from .weibo_client import WeiboAPIClient


IMAGES_DIR = Path(__file__).parent.parent / "data" / "images"


async def download_post_images(
    client: WeiboAPIClient,
    post_id: str,
    image_urls: List[str],
) -> Dict:
    """
    Download images from a Weibo post.
    Images are saved to data/images/{post_id}/ directory.
    Returns download results.
    """
    if not image_urls:
        return {
            "post_id": post_id,
            "total": 0,
            "downloaded": 0,
            "failed": 0,
            "files": [],
        }

    # Create directory for this post's images
    post_dir = IMAGES_DIR / post_id
    post_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    failed = []

    for i, url in enumerate(image_urls):
        try:
            content = await client.download_image(url)
            if content:
                # Determine file extension
                ext = url.split(".")[-1].split("?")[0]
                if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                    ext = "jpg"
                filename = f"{i+1:03d}.{ext}"
                filepath = post_dir / filename

                with open(filepath, "wb") as f:
                    f.write(content)

                downloaded.append({
                    "filename": filename,
                    "path": str(filepath),
                    "size_bytes": len(content),
                    "original_url": url,
                })
            else:
                failed.append({"url": url, "reason": "Empty response"})

            await asyncio.sleep(0.5)  # Rate limiting

        except Exception as e:
            failed.append({"url": url, "reason": str(e)})

    return {
        "post_id": post_id,
        "save_directory": str(post_dir),
        "total": len(image_urls),
        "downloaded": len(downloaded),
        "failed": len(failed),
        "files": downloaded,
        "errors": failed if failed else None,
    }
