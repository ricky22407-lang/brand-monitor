"""
crawlers/phase2/fb_crawler.py
使用 Playwright + Cookie 注入爬取 FB 社團與粉專。
直接解析 inner_text('body')，不依賴 role='article' selector。
"""

import re
import json
import time
import random
import pathlib
from datetime import datetime, timedelta
from typing import Optional

from core.utils import parse_dt, in_range, in_range_loose

M_BASE = "https://m.facebook.com"

# ── 強制停止旗標 ─────────────────────────────────
_STOP_REQUESTED = False

def request_stop():
    """由外部（app.py /api/stop）呼叫，讓爬蟲在下一個迭代安全退出"""
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    print("[FB] ⛔ 收到停止請求")

def reset_stop():
    """每次新爬蟲任務開始前重置旗標"""
    global _STOP_REQUESTED
    _STOP_REQUESTED = False

_UI_WORDS = {
    '讚', '留言', '分享', '回覆', '查看更多', '所有心情',
    '追蹤', '加入', '更多', 'Like', 'Comment', 'Share',
}

_SKIP_PATTERNS = [
    r"^\d+(小時|分鐘|天|週|月|秒)前?$",
    r"^\d+$",
    r"^所有心情：$",
    r"^查看更多.*$",
    r"^查看\s*\d+\s*則回覆$",
    r"^·$",
    r"^0:\d+\s*/\s*\d+:\d+$",
]

_STOP_LINES = {'送出第一則留言……', '撰寫回答……', '載入中……', '開啟應用程式'}


# ── Cookie 管理 ─────────────────────────────────

def _get_cookies_path() -> str:
    try:
        import core.config as _cfg
        return str(pathlib.Path(_cfg.CLIENT_DIR) / "fb_cookies.json")
    except:
        return "/tmp/fb_mbasic_cookies.json"


def check_profile_available() -> dict:
    try:
        with open(_get_cookies_path()) as f:
            c = json.load(f)
        if c.get("c_user") and c.get("xs"):
            return {"available": True, "message": f"Cookie 有效（帳號 {c.get('c_user','')}）"}
        return {"available": False, "message": "Cookie 不完整，請重新匯出"}
    except:
        return {"available": False, "message": "尚未設定 Cookie，請點「🍪 FB Cookie 設定」"}


def _load_cookies() -> list:
    try:
        with open(_get_cookies_path()) as f:
            data = json.load(f)
        items = [{"name": k, "value": v} for k, v in data.items()] if isinstance(data, dict) else data
        pw_cookies = []
        for c in items:
            if not c.get("name") or not c.get("value"):
                continue
            pw_cookies.append({
                "name":     c["name"],
                "value":    str(c["value"]),
                "domain":   c.get("domain", ".facebook.com"),
                "path":     c.get("path", "/"),
                "sameSite": "None",
                "secure":   True,
                "httpOnly": c.get("httpOnly", False),
            })
        user = data.get("c_user") if isinstance(data, dict) else "?"
        print(f"[FB] 載入 {len(pw_cookies)} 個 cookies（user: {user}）")
        return pw_cookies
    except Exception as e:
        print(f"[FB] 載入 cookies 失敗：{e}")
        return []


# ── 瀏覽器管理 ──────────────────────────────────

def _get_profile_dir() -> str:
    try:
        import core.config as _cfg
        return str(pathlib.Path(_cfg.CLIENT_DIR) / "chrome_profile")
    except:
        return "/tmp/fb_chrome_profile"


def _create_browser(playwright):
    """Persistent Context：登入狀態自動保存，重開不需重填 Cookie"""
    profile_dir = _get_profile_dir()
    pathlib.Path(profile_dir).mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=False,
        channel="chrome",
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--window-position=10000,10000",
        ],
        viewport={"width": 390, "height": 844},
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        locale="zh-TW",
        timezone_id="Asia/Taipei",
    )
    return None, context


