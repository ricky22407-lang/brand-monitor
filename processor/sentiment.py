"""
processor/sentiment.py

使用 Claude API 對文章進行情緒分析，回傳：
  - label:   "positive" | "negative" | "neutral"
  - score:   0.0 ~ 1.0（對應 label 的信心度）
  - summary: 一句話摘要（中文）
  - reason:  情緒判斷理由（給客戶看的說明）

支援：
  - 單篇分析  analyze()
  - 批次分析  analyze_batch()  ← 自動分批，避免超出 rate limit
  - 結果快取  _cache           ← 同一篇文章不重複呼叫 API

使用範例：
    import asyncio
    from processor.sentiment import SentimentAnalyzer

    analyzer = SentimentAnalyzer(api_key="sk-ant-xxx")
    result = asyncio.run(analyzer.analyze("Ford Focus 變速箱故障，超傻眼"))
    print(result.label, result.score, result.summary)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional
import anthropic


# ──────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────

@dataclass
class SentimentResult:
    label:   str            # "positive" | "negative" | "neutral"
    score:   float          # 0.0 ~ 1.0
    summary: str            # 一句話摘要
    reason:  str            # 情緒判斷理由
    source:  str = ""       # 來源平台（PTT / Dcard / ...）
    url:     str = ""       # 原文連結
    cached:  bool = False   # 是否從快取拿到的


@dataclass
class BatchResult:
    total:    int
    positive: int
    negative: int
    neutral:  int
    items:    list[SentimentResult] = field(default_factory=list)

    @property
    def positive_pct(self) -> float:
        return round(self.positive / self.total * 100, 1) if self.total else 0.0

    @property
    def negative_pct(self) -> float:
        return round(self.negative / self.total * 100, 1) if self.total else 0.0


# ──────────────────────────────────────────────
# 主類別
# ──────────────────────────────────────────────

class SentimentAnalyzer:
    """
    Args:
        api_key:     Anthropic API key，預設讀取環境變數 ANTHROPIC_API_KEY
        model:       使用的模型，預設 claude-haiku-3（速度快、成本低）
        brand_hint:  品牌名稱提示，讓模型更準確地判斷情緒對象
                     例如 "Ford Focus" → 只判斷針對 Ford 的情緒，忽略無關內容
        batch_size:  批次大小，避免太快觸發 rate limit，預設 5
        cache:       是否啟用記憶體快取（同一篇文章不重複 API 呼叫）
    """

    SYSTEM_PROMPT = """你是品牌輿情分析專家，專門分析台灣繁體中文社群的品牌相關討論。

分析規則：
1. 只判斷作者對「目標品牌」的情緒，忽略文章中與品牌無關的情緒
2. 如果文章只是陳述事實、無明顯情緒，判定為 neutral
3. 混合情緒時，以「主要情緒」為主，次要情緒影響 score

