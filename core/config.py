"""
core/config.py
客戶設定管理：讀取 config.json、fb_groups.json、fb_pages.json、blacklist.json
"""

import json
import os
import pathlib

# 由 app.py 啟動時設定
CLIENT_DIR   = "."
CLIENTS_BASE = ""


def init(client_dir: str, app_dir: str):
    """由 app.py 在啟動時呼叫，設定路徑"""
    global CLIENT_DIR, CLIENTS_BASE
    CLIENT_DIR   = str(pathlib.Path(client_dir).resolve())
    CLIENTS_BASE = str(pathlib.Path(app_dir) / "clients")
    pathlib.Path(CLIENTS_BASE).mkdir(exist_ok=True)


def _path(filename: str) -> str:
    return str(pathlib.Path(CLIENT_DIR) / filename)


def _read(filename: str, default):
    try:
        with open(_path(filename), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write(filename: str, data):
    with open(_path(filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 各設定檔 ─────────────────────────────────

def get_config() -> dict:
    return _read("config.json", {})


def get_blacklist() -> list:
    return _read("blacklist.json", {"domains": []}).get("domains", [])


def save_blacklist(domains: list):
    _write("blacklist.json", {"domains": sorted(set(domains))})


def get_fb_groups() -> list:
    return _read("fb_groups.json", {"groups": []}).get("groups", [])


def save_fb_groups(groups: list):
    _write("fb_groups.json", {"groups": groups})


def get_fb_pages() -> list:
    return _read("fb_pages.json", {"pages": []}).get("pages", [])


def save_fb_pages(pages: list):
    _write("fb_pages.json", {"pages": pages})


# ── 客戶列表管理 ─────────────────────────────

def list_clients() -> list:
    """掃描 clients/ 資料夾，回傳所有有效客戶"""
    clients = []
    base = pathlib.Path(CLIENTS_BASE)
    if not base.exists():
        return clients
    for d in sorted(base.iterdir()):
        if d.is_dir():
            cfg_path = d / "config.json"
            if cfg_path.exists():
                try:
                    with open(cfg_path, encoding="utf-8") as f:
                        cfg = json.load(f)
                    cfg["folder"] = d.name
                    clients.append(cfg)
                except Exception:
                    pass
    return clients


def create_client(folder: str, brand_name: str, port: int) -> dict:
    """
    建立新客戶資料夾與設定檔。
    回傳 {"ok": True} 或 {"ok": False, "error": "..."}
    """
    folder = folder.strip().replace(" ", "_")
    if not folder or not brand_name:
        return {"ok": False, "error": "缺少必填欄位"}

    client_path = pathlib.Path(CLIENTS_BASE) / folder

    # 如果已有完整設定，拒絕重建
    if (client_path / "config.json").exists():
        return {"ok": False, "error": f"客戶 '{folder}' 已存在"}

    # 建立資料夾
    client_path.mkdir(parents=True, exist_ok=True)

    # 寫入 config.json
    cfg = {
        "client_name":      folder,
        "brand_name":       brand_name,
        "keyword_rules":    "",
        "ptt_boards":       ["car"],
        "dcard_boards":     ["car"],
        "mobile01_ids":     {"汽車討論": 317},
        "threads_kw":       [],
        "news_keywords":    [],
        "include_comments": False,
        "comment_pages":    5,
        "port":             port,
        "chrome_profile":   ""
    }
    with open(client_path / "config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    # 寫入其他空設定
    defaults = {
        "fb_groups.json": {"groups": []},
        "fb_pages.json":  {"pages": []},
        "blacklist.json": {"domains": []},
    }
    for fname, default in defaults.items():
        fp = client_path / fname
        if not fp.exists():
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)

    return {"ok": True, "folder": folder}