def _setup_page(context, cookies: list):
    page = context.pages[0] if context.pages else context.new_page()
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
        print("[FB] playwright-stealth 已套用")
    except ImportError:
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = {runtime: {}};
        """)
    if cookies:
        try:
            context.add_cookies(cookies)
        except:
            pass
    return page


def _check_login(page) -> bool:
    try:
        print("[FB] 前往 m.facebook.com 確認登入...")
        page.goto(M_BASE, timeout=20000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
        url = page.url
        print(f"[FB] URL：{url}")
        if "login" in url or "checkpoint" in url:
            print("[FB] Cookie 已過期")
            return False
        print(f"[FB] 標題：{page.title()}")
        print("[FB] ✅ 登入確認成功")
        return True
    except Exception as e:
        print(f"[FB] 登入確認失敗：{e}")
        return False


def _dismiss_modal(page):
    try:
        removed = page.evaluate("""() => {
            let count = 0;
            document.querySelectorAll('div[role="dialog"]').forEach(el => {
                el.remove(); count++;
            });
            document.body.style.overflow = 'auto';
            return count;
        }""")
        if removed > 0:
            print(f"[FB] 移除 {removed} 個彈窗")
    except:
        pass


def _human_scroll(page, times=1):
    for _ in range(times):
        px = random.randint(800, 1400)
        page.evaluate(f"window.scrollBy(0, {px})")
        time.sleep(random.uniform(2, 3))


# ── 時間解析 ────────────────────────────────────

def _parse_relative_time(lines: list) -> Optional[datetime]:
    now = datetime.now().replace(microsecond=0)
    for line in lines[1:5]:
        line = line.replace('·', '').strip()
        if '剛剛' in line:
            return now
        for pattern, fn in [
            (r"(\d+)\s*分鐘", lambda m: timedelta(minutes=int(m.group(1)))),
            (r"(\d+)\s*小時", lambda m: timedelta(hours=int(m.group(1)))),
            (r"(\d+)\s*天",   lambda m: timedelta(days=int(m.group(1)))),
            (r"(\d+)\s*週",   lambda m: timedelta(weeks=int(m.group(1)))),
            (r"(\d+)\s*個月", lambda m: timedelta(days=int(m.group(1))*30)),
        ]:
            m = re.search(pattern, line)
            if m:
                return now - fn(m)
        m = re.search(r"(\d+)月(\d+)日", line)
        if m:
            try:
                return datetime(now.year, int(m.group(1)), int(m.group(2)))
            except:
                pass
    return None


# ── 頁面文字解析（不依賴 selector）────────────────

def _parse_body_text(full_text: str, fallback_url: str) -> list:
    """
    直接解析整頁 inner_text，以時間行作為貼文邊界。
    FB 行動版不使用 role='article'，改用此方法。
    """
    results = []
    seen_keys = set()

    # 第一步：移除零寬字元和方向標記（這些會破壞時間標記如「4天」）
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\ufeff]', '', full_text)
    # 第二步：移除其他特殊符號，保留中文、英文、標點
    text = re.sub(
        r'[^\u0020-\u007e\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef'
        r'\u3000-\u303f\uf900-\ufaff\n]',
        '', text
    )
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # 時間行：用來分割貼文邊界
    time_pat = re.compile(r'^(\d+)(小時|分鐘|天|週|個月)$')
    time_indices = [i for i, l in enumerate(lines) if time_pat.match(l)]

    if not time_indices:
        return []

    for idx, ti in enumerate(time_indices):
        # 作者：時間行前幾行找最接近的短文字（跳過噪音）
        _NOISE = {'•', '·', '追蹤', '最常發言的成員', '版主', '管理員'}
        author = ""
        for back in range(1, 6):
            if ti - back < 0:
                break
            cand = lines[ti - back]
            if (cand and len(cand) >= 2 and len(cand) < 60
                    and not time_pat.match(cand)
                    and cand not in _UI_WORDS
                    and cand not in _NOISE
                    and not re.match(r'^[•·\-\s]+$', cand)):
                author = cand
                break

        # 時間
        time_str = lines[ti]
        post_dt = _parse_relative_time(["", time_str])
        timestamp = post_dt.isoformat() if post_dt else ""

        # 內容：時間行之後到下一個時間行（或最多30行）
        next_ti = time_indices[idx + 1] if idx + 1 < len(time_indices) else len(lines)
        content_lines = []
        for i in range(ti + 1, min(next_ti, ti + 30)):
            line = lines[i]
            if line in _UI_WORDS:
                continue
            if line in _STOP_LINES:
                break
            if re.match(r'^\d+$', line):
                continue
            if re.match(r'^\d+(則留言|人回覆|則回覆)$', line):
                continue
            content_lines.append(line)

        content = '\n'.join(content_lines).strip()
        if len(content) < 3:
            continue

        # 用作者+內容前30字作為穩定去重鍵，避免每輪微小差異導致重複
        key = (author + content[:30]).strip()
        if key in seen_keys:
            continue
        seen_keys.add(key)

        post_id = str(abs(hash(key)))
        results.append({
            "id":        post_id,
            "content":   content,
            "author":    author,
            "timestamp": timestamp,
            "url":       fallback_url,
        })

    return results


def _get_post_url_by_click(page, element) -> Optional[str]:
    """
    點擊日期元素，等待 URL 跳轉到貼文頁，取得貼文 URL 後 go_back 返回。
    element 可以是 ElementHandle 或 Locator。
    """
    try:
        element.scroll_into_view_if_needed()
        time.sleep(0.3)
        box = element.bounding_box()
        if not box or box['y'] <= 0:
            return None
        before = page.url
        page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        try:
            page.wait_for_url(
                lambda u: 'story.php' in u or '/posts/' in u,
                timeout=8000
            )
        except:
            pass
        post_url = page.url
        if post_url == before:
            return None
        page.go_back(wait_until="domcontentloaded")
        time.sleep(1.5)
        _dismiss_modal(page)
        return post_url
    except Exception as e:
        print(f"[FB] _get_post_url_by_click 失敗：{e}")
        return None


def _extract_story_urls(obj, result: dict, depth=0):
    """遞迴從 GraphQL JSON 中找貼文 URL"""
    if depth > 8 or not isinstance(obj, dict):
        return
    sid = obj.get("story_id") or obj.get("id", "")
    url = obj.get("url", "")
    if (sid and url and str(sid).isdigit() and len(str(sid)) > 10
            and "facebook.com" in url):
        result[str(sid)] = url
    for v in obj.values():
        if isinstance(v, dict):
            _extract_story_urls(v, result, depth+1)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _extract_story_urls(item, result, depth+1)


# ── 社團爬蟲 ────────────────────────────────────

def _scrape_group(page, group_url, keyword_filter,
                  t_start, t_end, has_time_range, include_comments, checker):
    articles, comments, seen_ids = [], [], set()

    group_id = group_url.rstrip("/").split("/")[-1]
    url = f"{M_BASE}/groups/{group_id}"

    # GraphQL 攔截：取得貼文 URL
    story_urls = {}

    def _on_graphql(response):
        try:
            if "/api/graphql" not in response.url:
                return
            if response.status != 200:
                return
            import json as _j
            text = response.body().decode("utf-8", errors="ignore")
            for chunk in text.split("\n"):
                try:
                    obj = _j.loads(chunk)
                    _extract_story_urls(obj, story_urls)
                except:
                    pass
        except:
            pass

    page.on("response", _on_graphql)

    print(f"[FB社團] 前往：{url}")
    page.goto(url, timeout=20000)
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(3)
    _dismiss_modal(page)

    print(f"[FB社團] 標題：{page.title()} | URL：{page.url}")
    if "login" in page.url:
        print("[FB社團] 被導向登入頁")
        page.remove_listener("response", _on_graphql)
        return [], []

    # 切換排序為「新貼文」
    try:
        clicked = page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('div, span'));
            const sortEl = els.find(el => el.innerText && el.innerText.trim() === '排序' && el.children.length === 0);
            if (sortEl) { sortEl.click(); return true; }
            return false;
        }""")
        if clicked:
            time.sleep(1.5)
            page.evaluate("""() => {
                const els = Array.from(document.querySelectorAll('div, span'));
                const el = els.find(el => el.innerText && el.innerText.trim() === '新貼文' && el.children.length === 0);
                if (el) el.click();
            }""")
            time.sleep(2)
            print("[FB社團] ✅ 已切換為「新貼文」排序")
            _dismiss_modal(page)
    except Exception as e:
        print(f"[FB社團] 排序切換失敗（不影響）：{e}")

    out_of_range_streak = 0

    for scroll_idx in range(12):
        if _STOP_REQUESTED:
            print("[FB社團] ⛔ 收到停止，中斷貼文掃描")
            break
        _human_scroll(page, times=1)
        _dismiss_modal(page)

        # 展開所有「查看更多」
        try:
            page.evaluate("""() => {
                document.querySelectorAll('span, div').forEach(el => {
                    if (el.innerText && el.innerText.trim() === '查看更多' && el.children.length === 0) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0) el.click();
                    }
                });
            }""")
            time.sleep(0.5)
        except:
            pass

        # 收集日期元素（get_by_text locator，對應每篇貼文）
        date_elements = []
        try:
            _date_re = re.compile(r'\d+(天|小時|分鐘|週|個月)前?')
            _loc = page.get_by_text(_date_re)
            _cnt = _loc.count()
            date_elements = [_loc.nth(i) for i in range(_cnt)]
        except:
            pass

        try:
            full_text = page.inner_text("body")
        except Exception as e:
            print(f"[FB社團] inner_text 失敗：{e}")
            continue

        posts_data = _parse_body_text(full_text, group_url)
        print(f"[FB社團] 第 {scroll_idx+1} 輪解析到 {len(posts_data)} 篇（找到 {len(date_elements)} 個日期 locator）")

        stop = False
        new_posts = [d for d in posts_data if d and d["id"] not in seen_ids]

        for post_idx, d in enumerate(new_posts):
            seen_ids.add(d["id"])

            post_dt = parse_dt(d.get("timestamp", "")) if d.get("timestamp") else None

            if has_time_range and t_start and post_dt and post_dt < t_start:
                out_of_range_streak += 1
                if out_of_range_streak >= 5:
                    print("[FB社團] 連續 5 篇超出時間區間，停止")
                    stop = True
                continue
            else:
                out_of_range_streak = 0

            if post_dt is not None and not checker(post_dt, t_start, t_end):
                continue

            content = d.get("content", "")
            title   = content[:50]

            if keyword_filter.match(f"{title} {content}").matched:
                # 嘗試點擊日期元素取得貼文 URL
                post_url = story_urls.get(d.get("id", ""), group_url)
                if post_url == group_url and post_idx < len(date_elements):
                    clicked_url = _get_post_url_by_click(page, date_elements[post_idx])
                    if clicked_url:
                        post_url = clicked_url
                        print(f"[FB社團] 取得貼文 URL：{post_url[:60]}")

                articles.append({
                    "type":         "article",
                    "title":        f"[FB社團] {title}",
                    "content":      content,
                    "url":          post_url,
                    "source":       "Facebook",
                    "board":        "社團",
                    "author":       d.get("author", ""),
                    "timestamp":    d.get("timestamp", ""),
                    "parent_title": "",
                })

        if stop:
            break

    page.remove_listener("response", _on_graphql)
    if story_urls:
        print(f"[FB社團] GraphQL 攔截到 {len(story_urls)} 個貼文 URL")
    print(f"[FB社團] 完成：{len(articles)} 篇，{len(comments)} 則留言")
    return articles, comments


