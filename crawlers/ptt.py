"""
crawlers/ptt.py
PTT 爬蟲：路徑A（文章主文）+ 路徑B（留言）
統一回傳格式：{"type", "title", "content", "url", "source", "board",
               "author", "timestamp", "push_count", "parent_title"}
"""

import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from core.utils import in_range, in_range_loose, parse_dt

PTT_BASE = "https://www.ptt.cc"


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer":                   "https://www.ptt.cc/bbs/index.html",
        "Accept":                    "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language":           "zh-TW,zh;q=0.9,en;q=0.8",
        "Cache-Control":             "max-age=0",
        "Upgrade-Insecure-Requests": "1",
    })
    s.cookies.update({"over18": "1"})
    return s


def fetch_ptt(board: str, t_start, t_end, comment_pages: int = 0,
              has_time_range: bool = False) -> tuple[list, list]:
    """
    路徑A：文章主文，時間在區間內才納入
    路徑B：往回 comment_pages 頁的留言，留言時間在區間內才納入

    Returns:
        (articles, comments)
    """
    session = _make_session()
    try:
        session.get(f"{PTT_BASE}/bbs/index.html", timeout=10)
        time.sleep(0.5)
    except:
        pass

    articles       = []
    comments       = []
    url            = f"{PTT_BASE}/bbs/{board}/index.html"
    consecutive_old = 0
    checker        = in_range if has_time_range else in_range_loose

    for page_idx in range(max(comment_pages + 2, 5)):
        try:
            resp = session.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            prev_url = None
            for btn in soup.select("a.btn.wide"):
                if "上頁" in btn.text:
                    prev_url = btn.get("href")
                    break

            for item in soup.select("div.r-ent"):
                a_tag = item.select_one("div.title a")
                if not a_tag or not a_tag.get("href"):
                    continue
                path = a_tag["href"]

                need_article  = (consecutive_old < 5)
                need_comments = (comment_pages > 0) and (page_idx < comment_pages)

                if not need_article and not need_comments:
                    continue

                try:
                    art_resp = session.get(PTT_BASE + path, timeout=15)
                    art_soup = BeautifulSoup(art_resp.text, "html.parser")

                    # 取 meta
                    meta = {}
                    for block in art_soup.select("div.article-metaline"):
                        t = block.select_one("span.article-meta-tag")
                        v = block.select_one("span.article-meta-value")
                        if t and v:
                            meta[t.text.strip()] = v.text.strip()

                    title      = meta.get("標題", a_tag.get_text().strip())
                    author     = meta.get("作者", "").split(" ")[0]
                    time_str   = meta.get("時間", "")
                    precise_dt = parse_dt(time_str)

                    # 路徑A
                    if need_article and checker(precise_dt, t_start, t_end):
                        main = art_soup.select_one("div#main-content")
                        content = ""
                        if main:
                            for tag in main.select(
                                "div.article-metaline,div.article-metaline-right,div.push,span.f2"
                            ):
                                tag.decompose()
                            content = re.sub(
                                r"\n--\n.*", "",
                                main.get_text(separator="\n"),
                                flags=re.DOTALL
                            ).strip()

                        push_count = sum(
                            1  if p.get_text().strip() == "推" else
                            -1 if p.get_text().strip() == "噓" else 0
                            for p in art_soup.select("span.push-tag")
                        )
                        articles.append({
                            "type":        "article",
                            "title":       title,
                            "content":     content,
                            "url":         PTT_BASE + path,
                            "source":      "PTT",
                            "board":       board,
                            "author":      author,
                            "timestamp":   precise_dt.isoformat() if precise_dt else time_str,
                            "push_count":  push_count,
                            "parent_title": "",
                        })
                        consecutive_old = 0
                    elif precise_dt and t_start and precise_dt < t_start:
                        consecutive_old += 1

                    # 路徑B
                    if need_comments:
                        year = datetime.now().year
                        for push in art_soup.select("div.push"):
                            uid_el  = push.select_one("span.push-userid")
                            cnt_el  = push.select_one("span.push-content")
                            ipdt_el = push.select_one("span.push-ipdatetime")
                            if not cnt_el:
                                continue

                            c_content = cnt_el.get_text().lstrip(": ").strip()
                            raw_ipdt  = ipdt_el.get_text().strip() if ipdt_el else ""

                            c_dt = None
                            m = re.search(r"(\d{1,2}/\d{1,2}\s+\d{2}:\d{2})", raw_ipdt)
                            if m:
                                try:
                                    c_dt = datetime.strptime(
                                        f"{year}/{m.group(1)}", "%Y/%m/%d %H:%M"
                                    )
                                except:
                                    pass

                            if has_time_range and c_dt is not None:
                                if not in_range(c_dt, t_start, t_end):
                                    continue

                            comments.append({
                                "type":         "comment",
                                "title":        f"[留言] {c_content[:40]}",
                                "content":      c_content,
                                "url":          PTT_BASE + path,
                                "source":       "PTT",
                                "board":        board,
                                "author":       uid_el.get_text().strip() if uid_el else "",
                                "timestamp":    c_dt.isoformat() if c_dt else raw_ipdt,
                                "push_count":   0,
                                "parent_title": title,
                            })

                    time.sleep(0.8)

                except Exception as e:
                    pass

            if not prev_url:
                break
            if consecutive_old >= 5 and page_idx >= comment_pages - 1:
                break
            url = PTT_BASE + prev_url

        except Exception as e:
            print(f"[PTT] {board} 第 {page_idx+1} 頁失敗：{e}")
            break

    return articles, comments
