"""
crawlers/threads.py

透過 Threads 非官方 API 抓取關鍵字相關貼文。
不需要登入，直接搜尋公開內容。

回傳統一格式：
    {
        "title":     str,   # Threads 無標題，用內文前 30 字代替
        "content":   str,
        "url":       str,
        "source":    "Threads",
        "board":     str,   # 固定為 "threads"
        "author":    str,   # 用戶名稱
        "timestamp": str,
        "like_count": int,
    }

使用範例：
    crawler = ThreadsCrawler(keywords=["Ford Focus", "福特"])
    articles = crawler.fetch_all(limit=20)
"""

from __future__ import annotations

import time
import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
}

THREADS_SEARCH = "https://www.threads.net/search/?q={query}&serp_type=default"


class ThreadsCrawler:
    """
    Args:
        keywords:      搜尋關鍵字清單
        delay_seconds: 每次請求間隔
        timeout:       請求 timeout 秒數
    """

    def __init__(
        self,
        keywords:      list[str] = None,
        delay_seconds: float = 2.0,
        timeout:       int = 15,
    ):
        self.keywords      = keywords or []
        self.delay_seconds = delay_seconds
        self.timeout       = timeout

        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    # ── 公開方法 ──────────────────────────────

    def fetch_all(self, limit: int = 20) -> list[dict]:
        """對所有關鍵字搜尋，去重後合併回傳。"""
        seen_urls = set()
        results = []

        for kw in self.keywords:
            try:
                articles = self.fetch_keyword(kw, limit=limit)
                for a in articles:
                    if a["url"] not in seen_urls:
                        seen_urls.add(a["url"])
                        results.append(a)
                print(f"[Threads] '{kw}': 取得 {len(articles)} 篇")
                time.sleep(self.delay_seconds)
            except Exception as e:
                print(f"[Threads] '{kw}' 搜尋失敗：{e}")

        return results

    def fetch_keyword(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜尋單一關鍵字。"""
        url = THREADS_SEARCH.format(query=quote(keyword))

        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as e:
            print(f"[Threads] 請求失敗：{e}")
            return []

        articles = self._parse_response(resp.text, keyword)
        return articles[:limit]

    # ── 內部方法 ──────────────────────────────

    def _parse_response(self, html: str, keyword: str) -> list[dict]:
        """
        從 Threads 頁面 HTML 解析貼文。
        Threads 在 <script type="application/json"> 中嵌入資料。
        """
        articles = []

        # 方法一：從 JSON-LD 或內嵌 JSON 解析
        soup = BeautifulSoup(html, "html.parser")

        for script in soup.find_all("script", type="application/json"):
            try:
                data = json.loads(script.string or "")
                posts = self._extract_posts_from_json(data, keyword)
                articles.extend(posts)
            except (json.JSONDecodeError, AttributeError):
                continue

        # 方法二：fallback — 從 HTML 結構直接解析
        if not articles:
            articles = self._parse_html_fallback(soup, keyword)

        return articles

    def _extract_posts_from_json(self, data, keyword: str) -> list[dict]:
        """遞迴從 JSON 結構中找出貼文資料。"""
        posts = []

        if isinstance(data, dict):
            # 常見的 Threads JSON 結構路徑
            for key in ["edges", "nodes", "threads", "items", "data"]:
                if key in data:
                    posts.extend(self._extract_posts_from_json(data[key], keyword))

            # 判斷是否為貼文節點
            if "text_post_app_text" in data or ("id" in data and "text" in data):
                post = self._parse_post_node(data, keyword)
                if post:
                    posts.append(post)

        elif isinstance(data, list):
            for item in data:
                posts.extend(self._extract_posts_from_json(item, keyword))

        return posts

    def _parse_post_node(self, node: dict, keyword: str) -> Optional[dict]:
        """解析單一貼文節點。"""
        try:
            # 取得內文
            content = (
                node.get("text_post_app_text", {}).get("text", "")
                or node.get("text", "")
                or node.get("caption", {}).get("text", "")
                or ""
            )
            content = content.strip()
            if not content:
                return None

            # 用戶名稱
            user = node.get("user", {}) or {}
            author = (
                user.get("username", "")
                or user.get("name", "")
                or ""
            )

            # 時間
            taken_at = node.get("taken_at") or node.get("timestamp", 0)
            timestamp = ""
            if taken_at:
                try:
                    dt = datetime.fromtimestamp(int(taken_at), tz=timezone.utc)
                    timestamp = dt.isoformat()
                except Exception:
                    timestamp = str(taken_at)

            # 連結
            post_id = node.get("id", "")
            url = f"https://www.threads.net/@{author}/post/{post_id}" if author and post_id else "https://www.threads.net"

            # 按讚數
            like_count = node.get("like_count", 0) or 0

            # 用內文前 30 字當標題
            title = content[:30].replace("\n", " ")
            if len(content) > 30:
                title += "..."

            return {
                "title":      title,
                "content":    content,
                "url":        url,
                "source":     "Threads",
                "board":      "threads",
                "author":     author,
                "timestamp":  timestamp,
                "like_count": like_count,
                "keyword":    keyword,
            }
        except Exception:
            return None

    def _parse_html_fallback(self, soup: BeautifulSoup, keyword: str) -> list[dict]:
        """
        HTML fallback 解析。
        當 JSON 解析失敗時嘗試直接從 HTML 結構取得內容。
        """
        posts = []

        # Threads 貼文通常在 article 或 特定 div 結構中
        for article in soup.find_all("article"):
            content_el = article.find(["p", "span"], class_=re.compile(r"text|content|post", re.I))
            if not content_el:
                continue

            content = content_el.get_text(strip=True)
            if not content or len(content) < 5:
                continue

            link_el = article.find("a", href=re.compile(r"/post/"))
            url = "https://www.threads.net" + link_el["href"] if link_el else "https://www.threads.net"

            title = content[:30].replace("\n", " ")
            if len(content) > 30:
                title += "..."

            posts.append({
                "title":      title,
                "content":    content,
                "url":        url,
                "source":     "Threads",
                "board":      "threads",
                "author":     "",
                "timestamp":  "",
                "like_count": 0,
                "keyword":    keyword,
            })

        return posts

    def __repr__(self) -> str:
        return f"ThreadsCrawler(keywords={self.keywords})"


if __name__ == "__main__":
    crawler = ThreadsCrawler(
        keywords=["Ford Focus", "福特"],
        delay_seconds=2.0,
    )
    articles = crawler.fetch_all(limit=10)
    print(f"\n共取得 {len(articles)} 篇\n" + "=" * 50)
    for a in articles[:3]:
        print(f"作者：@{a['author']}")
        print(f"內文：{a['content'][:80]}...")
        print(f"連結：{a['url']}")
        print("-" * 50)
