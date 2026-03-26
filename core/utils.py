"""
core/utils.py
共用工具函式：時間解析、範圍判斷、HTTP session 建立
"""

import re
import time
import requests
from datetime import datetime
from typing import Optional


def parse_dt(s) -> Optional[datetime]:
    """
    把各種時間字串轉成 datetime，失敗回傳 None。
    支援：PTT文章、PTT留言、Dcard API、News RSS、ISO格式
    """
    if not s:
        return None
    s = str(s).strip()
    s = re.sub(r'\s*([\+\-]\d{4}|GMT|UTC|Z)$', '', s).strip()

    fmts = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M",
        "%a %b %d %H:%M:%S %Y",
        "%a, %d %b %Y %H:%M:%S",
        "%a, %d %b %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except:
            try:
                return datetime.strptime(s[:len(fmt)], fmt)
            except:
                continue
    return None


def in_range(dt: Optional[datetime], t_start, t_end) -> bool:
    """嚴格模式：dt=None 視為不在範圍（有設定時間區間時使用）"""
    if dt is None:
        return False
    if t_start and dt < t_start:
        return False
    if t_end and dt > t_end:
        return False
    return True


def in_range_loose(dt: Optional[datetime], t_start, t_end) -> bool:
    """寬鬆模式：dt=None 視為在範圍（無時間區間時使用）"""
    if dt is None:
        return True
    if t_start and dt < t_start:
        return False
    if t_end and dt > t_end:
        return False
    return True


def make_session(extra_headers: dict = None) -> requests.Session:
    """建立帶基本 headers 的 requests Session"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Cache-Control":   "max-age=0",
    })
    if extra_headers:
        s.headers.update(extra_headers)
    return s