# ── 粉專爬蟲 ────────────────────────────────────

def _scrape_page(page, page_url, keyword_filter,
                 t_start, t_end, has_time_range, checker):
    articles = []
    seen_ids = set()

    page_id = page_url.rstrip("/").split("/")[-1]
    url = f"{M_BASE}/{page_id}"

    print(f"[FB粉專] 前往：{url}")
    try:
        page.goto(url, timeout=25000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"[FB粉專] goto 失敗：{e}")
        return []

    time.sleep(3)
    _dismiss_modal(page)

    print(f"[FB粉專] 標題：{page.title()} | URL：{page.url}")
    if "login" in page.url:
        print("[FB粉專] 被導向登入頁")
        return []

    # 粉專頂部有封面/簡介，先滾過去
    page.evaluate("window.scrollBy(0, 400)")
    time.sleep(2)
    _dismiss_modal(page)

    out_of_range_streak = 0

    for scroll_round in range(10):
        if _STOP_REQUESTED:
            print("[FB粉專] ⛔ 收到停止，中斷掃描")
            break
        _human_scroll(page, times=1)
        _dismiss_modal(page)

        # 展開所有「查看更多」
        try:
            page.evaluate("""() => {
                document.querySelectorAll('span, div').forEach(el => {
                    if (el.innerText && el.innerText.trim() === '查看更多' && el.children.length === 0) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0) el.click();
                    }
                });
            }""")
            time.sleep(0.5)
        except:
            pass

        # 收集日期元素（get_by_text locator）
        date_elements = []
        try:
            _date_re = re.compile(r'\d+(天|小時|分鐘|週|個月)前?')
            _loc = page.get_by_text(_date_re)
            _cnt = _loc.count()
            date_elements = [_loc.nth(i) for i in range(_cnt)]
        except:
            pass

        try:
            full_text = page.inner_text("body")
        except Exception as e:
            print(f"[FB粉專] inner_text 失敗：{e}")
            continue

        posts_data = _parse_body_text(full_text, page_url)
        print(f"[FB粉專] 第 {scroll_round+1} 輪解析到 {len(posts_data)} 篇（找到 {len(date_elements)} 個日期 locator）")

        if scroll_round == 0 and len(posts_data) == 0:
            try:
                shot_path = str(pathlib.Path(_get_cookies_path()).parent / "fb_page_debug.png")
                page.screenshot(path=shot_path, full_page=False)
                print(f"[FB粉專] 截圖已存：{shot_path}")
            except:
                pass

        stop = False
        new_posts = [d for d in posts_data if d and d["id"] not in seen_ids]

        for post_idx, d in enumerate(new_posts):
            seen_ids.add(d["id"])

            post_dt = parse_dt(d.get("timestamp", "")) if d.get("timestamp") else None

            if has_time_range and t_start and post_dt and post_dt < t_start:
                out_of_range_streak += 1
                if out_of_range_streak >= 5:
                    stop = True
                continue
            else:
                out_of_range_streak = 0

            if post_dt is not None and not checker(post_dt, t_start, t_end):
                continue

            content = d.get("content", "")
            if keyword_filter.match(content).matched:
                # 嘗試點擊日期元素取得貼文 URL
                post_url = page_url
                if post_idx < len(date_elements):
                    clicked_url = _get_post_url_by_click(page, date_elements[post_idx])
                    if clicked_url:
                        post_url = clicked_url
                        print(f"[FB粉專] 取得貼文 URL：{post_url[:60]}")

                articles.append({
                    "type":         "article",
                    "title":        f"[FB粉專] {content[:50]}",
                    "content":      content,
                    "url":          post_url,
                    "source":       "Facebook",
                    "board":        "粉專",
                    "author":       d.get("author", ""),
                    "timestamp":    d.get("timestamp", ""),
                    "parent_title": "",
                })

        if stop:
            print("[FB粉專] 已超出時間區間，停止")
            break

    print(f"[FB粉專] 完成：{len(articles)} 篇")
    return articles


