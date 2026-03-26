"""
app.py — BrandPulse 主程式
職責：Flask 初始化、Blueprint 註冊、啟動
所有業務邏輯都在 core/ 和 routes/ 裡
"""

import argparse
import pathlib
import threading
import webbrowser
import time
import os

from dotenv import load_dotenv
from flask import Flask

load_dotenv()

# ── 解析啟動參數 ──────────────────────────────
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--client", default=".", help="客戶資料目錄")
parser.add_argument("--port",   default="5001", type=int)
args, _ = parser.parse_known_args()

APP_DIR    = pathlib.Path(__file__).parent.resolve()
CLIENT_DIR = str(pathlib.Path(args.client).resolve())
PORT       = args.port

# ── 初始化客戶設定 ────────────────────────────
import core.config as cfg_mod
cfg_mod.init(CLIENT_DIR, str(APP_DIR))

print(f"[BrandPulse] 客戶目錄：{CLIENT_DIR}")
print(f"[BrandPulse] Port：{PORT}")

# ── Flask 初始化 ──────────────────────────────
app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
)

# ── 註冊 Blueprints ───────────────────────────
from routes.monitor  import bp as monitor_bp
from routes.clients  import bp as clients_bp
from routes.settings import bp as settings_bp
from routes.export   import bp as export_bp

app.register_blueprint(monitor_bp)
app.register_blueprint(clients_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(export_bp)

# ── 注入爬蟲依賴 ──────────────────────────────
# news.py 需要知道 blacklist 的路徑
import crawlers.news as news_mod
news_mod.BLACKLIST_PATH = str(pathlib.Path(CLIENT_DIR) / "blacklist.json")

# fb_crawler cookie 存在客戶資料夾（重開機不會消失）
try:
    import crawlers.phase2.fb_crawler as fb_mod
    fb_mod.COOKIES_PATH = str(pathlib.Path(CLIENT_DIR) / "fb_cookies.json")
except:
    pass

# ── 啟動 ──────────────────────────────────────
if __name__ == "__main__":
    def open_browser():
        time.sleep(1.5)
        # 只用 Safari 開介面，不開 Chrome（Chrome 只在 FB 爬蟲時才用）
        import subprocess
        subprocess.Popen(["open", "-a", "Safari", f"http://127.0.0.1:{PORT}"])

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"\n🚀 BrandPulse 啟動中（port {PORT}）...")
    print(f"   手動前往：http://127.0.0.1:{PORT}\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)
