"""
routes/settings.py
設定相關 API：黑名單、FB 社團、FB 粉專、客戶 config
"""

from flask import Blueprint, jsonify, request
import core.config as cfg_mod

bp = Blueprint("settings", __name__)


# ── 黑名單 ────────────────────────────────────

@bp.route("/api/blacklist", methods=["GET"])
def api_blacklist_get():
    return jsonify({"domains": cfg_mod.get_blacklist()})


@bp.route("/api/blacklist", methods=["POST"])
def api_blacklist_post():
    data    = request.json or {}
    domains = [d.strip().lower() for d in data.get("domains", []) if d.strip()]
    cfg_mod.save_blacklist(domains)
    return jsonify({"ok": True, "count": len(domains)})


# ── FB 社團 ───────────────────────────────────

@bp.route("/api/fb/groups", methods=["GET"])
def api_fb_groups_get():
    return jsonify({"groups": cfg_mod.get_fb_groups()})


@bp.route("/api/fb/groups", methods=["POST"])
def api_fb_groups_post():
    data   = request.json or {}
    groups = [u.strip() for u in data.get("groups", []) if u.strip()]
    cfg_mod.save_fb_groups(groups)
    return jsonify({"ok": True, "count": len(groups)})


# ── FB 粉專 ───────────────────────────────────

@bp.route("/api/fb/pages", methods=["GET"])
def api_fb_pages_get():
    return jsonify({"pages": cfg_mod.get_fb_pages()})


@bp.route("/api/fb/pages", methods=["POST"])
def api_fb_pages_post():
    data  = request.json or {}
    pages = [u.strip() for u in data.get("pages", []) if u.strip()]
    cfg_mod.save_fb_pages(pages)
    return jsonify({"ok": True, "count": len(pages)})


# ── 客戶 config ───────────────────────────────

@bp.route("/api/config", methods=["GET"])
def api_config_get():
    return jsonify(cfg_mod.get_config())





# ── 客戶 config 儲存 ─────────────────────────

@bp.route("/api/config", methods=["POST"])
def api_config_save():
    import pathlib, json as _j
    data = request.json or {}
    path = str(pathlib.Path(cfg_mod.CLIENT_DIR) / "config.json")
    # 讀現有 config 再 merge，避免覆蓋掉 port/chrome_profile 等欄位
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = _j.load(f)
    except:
        existing = {}
    existing.update({
        "brand_name":       data.get("brand_name",       existing.get("brand_name", "")),
        "keyword_rules":    data.get("keyword_rules",    existing.get("keyword_rules", "")),
        "ptt_boards":       data.get("ptt_boards",       existing.get("ptt_boards", [])),
        "dcard_boards":     data.get("dcard_boards",     existing.get("dcard_boards", [])),
        "mobile01_ids":     data.get("mobile01_ids",     existing.get("mobile01_ids", {})),
        "threads_kw":       data.get("threads_kw",       existing.get("threads_kw", [])),
        "news_keywords":    data.get("news_keywords",    existing.get("news_keywords", [])),
        "include_comments": data.get("include_comments", existing.get("include_comments", False)),
        "comment_pages":    data.get("comment_pages",    existing.get("comment_pages", 5)),
        "fb_keywords":      data.get("fb_keywords",      existing.get("fb_keywords", "")),
    })
    with open(path, "w", encoding="utf-8") as f:
        _j.dump(existing, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


# ── FB Profile 狀態 ───────────────────────────

@bp.route("/api/fb/profile/status", methods=["GET"])
def api_fb_profile_status():
    try:
        from crawlers.phase2.fb_crawler import check_profile_available
        return jsonify(check_profile_available())
    except Exception as e:
        return jsonify({"available": False, "message": str(e)})


# ── FB Cookie 管理 ────────────────────────────

def _cookie_path():
    """Cookie 存在客戶資料夾，重開機不消失"""
    import pathlib
    return str(pathlib.Path(cfg_mod.CLIENT_DIR) / "fb_cookies.json")

@bp.route("/api/fb/cookie/status", methods=["GET"])
def api_fb_cookie_status():
    import json as _j, pathlib
    try:
        with open(_cookie_path()) as f:
            cookies = _j.load(f)
        if cookies.get("c_user") and cookies.get("xs"):
            return jsonify({"valid": True,  "message": f"Cookie 有效（帳號 {cookies.get('c_user','')}）"})
        return jsonify({"valid": False, "message": "Cookie 不完整，缺少登入憑證"})
    except:
        return jsonify({"valid": False, "message": "尚未設定 Cookie"})


@bp.route("/api/fb/cookie", methods=["POST"])
def api_fb_cookie_save():
    import json as _j
    data = request.json or {}
    cookies_raw = data.get("cookies", [])

    if not cookies_raw:
        return jsonify({"ok": False, "error": "Cookie 內容為空"}), 400

    # 支援兩種格式：list（Cookie-Editor 匯出）或 dict
    if isinstance(cookies_raw, list):
        cookie_dict = {c["name"]: c["value"] for c in cookies_raw if "name" in c and "value" in c}
    elif isinstance(cookies_raw, dict):
        cookie_dict = cookies_raw
    else:
        return jsonify({"ok": False, "error": "格式不正確"}), 400

    if not cookie_dict.get("c_user"):
        return jsonify({"ok": False, "error": "缺少 c_user，請確認已登入 Facebook 再匯出"}), 400

    with open(_cookie_path(), "w", encoding="utf-8") as f:
        _j.dump(cookie_dict, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "count": len(cookie_dict)})
