"""
crawlers/mobile01.py
Mobile01 爬蟲，支援時間區間過濾
"""

import re
import time

import requests
from bs4 import BeautifulSoup

from core.utils import in_range, in_range_loose, parse_dt


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language":        "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer":                "https://www.mobile01.com/",
        "sec-ch-ua":              '"Chromium";v="124", "Google Chrome";v="124"',
        "sec-ch-ua-mobile":       "?0",
        "sec-ch-ua-platform":     '"macOS"',
        "Sec-Fetch-Dest":         "document",
        "Sec-Fetch-Mode":         "navigate",
        "Sec-Fetch-Site":         "same-origin",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control":          "max-age=0",
    })
    return s


def fetch_mobile01(board_name: str, forum_id: int,
                   t_start, t_end,
                   has_time_range: bool = False,
                   pages: int = 2) -> list:
    """
    爬取 Mobile01 指定討論區。

    Returns:
        list[dict]（article type）
    """
    session = _make_session()
    checker = in_range if has_time_range else in_range_loose

    # Warm-up
    try:
        session.get("https://www.mobile01.com/", timeout=10)
        time.sleep(1.5)
    except:
        pass

    articles = []

    for page in range(1, pages + 1):
        try:
            url  = f"https://www.mobile01.com/topiclist.php?f={forum_id}&p={page}"
            resp = session.get(url, timeout=15)

            if resp.status_code == 403:
                print(f"[Mobile01] {board_name} 403，嘗試手機版...")
                url  = f"https://m.mobile01.com/topiclist.php?f={forum_id}&p={page}"
                resp = session.get(url, timeout=15)

            if resp.status_code != 200:
                print(f"[Mobile01] {board_name} 回傳 {resp.status_code}")
                break

            soup  = BeautifulSoup(resp.text, "html.parser")
            links = soup.select("h2.l-listTitle a, .topic-title a, a[href*='topicdetail']")
            if not links:
                links = soup.select("a.topic-title, .topic a")

            for link in links:
                href = link.get("href", "")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://www.mobile01.com/" + href.lstrip("/")

                title = link.get_text(strip=True)
                if not title:
                    continue

                try:
                    art_resp = session.get(href, timeout=15)
                    if art_resp.status_code != 200:
                        continue
                    art_soup = BeautifulSoup(art_resp.text, "html.parser")

                    time_el = art_soup.select_one("time, .publish-time, .post-time")
                    ts_str  = time_el.get("datetime", time_el.get_text(strip=True)) if time_el else ""
                    art_dt  = parse_dt(ts_str)

                    if not checker(art_dt, t_start, t_end):
                        continue

                    content_el = art_soup.select_one(
                        "article .l-message__articleBody, .post-content, .article-content"
                    )
                    content = content_el.get_text(separator=" ", strip=True)[:1500] if content_el else ""

                    author_el = art_soup.select_one(".username, .author-name")
                    author    = author_el.get_text(strip=True) if author_el else ""

                    reply_el = art_soup.select_one(".reply-count, .l-topic__replyCount")
                    reply_count = 0
                    if reply_el:
                        m = re.search(r"\d+", reply_el.get_text())
                        if m:
                            reply_count = int(m.group())

                    articles.append({
                        "type":         "article",
                        "title":        title,
                        "content":      content,
                        "url":          href,
                        "source":       "Mobile01",
                        "board":        board_name,
                        "author":       author,
                        "timestamp":    art_dt.isoformat() if art_dt else ts_str,
                        "reply_count":  reply_count,
                        "parent_title": "",
                    })
                    time.sleep(1.0)

                except:
                    continue

            time.sleep(1.5)

        except Exception as e:
            print(f"[Mobile01] {board_name} 第 {page} 頁失敗：{e}")
            break

    return articles
