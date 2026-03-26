from flask import Blueprint, jsonify, request
import threading
from core.state   import state
from core.monitor import run_monitor

bp = Blueprint("monitor", __name__)

@bp.route("/api/status")
def api_status():
    art_n = sum(1 for a in state["articles"] if a.get("type") == "article")
    cmt_n = sum(1 for a in state["articles"] if a.get("type") == "comment")
    return jsonify({
        "running":  state["running"],
        "last_run": state["last_run"],
        "stats":    {**state["stats"], "article_count": art_n, "comment_count": cmt_n},
        "log":      state["log"][-30:],
        "count":    len(state["articles"]),
    })

@bp.route("/api/articles")
def api_articles():
    sentiment = request.args.get("sentiment", "all")
    kind      = request.args.get("kind",      "all")
    source    = request.args.get("source",    "all")
    items     = state["articles"]
    if sentiment != "all":
        items = [a for a in items if a.get("sentiment") == sentiment]
    if kind != "all":
        items = [a for a in items if a.get("type") == kind]
    if source != "all":
        items = [a for a in items if a.get("source") == source]
    return jsonify(items)

@bp.route("/api/sources")
def api_sources():
    sources = sorted(set(a.get("source","") for a in state["articles"] if a.get("source")))
    return jsonify(sources)

@bp.route("/api/run", methods=["POST"])
def api_run():
    if state["running"]:
        return jsonify({"error": "執行中"}), 400
    cfg = request.json or {}
    threading.Thread(target=run_monitor, args=(cfg,), daemon=True).start()
    return jsonify({"status": "started"})


@bp.route('/api/stop', methods=['POST'])
def api_stop():
    try:
        import crawlers.phase2.fb_crawler as fb_mod
        fb_mod.request_stop()
    except Exception as e:
        print(f"[STOP] {e}")
    from flask import jsonify
    return jsonify({"status": "stop_requested", "message": "⛔ 停止訊號已送出"})
