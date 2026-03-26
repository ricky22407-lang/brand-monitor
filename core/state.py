"""
core/state.py
全域執行狀態，所有模組共用同一份 state。
"""

state = {
    "running":  False,
    "last_run": None,
    "articles": [],
    "stats":    {"total": 0, "positive": 0, "negative": 0, "neutral": 0},
    "log":      [],
}


def log(msg: str):
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    state["log"].append(entry)
    if len(state["log"]) > 300:
        state["log"] = state["log"][-300:]
    print(entry)


def reset():
    state["running"]  = False
    state["articles"] = []
    state["log"]      = []
    state["stats"]    = {"total": 0, "positive": 0, "negative": 0, "neutral": 0}
