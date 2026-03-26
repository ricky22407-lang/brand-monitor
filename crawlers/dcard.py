"""
crawlers/dcard.py
Dcard 爬蟲：路徑A（文章）+ 路徑B（留言）
"""

import time
from datetime import datetime
from typing import Optional

import requests

from core.utils import in_range, in_range_loose, parse_dt


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin":          "https://www.dcard.tw",
        "Referer":         "https://www.dcard.tw/f",
        "sec-ch-ua":       '"Chromium";v="124", "Google Chrome";v="124"',
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": '"macOS"',
        "Sec-Fetch-Dest":  "empty",
        "Sec-Fetch-Mode":  "cors",
        "Sec-Fetch-Site":  "same-origin",
    })
    return s


def _fallback_web(session, board: str) -> list:
    """API 403 時改爬網頁版，只取標題"""
    from bs4 import BeautifulSoup
    articles = []
    try:
        resp = session.get(f"https://www.dcard.tw/f/{board}", timeout=15)
        if resp.status_code != 200:
            return articles
        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.select("article a[href*='/p/']")[:20]:
            href  = a_tag.get("href", "")
            url   = f"https://www.dcard.tw{href}" if href.startswith("/") else href
            title = a_tag.get_text(strip=True)[:80]
            if title:
                articles.append({
                    "type": "article", "title": title, "content": "",
                    "url": url, "source": "Dcard", "board": board,
                    "author": "", "timestamp": "", "like_count": 0, "parent_title": "",
                })
    except Exception as e:
        print(f"[Dcard] 網頁備用失敗：{e}")
    return articles


def fetch_dcard(board: str, t_start, t_end,
                comment_pages: int = 0,
                has_time_range: bool = False) -> tuple[list, list]:
    """
    Returns:
        (articles, comments)
    """
    session = _make_session()

    # Warm-up：先訪問首頁取 cookie
    try:
        session.get("https://www.dcard.tw/f", timeout=10)
        time.sleep(1.5)
        session.get(f"https://www.dcard.tw/f/{board}", timeout=10)
        time.sleep(1.0)
    except:
        pass

    articles        = []
    comments        = []
    params          = {"limit": 30}
    page_idx        = 0
    consecutive_old = 0
    checker         = in_range if has_time_range else in_range_loose

    while page_idx < max(comment_pages + 2, 5):
        try:
            resp = session.get(
                f"https://www.dcard.tw/service/api/v2/forums/{board}/posts",
                params=params, timeout=15
            )
            if resp.status_code == 429:
                print(f"[Dcard] {board} 速率限制，等 15 秒...")
                time.sleep(15)
                resp = session.get(
                    f"https://www.dcard.tw/service/api/v2/forums/{board}/posts",
                    params=params, timeout=15
                )
            if resp.status_code == 403:
                print(f"[Dcard] {board} 403，改用備用方式...")
                articles.extend(_fallback_web(session, board))
                break
            if resp.status_code != 200 or not resp.text.strip():
                print(f"[Dcard] {board} API 回傳 {resp.status_code}")
                break

            posts = resp.json()
            if isinstance(posts, dict):
                posts = posts.get("posts", posts.get("data", []))

        except Exception as e:
            print(f"[Dcard] {board} 失敗：{e}")
            break

        if not posts:
            break

        for post in posts:
            post_id = post.get("id")
            created = post.get("createdAt", "")
            art_dt  = parse_dt(created)
            forum   = post.get("forumAlias") or board
            title   = post.get("title", "")
            url     = f"https://www.dcard.tw/f/{forum}/p/{post_id}"
            author  = str(post.get("school", "匿名"))

            # 路徑A
            if checker(art_dt, t_start, t_end):
                articles.append({
                    "type":         "article",
                    "title":        title,
                    "content":      post.get("excerpt", ""),
                    "url":          url,
                    "source":       "Dcard",
                    "board":        board,
                    "author":       author,
                    "timestamp":    art_dt.isoformat() if art_dt else created,
                    "like_count":   post.get("likeCount", 0),
                    "parent_title": "",
                })
                consecutive_old = 0
            else:
                if art_dt and t_start and art_dt < t_start:
                    consecutive_old += 1

            # 路徑B
            if page_idx < comment_pages and post_id:
                try:
                    c_resp = session.get(
                        f"https://www.dcard.tw/service/api/v2/posts/{post_id}/comments",
                        params={"limit": 30}, timeout=10
                    )
                    if c_resp.status_code != 200 or not c_resp.text.strip():
                        continue
                    for c in c_resp.json():
                        c_content = c.get("content", "").strip()
                        if not c_content:
                            continue
                        c_dt = parse_dt(c.get("createdAt", ""))

                        if has_time_range and c_dt is not None:
                            if not in_range(c_dt, t_start, t_end):
                                continue

                        comments.append({
                            "type":         "comment",
                            "title":        f"[留言] {c_content[:40]}",
                            "content":      c_content,
                            "url":          url,
                            "source":       "Dcard",
                            "board":        board,
                            "author":       str(c.get("school", "匿名")),
                            "timestamp":    c_dt.isoformat() if c_dt else "",
                            "like_count":   c.get("likeCount", 0),
                            "parent_title": title,
                        })
                    time.sleep(0.5)
                except:
                    pass

        params["before"] = posts[-1].get("id")
        page_idx += 1
        time.sleep(1.0)

        if consecutive_old >= 5 and page_idx >= comment_pages:
            break

    return articles, comments