# ── 公開介面 ────────────────────────────────────

def fetch_fb_all(group_urls, page_urls, keyword_filter, t_start, t_end,
                 has_time_range=False, include_comments=True):
    if not group_urls and not page_urls:
        return [], [], []

    reset_stop()   # 每次任務開始前清除停止旗標

    status = check_profile_available()
    if not status["available"]:
        print(f"[FB] {status['message']}")
        return [], [], []

    cookies = _load_cookies()
    if not cookies:
        print("[FB] 無 cookies，跳過")
        return [], [], []

    from playwright.sync_api import sync_playwright
    group_articles, group_comments, page_articles = [], [], []

    try:
        with sync_playwright() as p:
            browser, context = _create_browser(p)
            page = _setup_page(context, cookies)

            if not _check_login(page):
                context.close()
                return [], [], []

            checker = in_range if has_time_range else in_range_loose

            for url in group_urls:
                try:
                    a, c = _scrape_group(page, url, keyword_filter,
                                         t_start, t_end, has_time_range,
                                         include_comments, checker)
                    group_articles.extend(a)
                    group_comments.extend(c)
                    print(f"[FB社團] {url[:50]}：貼文 {len(a)}，留言 {len(c)}")
                    time.sleep(random.uniform(3, 5))
                except Exception as e:
                    print(f"[FB社團] {url[:50]} 失敗：{e}")

            # 留言獨立掃描（最新動態排序）
            if include_comments:
                for url in group_urls:
                    try:
                        cmts = _scrape_group_comments(
                            page, url, keyword_filter,
                            t_start, t_end, has_time_range, checker
                        )
                        group_comments.extend(cmts)
                        time.sleep(random.uniform(3, 5))
                    except Exception as e:
                        print(f"[FB留言] {url[:50]} 失敗：{e}")

            page2 = _setup_page(context, cookies)
            for url in page_urls:
                try:
                    arts = _scrape_page(page2, url, keyword_filter,
                                        t_start, t_end, has_time_range, checker)
                    page_articles.extend(arts)
                    print(f"[FB粉專] {url[:50]}：{len(arts)} 篇")
                    time.sleep(random.uniform(3, 5))
                except Exception as e:
                    print(f"[FB粉專] {url[:50]} 失敗：{e}")

            context.close()
    except Exception as e:
        print(f"[FB] 瀏覽器失敗：{e}")

    return group_articles, group_comments, page_articles


