"""
processor/keyword_filter.py

支援三種關鍵字模式：
  - 單詞模式:  "ford"           → 文章包含 ford
  - AND 模式:  "ford+focus"     → 文章同時包含 ford 和 focus
  - OR  模式:  "ford|focus"     → 文章包含 ford 或 focus（任一）

使用範例：
    rules = [
        {"type": "single", "terms": ["ford"]},
        {"type": "and",    "terms": ["ford", "focus"]},
        {"type": "or",     "terms": ["ford", "focus"]},
    ]
    f = KeywordFilter(rules)
    result = f.match("我開了一台 Ford Focus 覺得很棒")
    # result.matched == True
    # result.matched_rules == [...]
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field


# ──────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────

@dataclass
class KeywordRule:
    """單一規則，由設定檔或 UI 傳入。"""
    type: str          # "single" | "and" | "or"
    terms: list[str]   # 關鍵字清單（已去除空白）

    def __post_init__(self):
        allowed = {"single", "and", "or"}
        if self.type not in allowed:
            raise ValueError(f"KeywordRule.type 必須是 {allowed}，收到：{self.type!r}")
        if not self.terms:
            raise ValueError("KeywordRule.terms 不能是空清單")
        # 統一小寫、去除空白
        self.terms = [t.strip().lower() for t in self.terms if t.strip()]


@dataclass
class MatchResult:
    """過濾結果，帶著命中的規則與關鍵字供 debug 使用。"""
    matched: bool
    matched_rules: list[dict] = field(default_factory=list)
    # 每個 dict: {"type": ..., "terms": [...], "hit_terms": [...]}


# ──────────────────────────────────────────────
# 主類別
# ──────────────────────────────────────────────

class KeywordFilter:
    """
    初始化後可對任意文章字串呼叫 match()。

    Args:
        rules: KeywordRule 的清單，或是 dict 清單（會自動轉換）。

    範例（dict 格式，方便從 JSON / DB 直接傳入）:
        filter = KeywordFilter([
            {"type": "single", "terms": ["ford"]},
            {"type": "and",    "terms": ["ford", "故障"]},
            {"type": "or",     "terms": ["試駕", "開箱", "評測"]},
        ])
    """

    def __init__(self, rules: list[KeywordRule | dict]):
        self.rules: list[KeywordRule] = []
        for r in rules:
            if isinstance(r, dict):
                self.rules.append(KeywordRule(**r))
            elif isinstance(r, KeywordRule):
                self.rules.append(r)
            else:
                raise TypeError(f"rules 元素必須是 KeywordRule 或 dict，收到：{type(r)}")

    # ── 核心方法 ──────────────────────────────

    def match(self, text: str) -> MatchResult:
        """
        對 text 執行所有規則，只要「任一規則命中」就回傳 matched=True。

        Args:
            text: 文章標題 + 內文的合併字串（呼叫端自行組合）

        Returns:
            MatchResult
        """
        if not text:
            return MatchResult(matched=False)

        normalized = text.lower()
        matched_rules = []

        for rule in self.rules:
            hit = self._evaluate(rule, normalized)
            if hit is not None:
                matched_rules.append(hit)

        return MatchResult(
            matched=len(matched_rules) > 0,
            matched_rules=matched_rules,
        )

    def match_batch(self, items: list[dict], text_fields: list[str] = None) -> list[dict]:
        """
        批次過濾，適合爬蟲回傳的 list[dict] 資料。

        Args:
            items:       爬蟲回傳的原始資料清單
            text_fields: 要合併比對的欄位名稱，預設 ["title", "content"]

        Returns:
            只保留命中的 item，並在每個 item 上加入 "_match" key。
        """
        if text_fields is None:
            text_fields = ["title", "content"]

        results = []
        for item in items:
            combined = " ".join(
                str(item.get(f, "")) for f in text_fields
            )
            result = self.match(combined)
            if result.matched:
                item["_match"] = result.matched_rules
                results.append(item)
        return results

    # ── 內部評估邏輯 ─────────────────────────

    def _evaluate(self, rule: KeywordRule, normalized_text: str) -> dict | None:
        """
        回傳命中資訊 dict，未命中回傳 None。
        使用 word-boundary 比對，避免 "ford" 命中 "afford"。
        """
        if rule.type == "single":
            term = rule.terms[0]
            if self._contains(normalized_text, term):
                return {"type": "single", "terms": rule.terms, "hit_terms": [term]}

        elif rule.type == "and":
            hit_terms = [t for t in rule.terms if self._contains(normalized_text, t)]
            if len(hit_terms) == len(rule.terms):
                return {"type": "and", "terms": rule.terms, "hit_terms": hit_terms}

        elif rule.type == "or":
            hit_terms = [t for t in rule.terms if self._contains(normalized_text, t)]
            if hit_terms:
                return {"type": "or", "terms": rule.terms, "hit_terms": hit_terms}

        return None

    @staticmethod
    def _contains(text: str, term: str) -> bool:
        """
        中英文混合友善的包含比對：
        - 英文：word boundary（避免 "ford" 命中 "afford"）
        - 中文：直接 substring（中文本來就以字為單位）
        """
        # 判斷是否含有英文字母
        if re.search(r"[a-zA-Z]", term):
            pattern = r"(?<![a-zA-Z])" + re.escape(term) + r"(?![a-zA-Z])"
            return bool(re.search(pattern, text, re.IGNORECASE))
        else:
            return term in text

    # ── 工具方法 ──────────────────────────────

    @classmethod
    def from_ui_string(cls, ui_input: str) -> "KeywordFilter":
        """
        從 UI 貼上的關鍵字字串建立 filter，方便快速測試。

        格式（每行一個規則）：
            ford                → single
            ford+focus          → and
            ford or focus       → or（空格 or 空格）
            ford|focus          → or（pipe 符號）

        範例：
            f = KeywordFilter.from_ui_string('''
                ford
                ford+focus
                ford or focus
                試駕|開箱|評測
            ''')
        """
        rules = []
        for line in ui_input.strip().splitlines():
            line = line.strip()
            if not line:
                continue

            if "+" in line:
                terms = [t.strip() for t in line.split("+") if t.strip()]
                rules.append({"type": "and", "terms": terms})
            elif " or " in line.lower():
                terms = [t.strip() for t in re.split(r"\s+or\s+", line, flags=re.IGNORECASE) if t.strip()]
                rules.append({"type": "or", "terms": terms})
            elif "|" in line:
                terms = [t.strip() for t in line.split("|") if t.strip()]
                rules.append({"type": "or", "terms": terms})
            else:
                rules.append({"type": "single", "terms": [line]})

        return cls(rules)

    def __repr__(self) -> str:
        return f"KeywordFilter({len(self.rules)} rules)"


# ──────────────────────────────────────────────
# 快速測試（直接執行此檔案時）
# ──────────────────────────────────────────────

if __name__ == "__main__":
    f = KeywordFilter.from_ui_string("""
        ford
        ford+focus
        ford or focus
        試駕|開箱|評測
        ford+故障
    """)

    test_cases = [
        ("我的 Ford Focus 很棒", True),
        ("這台 ford 開了三年沒問題", True),
        ("Ford Focus 變速箱故障", True),
        ("開箱新手機", True),
        ("今天天氣很好", False),
        ("afford 不起", False),   # 不應命中 "ford"
    ]

    print("=" * 50)
    for text, expected in test_cases:
        result = f.match(text)
        status = "✅" if result.matched == expected else "❌"
        print(f"{status} [{text}]")
        if result.matched:
            for rule in result.matched_rules:
                print(f"   命中規則: type={rule['type']}, hit={rule['hit_terms']}")
    print("=" * 50)
