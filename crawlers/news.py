"""
crawlers/news.py

透過 Google News RSS 抓取台灣新聞，再進原始頁面取得內文。
優點：不需要針對每個新聞網站分別維護爬蟲，RSS 格式統一穩定。

支援的新聞來源（透過 Google News）：
    - 自由時報、聯合新聞網、中時新聞網、ETtoday、三立新聞
    - 以及其他 Google News 索引的台灣媒體

回傳統一格式：
    {
        "title":     str,
        "content":   str,
        "url":       str,
        "source":    "News",
        "board":     str,   # 新聞來源媒體名稱
        "author":    str,
        "timestamp": str,
        "keyword":   str,   # 搜尋關鍵字
    }

使用範例：
    crawler = NewsCrawler(keywords=["Ford Focus", "福特"])
    articles = crawler.fetch_all(limit=20)
"""

from __future__ import annotations

import time
import re
from typing import Optional
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}

# Google News RSS endpoint
GNEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

import json as _json

# 由 app.py 在啟動時設定，指向客戶資料夾的 blacklist.json
BLACKLIST_PATH = "blacklist.json"

def _load_blacklist() -> set:
    """從 BLACKLIST_PATH 動態讀取黑名單"""
    try:
        with open(BLACKLIST_PATH, "r", encoding="utf-8") as f:
            data = _json.load(f)
            return set(data.get("domains", []))
    except Exception:
        return set()


class NewsCrawler:
    """
    Args:
        keywords:      搜尋關鍵字清單，每個關鍵字獨立搜尋
        delay_seconds: 每次請求間隔
        timeout:       請求 timeout 秒數
        fetch_content: 是否進原始頁面抓完整內文（True 較慢但內容完整）
    """

    def __init__(
        self,
        keywords:      list[str] = None,
        delay_seconds: float = 1.5,
        timeout:       int = 10,
        fetch_content: bool = True,
    ):
        self.keywords      = keywords or []
        self.delay_seconds = delay_seconds
        self.timeout       = timeout
        self.fetch_content = fetch_content

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
                print(f"[News] '{kw}': 取得 {len(articles)} 篇")
            except Exception as e:
                print(f"[News] '{kw}' 搜尋失敗：{e}")

        return results

    def fetch_keyword(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜尋單一關鍵字的新聞。"""
        rss_url = GNEWS_RSS.format(query=quote(keyword))

        try:
            resp = self.session.get(rss_url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as e:
            print(f"[News] RSS 請求失敗：{e}")
            return []

        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:limit]

        articles = []
        for item in items:
            article = self._parse_rss_item(item, keyword)
            if not article:
                continue

            # 選擇性進原始頁面抓完整內文
            if self.fetch_content:
                fetched_content, fetched_ts = self._fetch_article_content(article["url"])
                if fetched_content:
                    article["content"] = fetched_content
                # 用文章原始發佈時間取代 RSS pubDate（更準確）
                if fetched_ts:
                    article["timestamp"] = fetched_ts
                time.sleep(self.delay_seconds)

            articles.append(article)

        return articles

    # ── 內部方法 ──────────────────────────────

    def _parse_rss_item(self, item, keyword: str) -> Optional[dict]:
        """解析 RSS item。"""
        try:
            title = item.find("title")
            title = title.get_text(strip=True) if title else ""

            # 移除 - 媒體名稱 後綴
            media_name = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                media_name = parts[1].strip()

            link = item.find("link")
            url = link.get_text(strip=True) if link else ""
            # Google News 有時回傳 redirect URL，直接用
            if not url:
                return None

            pub_date = item.find("pubDate")
            timestamp = pub_date.get_text(strip=True) if pub_date else ""

            description = item.find("description")
            content = description.get_text(strip=True) if description else ""
            # 清理 HTML 標籤殘留
            content = re.sub(r"<[^>]+>", "", content).strip()

            # 黑名單過濾（每次動態讀取，即時生效）
            domain = self._extract_domain(url)
            blacklist = _load_blacklist()
            if blacklist and any(blocked in domain for blocked in blacklist):
                return None

            return {
                "title":     title,
                "content":   content,
                "url":       url,
                "source":    "News",
                "board":     media_name or domain,
                "author":    "",
                "timestamp": timestamp,
                "keyword":   keyword,
            }
        except Exception:
            return None

    def _fetch_article_content(self, url: str) -> tuple:
        """
        進原始文章頁面抓完整內文和原始發佈時間。
        Returns: (content: str, pub_date: str)
        """
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            resp.raise_for_status()
        except Exception:
            return "", ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # 移除不必要的標籤
        for tag in soup.select("script, style, nav, header, footer, aside, .ad, .advertisement"):
            tag.decompose()

        # 常見新聞內文容器 CSS 選擇器（按優先序）
        selectors = [
            "article",
            "[class*='article-body']",
            "[class*='article-content']",
            "[class*='news-content']",
            "[class*='story-body']",
            "[class*='post-content']",
            "div.content",
            "div.main-content",
        ]

        for selector in selectors:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    # 也取原始發佈時間
                    pub_date = ""
                    for ts_sel in [
                        'meta[property="article:published_time"]',
                        'meta[name="pubdate"]',
                        'meta[itemprop="datePublished"]',
                        'time[itemprop="datePublished"]',
                        'time[datetime]',
                    ]:
                        ts_el = soup.select_one(ts_sel)
                        if ts_el:
                            pub_date = ts_el.get("content") or ts_el.get("datetime") or ts_el.get_text(strip=True)
                            if pub_date:
                                break
                    return text[:2000], pub_date

        # 嘗試從 meta 取原始發佈時間
        pub_date = ""
        for sel in [
            'meta[property="article:published_time"]',
            'meta[name="pubdate"]',
            'meta[name="publishdate"]',
            'meta[itemprop="datePublished"]',
            'time[itemprop="datePublished"]',
            'time[datetime]',
        ]:
            el = soup.select_one(sel)
            if el:
                pub_date = el.get("content") or el.get("datetime") or el.get_text(strip=True)
                if pub_date:
                    break

        # Fallback：抓最長的 <p> 段落群
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 30]
        return "\n".join(paragraphs[:15])[:2000], pub_date

    @staticmethod
    def _extract_domain(url: str) -> str:
        """從 URL 擷取網域作為來源名稱。"""
        try:
            domain = urlparse(url).netloc
            return domain.replace("www.", "")
        except Exception:
            return "新聞"

    def __repr__(self) -> str:
        return f"NewsCrawler(keywords={self.keywords})"


if __name__ == "__main__":
    crawler = NewsCrawler(
        keywords=["Ford Focus", "福特 汽車"],
        delay_seconds=1.5,
        fetch_content=True,
    )
    articles = crawler.fetch_all(limit=5)
    print(f"\n共取得 {len(articles)} 篇\n" + "=" * 50)
    for a in articles:
        print(f"標題：{a['title']}")
        print(f"來源：{a['board']}　關鍵字：{a['keyword']}")
        print(f"內文：{a['content'][:80]}...")
        print("-" * 50)
