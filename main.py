"""
main.py

品牌輿情監控系統主程式。
直接執行會立即跑一次完整監控流程。
"""

import os
import sys
from dotenv import load_dotenv

# 讀取 .env
load_dotenv()

from crawlers.ptt      import PttCrawler
from crawlers.dcard    import DcardCrawler
from crawlers.mobile01 import Mobile01Crawler
from crawlers.news     import NewsCrawler
from crawlers.threads  import ThreadsCrawler
from processor.keyword_filter import KeywordFilter
from processor.sentiment      import SentimentAnalyzer
import asyncio

# ──────────────────────────────────────────────
# 設定區（之後移到 config.py）
# ──────────────────────────────────────────────

BRAND_NAME = "Ford Focus"

# 關鍵字規則（UI 字串格式）
KEYWORD_RULES = """
ford
focus
ford+focus
ford or focus
福特
福特+focus
"""

# 各爬蟲設定
PTT_BOARDS    = ["car", "gossiping"]
DCARD_BOARDS  = ["car"]
MOBILE01_IDS  = {"汽車": 317}
NEWS_KEYWORDS = ["Ford Focus", "福特 Focus"]
THREADS_KW    = ["Ford Focus", "福特"]


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

async def run():
    print("\n" + "=" * 50)
    print(f"  品牌輿情監控：{BRAND_NAME}")
    print("=" * 50 + "\n")

    # 1. 爬蟲
    print("【第一步】爬取各平台資料...")
    all_articles = []

    crawlers = [
        ("PTT",      lambda: PttCrawler(boards=PTT_BOARDS).fetch_all(pages=1)),
        ("Dcard",    lambda: DcardCrawler(boards=DCARD_BOARDS).fetch_all(limit=20)),
        ("Mobile01", lambda: Mobile01Crawler(forum_ids=MOBILE01_IDS).fetch_all(pages=1)),
        ("News",     lambda: NewsCrawler(keywords=NEWS_KEYWORDS).fetch_all(limit=10)),
        ("Threads",  lambda: ThreadsCrawler(keywords=THREADS_KW).fetch_all(limit=20)),
    ]

    for name, fn in crawlers:
        try:
            articles = fn()
            all_articles.extend(articles)
            print(f"  {name}: {len(articles)} 篇")
        except Exception as e:
            print(f"  {name}: 失敗 ({e})")

    print(f"\n  爬蟲完成，共 {len(all_articles)} 篇原始資料\n")

    # 2. 關鍵字過濾
    print("【第二步】關鍵字過濾...")
    kf = KeywordFilter.from_ui_string(KEYWORD_RULES)
    filtered = kf.match_batch(all_articles)
    print(f"  過濾後剩 {len(filtered)} 篇相關文章\n")

    if not filtered:
        print("  沒有找到相關文章，結束。")
        return

    # 3. 情緒分析
    print("【第三步】情緒分析...")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or "請填入" in api_key:
        print("  ⚠️  未設定 ANTHROPIC_API_KEY，跳過情緒分析")
        for a in filtered:
            a["sentiment"] = "neutral"
            a["sentiment_score"] = 0.5
            a["sentiment_summary"] = "未分析"
    else:
        analyzer = SentimentAnalyzer(api_key=api_key, brand_hint=BRAND_NAME)
        batch = await analyzer.analyze_batch(filtered)
        for item, result in zip(filtered, batch.items):
            item["sentiment"]         = result.label
            item["sentiment_score"]   = result.score
            item["sentiment_summary"] = result.summary

        print(f"  正面：{batch.positive} 篇（{batch.positive_pct}%）")
        print(f"  負面：{batch.negative} 篇（{batch.negative_pct}%）")
        print(f"  中性：{batch.neutral} 篇\n")

    # 4. 輸出結果
    print("【第四步】輸出結果...\n")
    print("-" * 50)
    for a in filtered[:5]:  # 先印前5篇
        sent_icon = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            a.get("sentiment", "neutral"), "⚪"
        )
        print(f"{sent_icon} [{a['source']}] {a['title'][:40]}")
        print(f"   {a.get('sentiment_summary', '')}  {a['url']}")
        print()

    if len(filtered) > 5:
        print(f"  ... 以及其他 {len(filtered)-5} 篇")

    print("-" * 50)
    print(f"\n✅ 完成！共分析 {len(filtered)} 篇文章")


if __name__ == "__main__":
    asyncio.run(run())
