#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate

# 啟動 Flask（背景）
python app.py &
FLASK_PID=$!

# 等待 Flask 啟動
sleep 2

# 用 Safari 開啟介面（不干擾 Chrome）
open -a Safari "http://127.0.0.1:5001"

echo "BrandPulse 已啟動（PID: $FLASK_PID）"
echo "介面：http://127.0.0.1:5001"
echo "關閉此視窗不會停止程式，如需停止請執行：pkill -f 'python app.py'"

# 等待程式結束
wait $FLASK_PID
