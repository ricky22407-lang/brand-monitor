"""
core/monitor.py
監控主流程：爬蟲 → 關鍵字過濾 → 情緒分析
"""

import os
import asyncio
from datetime import datetime

from core.state  import state, log
from core.utils  import parse_dt, in_range, in_range_loose
from core.config import get_blacklist


def run_monitor(cfg: dict):
    """
    主監控流程，在獨立執行緒中執行。
    cfg 從前端 /api/run 的 POST body 取得。
    """
    from core.state import reset
    reset()
    state["running"] = True

    brand_name       = cfg.get("brand_name", "")
    keyword_rules    = cfg.get("keyword_rules", "")
    ptt_boards       = cfg.get("ptt_boards", [])
    dcard_boards     = cfg.get("dcard_boards", [])
    mobile01_ids     = cfg.get("mobile01_ids", {})
    news_keywords    = cfg.get("news_keywords", [])
    threads_kw       = cfg.get("threads_kw", [])
    include_comments = cfg.get("include_comments", False)
    comment_pages    = int(cfg.get("comment_pages", 5))
    scan_facebook    = cfg.get("scan_facebook", True)
    fb_keywords_raw  = cfg.get("fb_keywords", "").strip()
    time_start_str   = cfg.get("time_start", "")
    time_end_str     = cfg.get("time_end", "")

    t_start = parse_dt(time_start_str)
    t_end   = parse_dt(time_end_str)
    has_tr  = bool(t_start or t_end)

    if has_tr:
        log(f"時間區間：{t_start.strftime('%Y-%m-%d %H:%M') if t_start else '不限'} ～ {t_end.strftime('%Y-%m-%d %H:%M') if t_end else '現在'}")
    else:
        log("時間區間：不限")
    log(f"開始監控：{brand_name}")

    try:
        from crawlers.ptt      import fetch_ptt
        from crawlers.dcard    import fetch_dcard
        from crawlers.mobile01 import fetch_mobile01
        from crawlers.news     import NewsCrawler
        from crawlers.threads  import ThreadsCrawler
        from processor.keyword_filter import KeywordFilter
        from processor.sentiment      import SentimentAnalyzer

        kf       = KeywordFilter.from_ui_string(keyword_rules)
        checker  = in_range if has_tr else in_range_loose
        all_items = []

        # ── PTT ───────────────────────────────────────
        for board in ptt_boards:
            try:
                log(f"PTT {board} 掃描中...")
                cp = comment_pages if include_comments else 0
                arts, cmts = fetch_ptt(board, t_start, t_end, cp, has_tr)
                all_items.extend(arts)
                if include_comments:
                    all_items.extend(cmts)
                log(f"PTT {board}：文章 {len(arts)} 篇，留言 {len(cmts)} 則")
            except Exception as e:
                log(f"PTT {board} 失敗：{e}")

        # ── Dcard ─────────────────────────────────────
        for board in dcard_boards:
            try:
                log(f"Dcard {board} 掃描中...")
                cp = comment_pages if include_comments else 0
                arts, cmts = fetch_dcard(board, t_start, t_end, cp, has_tr)
                all_items.extend(arts)
                if include_comments:
                    all_items.extend(cmts)
                log(f"Dcard {board}：文章 {len(arts)} 篇，留言 {len(cmts)} 則")
            except Exception as e:
                log(f"Dcard {board} 失敗：{e}")

        # ── Mobile01 ──────────────────────────────────
        try:
            log("Mobile01 掃描中...")
            all_m01 = []
            for name, fid in mobile01_ids.items():
                arts = fetch_mobile01(name, fid, t_start, t_end, has_tr, pages=2)
                all_m01.extend(arts)
                log(f"Mobile01 {name}：{len(arts)} 篇")
            all_items.extend(all_m01)
            log(f"Mobile01：共 {len(all_m01)} 篇")
        except Exception as e:
            log(f"Mobile01 失敗：{e}")

        # ── News ──────────────────────────────────────
        try:
            log("新聞掃描中...")
            arts = NewsCrawler(keywords=news_keywords).fetch_all(limit=30)
            arts = [a for a in arts if checker(parse_dt(a.get("timestamp", "")), t_start, t_end)]
            all_items.extend([{**a, "type": "article", "parent_title": ""} for a in arts])
            log(f"新聞：{len(arts)} 篇")
        except Exception as e:
            log(f"新聞失敗：{e}")

        # ── Threads ───────────────────────────────────
        try:
            log("Threads 掃描中...")
            arts = ThreadsCrawler(keywords=threads_kw).fetch_all(limit=30)
            arts = [a for a in arts if checker(parse_dt(a.get("timestamp", "")), t_start, t_end)]
            all_items.extend([{**a, "type": "article", "parent_title": ""} for a in arts])
            log(f"Threads：{len(arts)} 則")
        except Exception as e:
            log(f"Threads 失敗：{e}")

        log(f"爬蟲完成，共 {len(all_items)} 筆原始資料")

        # ── 關鍵字過濾 ────────────────────────────────
        filtered     = []
        missed_sample = []
        for item in all_items:
            title   = (item.get("title")   or "").strip()
            content = (item.get("content") or "").strip()
            text    = f"{title} {content}".strip()
            if not text:
                missed_sample.append(f"[空內容] {item.get('source')} {item.get('board')}")
                continue
            if kf.match(text).matched:
                filtered.append(item)
            elif len(missed_sample) < 5:
                missed_sample.append(f"{item.get('source')}|{title[:25]}")

        # 統計各來源
        source_stats = {}
        for item in all_items:
            src = item.get("source", "?")
            source_stats.setdefault(src, {"total": 0, "passed": 0})
            source_stats[src]["total"] += 1
        for item in filtered:
            source_stats.get(item.get("source", "?"), {})["passed"] = \
                source_stats.get(item.get("source", "?"), {}).get("passed", 0) + 1

        log(f"關鍵字過濾後：{len(filtered)} 筆（原始 {len(all_items)} 筆）")
        for src, s in source_stats.items():
            log(f"  {src}：{s.get('passed',0)}/{s['total']} 筆通過")
        if missed_sample:
            log(f"未命中樣本：{' / '.join(missed_sample[:5])}")

        # ── Facebook ──────────────────────────────
        import core.config as _cfg
        log(f"CLIENT_DIR = {_cfg.CLIENT_DIR}")
        fb_group_urls = _cfg.get_fb_groups()
        fb_page_urls  = _cfg.get_fb_pages()
        log(f"FB社團清單：{fb_group_urls}")
        log(f"FB粉專清單：{fb_page_urls}")

        if scan_facebook and (fb_group_urls or fb_page_urls):
            log("Facebook 掃描中...")
            try:
                from crawlers.phase2.fb_crawler import (
                    fetch_fb_all, check_profile_available
                )
                # FB 獨立關鍵字：有填用自己的，空白 fallback 用主關鍵字
                if fb_keywords_raw:
                    fb_kf = KeywordFilter.from_ui_string(fb_keywords_raw)
                    log(f"FB 使用獨立關鍵字：{fb_keywords_raw[:50]}")
                else:
                    fb_kf = kf
                    log("FB 沿用主關鍵字規則")

                import core.config as _dbg
                log(f"FB debug CLIENT_DIR: {_dbg.CLIENT_DIR}")
                from crawlers.phase2.fb_crawler import _get_cookies_path
                log(f"FB debug cookie path: {_get_cookies_path()}")
                profile_status = check_profile_available()
                if not profile_status["available"]:
                    log(f"⚠️ FB 跳過：{profile_status['message']}")
                else:
                    fb_g_arts, fb_g_cmts, fb_p_arts = fetch_fb_all(
                        fb_group_urls, fb_page_urls, fb_kf,
                        t_start, t_end, has_tr, include_comments
                    )
                    filtered.extend(fb_g_arts)
                    filtered.extend(fb_g_cmts)
                    filtered.extend(fb_p_arts)
                    log(f"FB社團：貼文 {len(fb_g_arts)}，留言 {len(fb_g_cmts)}")
                    log(f"FB粉專：{len(fb_p_arts)} 篇")
            except Exception as e:
                log(f"FB 失敗：{e}")


        if not filtered:
            log("沒有符合條件的資料")
            state["running"] = False
            return

        # ── 情緒分析 ──────────────────────────────────
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key or "請填入" in api_key:
            log("未設定 API Key，跳過情緒分析")
            for a in filtered:
                a.update({"sentiment": "neutral", "sentiment_score": 0.5, "sentiment_summary": "未分析"})
        else:
            log(f"情緒分析中（{len(filtered)} 筆）...")
            analyzer = SentimentAnalyzer(api_key=api_key, brand_hint=brand_name)

            async def _analyze():
                return await analyzer.analyze_batch(filtered)

            batch = asyncio.run(_analyze())
            for item, result in zip(filtered, batch.items):
                item.update({
                    "sentiment":         result.label,
                    "sentiment_score":   round(result.score, 2),
                    "sentiment_summary": result.summary,
                })
            state["stats"] = {
                "total":    batch.total,
                "positive": batch.positive,
                "negative": batch.negative,
                "neutral":  batch.neutral,
            }
            log(f"分析完成：正面 {batch.positive} / 負面 {batch.negative} / 中性 {batch.neutral}")


        state["articles"] = filtered
        state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        art_n = sum(1 for a in filtered if a.get("type") == "article")
        cmt_n = sum(1 for a in filtered if a.get("type") == "comment")
        log(f"✅ 完成：文章 {art_n} 篇，留言 {cmt_n} 則，共 {len(filtered)} 筆")

    except Exception as e:
        log(f"❌ 錯誤：{e}")
        import traceback
        log(traceback.format_exc()[:300])
    finally:
        state["running"] = False
