# 品牌輿情監控系統 — 專案說明

## 專案目的
幫助品牌客戶監控 PTT、Dcard、Mobile01、新聞、Threads 上的品牌聲量，
每天早上自動整理成報表寄給客戶。這是一個 Python 後端專案。

## 技術規格
- 語言：Python 3.11+
- 套件管理：pip + requirements.txt
- 資料庫：SQLite（輕量，不需要安裝額外服務）
- AI 情緒分析：Anthropic API（claude-haiku-4-5-20251001）
- 網頁爬蟲：requests + BeautifulSoup（公開版區）
- FB 模擬：Playwright（第二步，獨立模組）

## 資料夾結構與用途

```
brand-monitor/
├── crawlers/           爬蟲模組，每個來源一個獨立 .py 檔
│   ├── ptt.py          PTT 爬蟲
│   ├── dcard.py        Dcard 爬蟲
│   ├── mobile01.py     Mobile01 爬蟲
│   ├── news.py         新聞網站爬蟲
│   ├── threads.py      Threads 爬蟲
│   └── phase2/         FB 模組（獨立，第二步再開發）
│       ├── fb_pages.py
│       └── fb_groups.py
├── processor/          已完成，不要修改
│   ├── keyword_filter.py  關鍵字過濾（單詞/AND/OR）
│   └── sentiment.py       Claude API 情緒分析
├── reporter/           輸出模組
│   ├── dashboard.py    Flask/FastAPI 儀表板
│   ├── excel_export.py openpyxl 匯出
│   └── email_sender.py 寄信（smtplib 或 SendGrid）
├── database/
│   └── models.py       SQLite schema + 操作函式
├── main.py             主程式入口
├── scheduler.py        APScheduler 排程
└── config.py           設定檔（API key、排程時間等）
```

## 開發原則
1. 每個模組獨立，可以單獨執行測試
2. 每個爬蟲回傳統一格式的 list[dict]：
   {"title": str, "content": str, "url": str, "source": str, "timestamp": str}
3. crawlers/phase2/ 完全獨立，不得 import 第一步的任何模組
4. 所有 API key 從 config.py 或環境變數讀取，不寫死在程式碼裡
5. 錯誤要 try/catch，單一來源失敗不能讓整個程式崩潰

## 目前進度
- [x] processor/keyword_filter.py — 完成
- [x] processor/sentiment.py — 完成
- [ ] crawlers/ptt.py — 待開發
- [ ] crawlers/dcard.py — 待開發
- [ ] crawlers/mobile01.py — 待開發
- [ ] crawlers/news.py — 待開發
- [ ] crawlers/threads.py — 待開發
- [ ] database/models.py — 待開發
- [ ] reporter/excel_export.py — 待開發
- [ ] reporter/email_sender.py — 待開發
- [ ] main.py + scheduler.py — 待開發
- [ ] phase2/ FB 模組 — 第二步

## 給 Cowork 的指示
每次開始新任務時，請先閱讀這份文件。
開發新模組時，請參考 processor/ 裡已完成的程式碼風格。
每完成一個模組，請更新上方的「目前進度」清單。
