"""
crawlers/phase2/fb_crawler.py

使用 Playwright + Chrome Profile 3 爬取 FB 社團與粉專。
執行期間 Chrome Profile 3 不能同時開著。
"""

import re
import time
import pathlib
import subprocess
from datetime import datetime
from typing import Optional

from core.utils import parse_dt, in_range, in_range_loose

CHROME_PROFILE_PATH = "/Users/Ricky_1/Library/Application Support/Google/Chrome/Profile 3"


def check_profile_available() -> dict:
    """檢查 Profile 3 是否可用"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "Profile 3"],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            return {"available": False, "message": "Chrome Profile 3 正在使用中，請先關閉"}
    except:
        pass
    return {"available": True, "message": "Profile 3 可用"}


def _create_context(playwright):
    return playwright.chromium.launch_persistent_context(
        user_data_dir=CHROME_PROFILE_PATH,
        headless=True,
        channel="chrome",
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
        viewport={"width": 1280, "height": 800},
        locale="zh-TW",
    )


def _check_login(page) -> bool:
    try:
        page.goto("https://www.facebook.com", timeout=20000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
        return "login" not in page.url and "checkpoint" not in page.url
    except:
        return False


def _extract_post(post_el, fallback_url: str) -> Optional[dict]:
    try:
        content_el = post_el.query_selector("div[data-ad-comet-preview='message'], div[dir='auto']")
        content    = content_el.inner_text().strip() if content_el else ""
        if not content or len(content) < 3:
            return None

        author_el = post_el.query_selector("h2 a, h3 a, strong a")
        author    = author_el.inner_text().strip() if author_el else ""

        timestamp = ""
        time_el   = post_el.query_selector("abbr[data-utime]")
        if time_el:
            utime = time_el.get_attribute("data-utime")
            if utime:
                try:
                    timestamp = datetime.fromtimestamp(int(utime)).isoformat()
                except:
                    pass

        link_el = post_el.query_selector("a[href*='/posts/'], a[href*='story_fbid'], a[href*='/permalink/']")
        url     = ""
        if link_el:
            href = link_el.get_attribute("href") or ""
            url  = href if href.startswith("http") else "https://www.facebook.com" + href

        m       = re.search(r"/(\d+)/?$", url) if url else None
        post_id = m.group(1) if m else str(abs(hash(content[:30])))

        return {"id": post_id, "content": content, "author": author, "timestamp": timestamp, "url": url or fallback_url}
    except:
        return None


def _scrape_comments(page, post_url: str, keyword_filter,
                     t_start, t_end, has_time_range: bool,
                     checker, parent_title: str = "") -> list:
    comments = []
    try:
        page.goto(post_url, timeout=20000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
        for btn in page.query_selector_all("div[role='button']:has-text('查看更多留言')")[:3]:
            try:
                btn.click(); time.sleep(1)
            except:
                pass
        for c_el in page.query_selector_all("div[aria-label*='留言'], ul li div[role='article']"):
            try:
                c_content = c_el.inner_text().strip()
                if not c_content or len(c_content) < 2:
                    continue
                c_dt = None
                c_ts = ""
                t_el = c_el.query_selector("abbr[data-utime]")
                if t_el:
                    ut = t_el.get_attribute("data-utime")
                    if ut:
                        try:
                            c_dt = datetime.fromtimestamp(int(ut)); c_ts = c_dt.isoformat()
                        except:
                            pass
                if has_time_range and c_dt and not in_range(c_dt, t_start, t_end):
                    continue
                if not keyword_filter.match(c_content).matched:
                    continue
                a_el   = c_el.query_selector("span[dir='auto'] a, h3 a")
                author = a_el.inner_text().strip() if a_el else ""
                comments.append({
                    "type": "comment", "title": f"[FB留言] {c_content[:40]}",
                    "content": c_content, "url": post_url,
                    "source": "Facebook", "board": "社團",
                    "author": author, "timestamp": c_ts, "parent_title": parent_title,
                })
            except:
                continue
    except Exception as e:
        print(f"[FB] 留言失敗：{e}")
    return comments


def _scrape_group(page, group_url, keyword_filter, t_start, t_end,
                  has_time_range, include_comments, checker):
    articles, comments, seen_ids = [], [], set()
    page.goto(group_url, timeout=20000)
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(3)

    for _ in range(8):
        page.evaluate("window.scrollBy(0, 1500)"); time.sleep(2.5)
        stop = False
        for post in page.query_selector_all("div[role='article']"):
            d = _extract_post(post, group_url)
            if not d or d["id"] in seen_ids:
                continue
            seen_ids.add(d["id"])
            post_dt = parse_dt(d.get("timestamp", ""))
            if has_time_range and t_start and post_dt and post_dt < t_start:
                stop = True; continue
            if not checker(post_dt, t_start, t_end):
                continue
            content = d.get("content", ""); title = content[:50]
            if keyword_filter.match(f"{title} {content}").matched:
                articles.append({
                    "type": "article", "title": f"[FB社團] {title}",
                    "content": content, "url": d.get("url", group_url),
                    "source": "Facebook", "board": "社團",
                    "author": d.get("author", ""),
                    "timestamp": post_dt.isoformat() if post_dt else "",
                    "parent_title": "",
                })
            if include_comments and d.get("url"):
                try:
                    cmts = _scrape_comments(page, d["url"], keyword_filter,
                                            t_start, t_end, has_time_range, checker, title)
                    comments.extend(cmts); time.sleep(1.5)
                except:
                    pass
        if stop:
            break
    return articles, comments


def fetch_fb_groups(group_urls, keyword_filter, t_start, t_end,
                    has_time_range=False, include_comments=True):
    if not group_urls:
        return [], []
    status = check_profile_available()
    if not status["available"]:
        print(f"[FB社團] {status['message']}"); return [], []

    from playwright.sync_api import sync_playwright
    articles, comments = [], []
    try:
        with sync_playwright() as p:
            ctx  = _create_context(p)
            page = ctx.new_page()
            if not _check_login(page):
                print("[FB社團] 未登入，請在 Chrome Profile 3 登入 Facebook")
                ctx.close(); return [], []
            checker = in_range if has_time_range else in_range_loose
            for url in group_urls:
                try:
                    a, c = _scrape_group(page, url, keyword_filter, t_start, t_end,
                                         has_time_range, include_comments, checker)
                    articles.extend(a); comments.extend(c)
                    print(f"[FB社團] {url[:50]}：貼文 {len(a)}，留言 {len(c)}")
                    time.sleep(3)
                except Exception as e:
                    print(f"[FB社團] 失敗：{e}")
            ctx.close()
    except Exception as e:
        print(f"[FB社團] 瀏覽器啟動失敗：{e}")
    return articles, comments


def fetch_fb_pages(page_urls, keyword_filter, t_start, t_end, has_time_range=False):
    if not page_urls:
        return []
    status = check_profile_available()
    if not status["available"]:
        print(f"[FB粉專] {status['message']}"); return []

    from playwright.sync_api import sync_playwright
    articles = []
    checker  = in_range if has_time_range else in_range_loose
    try:
        with sync_playwright() as p:
            ctx  = _create_context(p)
            page = ctx.new_page()
            if not _check_login(page):
                print("[FB粉專] 未登入"); ctx.close(); return []
            for page_url in page_urls:
                try:
                    seen_ids = set()
                    page.goto(page_url, timeout=20000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    time.sleep(3)
                    for _ in range(5):
                        page.evaluate("window.scrollBy(0, 1500)"); time.sleep(2.5)
                        for post in page.query_selector_all("div[role='article']"):
                            d = _extract_post(post, page_url)
                            if not d or d["id"] in seen_ids:
                                continue
                            seen_ids.add(d["id"])
                            post_dt = parse_dt(d.get("timestamp", ""))
                            if not checker(post_dt, t_start, t_end):
                                continue
                            content = d.get("content", "")
                            if keyword_filter.match(content).matched:
                                articles.append({
                                    "type": "article", "title": f"[FB粉專] {content[:50]}",
                                    "content": content, "url": d.get("url", page_url),
                                    "source": "Facebook", "board": "粉專",
                                    "author": d.get("author", ""),
                                    "timestamp": post_dt.isoformat() if post_dt else "",
                                    "parent_title": "",
                                })
                    print(f"[FB粉專] {page_url[:50]}：{len(articles)} 篇")
                    time.sleep(3)
                except Exception as e:
                    print(f"[FB粉專] {page_url[:50]} 失敗：{e}")
            ctx.close()
    except Exception as e:
        print(f"[FB粉專] 瀏覽器啟動失敗：{e}")
    return articles