必須以 JSON 格式回傳，不要有任何其他文字：
{
  "label": "positive" | "negative" | "neutral",
  "score": 0.0 到 1.0 之間的數字（代表對 label 的信心度）,
  "summary": "一句話摘要，15字以內，繁體中文",
  "reason": "情緒判斷理由，30字以內，繁體中文"
}"""

    def __init__(
        self,
        api_key:    str | None = None,
        model:      str = "claude-haiku-4-5-20251001",
        brand_hint: str = "",
        batch_size: int = 5,
        cache:      bool = True,
    ):
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        self.model      = model
        self.brand_hint = brand_hint
        self.batch_size = batch_size
        self._cache: dict[str, SentimentResult] = {} if cache else None

    # ── 單篇分析 ─────────────────────────────

    async def analyze(
        self,
        text:   str,
        source: str = "",
        url:    str = "",
    ) -> SentimentResult:
        """
        對單篇文章進行情緒分析。

        Args:
            text:   文章內容（標題 + 內文合併）
            source: 來源平台名稱，例如 "PTT"
            url:    原文連結

        Returns:
            SentimentResult
        """
        if not text.strip():
            return SentimentResult(
                label="neutral", score=0.5,
                summary="內容為空", reason="無文字內容可分析",
                source=source, url=url,
            )

        # 快取檢查
        cache_key = self._make_key(text)
        if self._cache is not None and cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.cached = True
            return cached

        # 組合 prompt
        brand_note = f"目標品牌：{self.brand_hint}\n\n" if self.brand_hint else ""
        user_message = f"{brand_note}請分析以下文章對品牌的情緒：\n\n{text[:1500]}"
        # 限制 1500 字，避免超出 context，且大部分貼文不超過這個長度

        try:
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=self.model,
                max_tokens=256,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            raw = response.content[0].text.strip()
            data = self._parse_json(raw)

            result = SentimentResult(
                label   = data.get("label",   "neutral"),
                score   = float(data.get("score",   0.5)),
                summary = data.get("summary", ""),
                reason  = data.get("reason",  ""),
                source  = source,
                url     = url,
                cached  = False,
            )

        except Exception as e:
            # API 失敗時回傳 neutral，不中斷整個批次
            result = SentimentResult(
                label="neutral", score=0.5,
                summary="分析失敗", reason=f"API 錯誤：{str(e)[:50]}",
                source=source, url=url,
            )

        # 存入快取
        if self._cache is not None:
            self._cache[cache_key] = result

        return result

    # ── 批次分析 ─────────────────────────────

    async def analyze_batch(
        self,
        items: list[dict],
        text_fields:   list[str] = None,
        source_field:  str = "source",
        url_field:     str = "url",
        delay_seconds: float = 0.5,
    ) -> BatchResult:
        """
        批次分析爬蟲回傳的 list[dict]，自動分批並加入延遲。

        Args:
            items:         爬蟲回傳的資料清單（已通過 KeywordFilter）
            text_fields:   要合併成分析文字的欄位，預設 ["title", "content"]
            source_field:  來源欄位名稱
            url_field:     連結欄位名稱
            delay_seconds: 每批之間的等待秒數，避免 rate limit

        Returns:
            BatchResult（包含統計數字 + 每篇的 SentimentResult）
        """
        if text_fields is None:
            text_fields = ["title", "content"]

        results = []
        batches = [items[i:i+self.batch_size] for i in range(0, len(items), self.batch_size)]

        for batch_idx, batch in enumerate(batches):
            tasks = []
            for item in batch:
                text   = " ".join(str(item.get(f, "")) for f in text_fields)
                source = str(item.get(source_field, ""))
                url    = str(item.get(url_field, ""))
                tasks.append(self.analyze(text, source=source, url=url))

            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)

            # 最後一批不需要等待
            if batch_idx < len(batches) - 1:
                await asyncio.sleep(delay_seconds)

        # 統計
        pos = sum(1 for r in results if r.label == "positive")
        neg = sum(1 for r in results if r.label == "negative")
        neu = sum(1 for r in results if r.label == "neutral")

        return BatchResult(
            total=len(results),
            positive=pos,
            negative=neg,
            neutral=neu,
            items=results,
        )

    # ── 工具方法 ──────────────────────────────

    @staticmethod
    def _make_key(text: str) -> str:
        """用 MD5 作為快取 key，避免重複分析相同文章。"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """
        解析 Claude 回傳的 JSON，容錯處理常見格式問題。
        """
        # 去除 markdown code block
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 找出第一個 { } 之間的內容
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(raw[start:end])
            return {}

    def clear_cache(self):
        """清除記憶體快取。"""
        if self._cache is not None:
            self._cache.clear()

    def __repr__(self) -> str:
        cached = len(self._cache) if self._cache is not None else "disabled"
        return f"SentimentAnalyzer(model={self.model!r}, brand={self.brand_hint!r}, cached={cached})"


# ──────────────────────────────────────────────
# 快速測試（直接執行此檔案時）
# ──────────────────────────────────────────────

async def _test():
    analyzer = SentimentAnalyzer(brand_hint="Ford Focus")

    test_cases = [
        "Ford Focus 開了三年沒什麼問題，油耗也不錯，整體很滿意",
        "Ford Focus 變速箱突然頓挫，送廠才一週又出現同樣問題，服務態度也很差",
        "Ford 宣布 Focus 電動版將於下半年發表，預計售價 120 萬起",
    ]

    print("=" * 50)
    for text in test_cases:
        result = await analyzer.analyze(text)
        icon = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(result.label, "❓")
        print(f"{icon} [{result.label.upper()} {result.score:.0%}] {result.summary}")
        print(f"   理由：{result.reason}")
        print(f"   原文：{text[:40]}...")
        print()
    print("=" * 50)
    print(analyzer)


if __name__ == "__main__":
    asyncio.run(_test())
