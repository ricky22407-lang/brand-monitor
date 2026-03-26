import pathlib
from flask import Blueprint, jsonify, render_template, request, redirect
import core.config as cfg_mod

bp = Blueprint("clients", __name__)

@bp.route("/")
def index():
    app_dir = str(pathlib.Path(__file__).parent.parent.resolve())
    default = str(pathlib.Path(app_dir).resolve())
    if cfg_mod.CLIENT_DIR != default:
        return render_template("dashboard.html")
    return render_template("selector.html")

@bp.route("/monitor")
def monitor_page():
    return render_template("dashboard.html")

@bp.route("/api/clients", methods=["GET"])
def api_clients_get():
    return jsonify(cfg_mod.list_clients())

@bp.route("/api/clients", methods=["POST"])
def api_clients_post():
    data   = request.json or {}
    folder = data.get("folder",     "").strip()
    brand  = data.get("brand_name", "").strip()
    port   = int(data.get("port", 5001))
    result = cfg_mod.create_client(folder, brand, port)
    if result["ok"]:
        return jsonify(result)
    return jsonify(result), 400

@bp.route("/launch")
def launch():
    """切換到指定客戶，更新 CLIENT_DIR 後導向監控介面"""
    folder      = request.args.get("client", "")
    client_path = str(pathlib.Path(cfg_mod.CLIENTS_BASE) / folder)
    # 直接切換客戶設定
    import os
    cfg_mod.CLIENT_DIR = str(pathlib.Path(client_path).resolve())
    # 更新 blacklist 路徑
    try:
        import crawlers.news as news_mod
        news_mod.BLACKLIST_PATH = str(pathlib.Path(client_path) / "blacklist.json")
    except:
        pass
    return redirect("/monitor")