def fetch_fb_groups(group_urls, keyword_filter, t_start, t_end,
                    has_time_range=False, include_comments=True):
    a, c, _ = fetch_fb_all(group_urls, [], keyword_filter, t_start, t_end,
                            has_time_range, include_comments)
    return a, c


def fetch_fb_pages(page_urls, keyword_filter, t_start, t_end, has_time_range=False):
    _, _, arts = fetch_fb_all([], page_urls, keyword_filter, t_start, t_end, has_time_range)
    return arts


# ── 留言爬蟲（獨立掃描，最新動態排序）────────────────

def _scrape_group_comments(page, group_url, keyword_filter,
                           t_start, t_end, has_time_range, checker):
    """
    用「最新動態」排序掃社團，用新分頁進入每篇貼文抓留言。
    社團頁全程不導航，捲動位置持續往下推進。
    """
    import re as _re4
    comments = []
    seen_comment_keys = set()

    group_id = group_url.rstrip("/").split("/")[-1]
    url = f"{M_BASE}/groups/{group_id}"
    ctx = page.context   # 用來開新分頁

    print(f"[FB留言] 前往社團（最新動態排序）：{url}")
    page.goto(url, timeout=20000)
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(3)
    _dismiss_modal(page)

    if "login" in page.url:
        return []

    # 切換為「最新動態」排序
    try:
        clicked = page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('div, span'));
            const el = els.find(e => e.innerText && e.innerText.trim() === '排序' && e.children.length === 0);
            if (el) { el.click(); return true; }
            return false;
        }""")
        if clicked:
            time.sleep(1.5)
            page.evaluate("""() => {
                const els = Array.from(document.querySelectorAll('div, span'));
                const el = els.find(e => e.innerText && e.innerText.trim() === '最新動態' && e.children.length === 0);
                if (el) el.click();
            }""")
            time.sleep(2)
            print("[FB留言] ✅ 已切換為「最新動態」排序")
            _dismiss_modal(page)
    except Exception as e:
        print(f"[FB留言] 排序切換失敗：{e}")

    post_urls_seen = set()   # 已處理的貼文 URL（含已收留言和跳過的）
    time_regex = _re4.compile(r'\d+(天|小時|分鐘|週|個月)前?')
    MAX_POSTS   = 20
    no_new_rounds = 0        # 連續沒找到新 URL 的輪數

    # ── Phase 1+2 合併：邊 scroll 邊開新分頁抓留言 ───────────────
    # 核心設計：
    #   - 社團頁（page）全程不離開，捲動位置持續往下
    #   - 每個日期元素透過 JS 抽取其 <a> 的 href（不觸發導航）
    #   - 拿到 URL 後，開新分頁抓留言，完成後關閉新分頁
    #   - 回到社團頁繼續往下 scroll，DOM 完全沒刷新
    for scroll_idx in range(80):   # 最多 80 輪 scroll（足夠覆蓋 20 篇）
        if _STOP_REQUESTED:
            print("[FB留言] ⛔ 收到停止，中斷留言掃描")
            break
        if len(post_urls_seen) >= MAX_POSTS:
            break

        _human_scroll(page, times=1)
        _dismiss_modal(page)

        # 從每個日期元素的最近 <a> 祖先抽取 href（完全不導航）
        try:
            hrefs = page.evaluate("""(timePattern) => {
                const results = [];
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                );
                let node;
                while ((node = walker.nextNode())) {
                    if (new RegExp(timePattern).test(node.textContent.trim())) {
                        let el = node.parentElement;
                        // 往上找最近的 <a>，最多找 6 層
                        for (let i = 0; i < 6; i++) {
                            if (!el) break;
                            if (el.tagName === 'A' && el.href) {
                                results.push(el.href);
                                break;
                            }
                            el = el.parentElement;
                        }
                    }
                }
                return results;
            }""", r'\d+(天|小時|分鐘|週|個月)前?')
        except Exception:
            hrefs = []

        # 過濾出貼文 URL（story.php 或 /posts/）
        new_urls = []
        for h in hrefs:
            if ('story.php' in h or '/posts/' in h) and h not in post_urls_seen:
                new_urls.append(h)

        if not new_urls:
            no_new_rounds += 1
            if no_new_rounds >= 5:
                print(f"[FB留言] 連續 {no_new_rounds} 輪無新貼文，停止")
                break
            continue
        no_new_rounds = 0

        for post_url in new_urls:
            if _STOP_REQUESTED:
                break
            if len(post_urls_seen) >= MAX_POSTS:
                break

            post_urls_seen.add(post_url)
            print(f"[FB留言] 進入貼文（{len(post_urls_seen)}/{MAX_POSTS}）：{post_url[:70]}")

            # ── 在主頁面導航到貼文，抓完留言後回社團並恢復捲動位置 ──
            try:
                # 記住目前捲動位置
                scroll_y = page.evaluate("window.scrollY") or 0

                for attempt in range(2):
                    try:
                        page.goto(post_url, timeout=30000, wait_until="domcontentloaded")
                        break
                    except Exception as e:
                        if attempt == 0:
                            print(f"[FB留言] retry goto：{e}")
                            time.sleep(3)

                cur = page.url
                if "login" in cur or cur == "about:blank":
                    page.goto(url, timeout=20000, wait_until="domcontentloaded")
                    page.evaluate(f"window.scrollTo(0, {scroll_y})")
                    continue

                time.sleep(2)
                _dismiss_modal(page)

                # 展開「查看更多留言」（最多 3 次）
                for _ in range(3):
                    try:
                        more = page.get_by_text("查看更多留言")
                        if more.count() > 0:
                            more.first.click()
                            time.sleep(1)
                        else:
                            break
                    except Exception:
                        break

                # 讀取整頁文字
                try:
                    raw = page.inner_text("body")
                except Exception:
                    page.goto(url, timeout=20000, wait_until="domcontentloaded")
                    page.evaluate(f"window.scrollTo(0, {scroll_y})")
                    continue

                raw  = _re4.sub(r'[\u200b-\u200f\u202a-\u202e\ufeff]', '', raw)
                text = _re4.sub(
                    r'[^\u0020-\u007e\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef'
                    r'\u3000-\u303f\uf900-\ufaff\n]',
                    '', raw
                )
                lines = [l.strip() for l in text.split('\n') if l.strip()]

                time_pat = _re4.compile(r'^\d+(天|小時|分鐘|週|個月)前?$')
                time_indices = [i for i, l in enumerate(lines) if time_pat.match(l)]

                _NOISE = {'•', '·', '追蹤', '回覆', '讚', '查看更多回覆', '查看更多留言'}

                # 第 0 個時間行是貼文本體，第 1 個之後是留言
                comment_time_indices = time_indices[1:] if len(time_indices) > 1 else []
                print(f"[FB留言] 此貼文找到 {len(comment_time_indices)} 則留言候選")

                for cidx, ti in enumerate(comment_time_indices):
                    if _STOP_REQUESTED:
                        break

                    # 作者
                    author = ""
                    for back in range(1, 5):
                        if ti - back < 0:
                            break
                        cand = lines[ti - back]
                        if cand and len(cand) < 60 and not time_pat.match(cand) and cand not in _NOISE:
                            author = cand
                            break

                    # 時間
                    post_dt = _parse_relative_time(["", lines[ti]])
                    timestamp = post_dt.isoformat() if post_dt else ""

                    # 時間篩選
                    if post_dt is not None and not checker(post_dt, t_start, t_end):
                        continue
                    if has_time_range and t_start and post_dt and post_dt < t_start:
                        break

                    # 內容
                    next_ti = comment_time_indices[cidx+1] if cidx+1 < len(comment_time_indices) else len(lines)
                    content_lines = []
                    for i in range(ti+1, min(next_ti, ti+20)):
                        line = lines[i]
                        if line in _NOISE or _re4.match(r'^\d+$', line):
                            continue
                        content_lines.append(line)

                    content = '\n'.join(content_lines).strip()
                    if len(content) < 2:
                        continue

                    key = (author + content[:30]).strip()
                    if key in seen_comment_keys:
                        continue
                    seen_comment_keys.add(key)

                    if not keyword_filter.match(content).matched:
                        continue

                    comments.append({
                        "type":         "comment",
                        "title":        f"[FB留言] {content[:40]}",
                        "content":      content,
                        "url":          post_url,
                        "source":       "Facebook",
                        "board":        "社團",
                        "author":       author,
                        "timestamp":    timestamp,
                        "parent_title": post_url,
                    })
                    print(f"[FB留言] ✅ 收錄：{author} - {content[:30]}")

            except Exception as e:
                print(f"[FB留言] 貼文 {post_url[:50]} 失敗：{e}")
            finally:
                # 回到社團頁並恢復捲動位置
                try:
                    if "groups" not in page.url:
                        page.goto(url, timeout=20000, wait_until="domcontentloaded")
                    page.evaluate(f"window.scrollTo(0, {scroll_y})")
                    time.sleep(1)
                    _dismiss_modal(page)
                except Exception:
                    pass

    print(f"[FB留言] 完成：共掃描 {len(post_urls_seen)} 篇，收錄 {len(comments)} 則留言")
    return comments





