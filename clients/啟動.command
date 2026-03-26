#!/bin/bash
# 雙擊啟動此客戶的監控系統
# 自動偵測此檔案所在的 client 資料夾

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT_DIR="$SCRIPT_DIR"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "=============================="
echo "  BrandPulse 監控系統啟動中"
echo "  客戶目錄：$CLIENT_DIR"
echo "=============================="

cd "$ROOT_DIR"
source .venv/bin/activate

# 讀取 port 設定
PORT=$(python3 -c "
import json
with open('$CLIENT_DIR/config.json') as f:
    d = json.load(f)
print(d.get('port', 5001))
" 2>/dev/null || echo "5001")

echo "Port: $PORT"
echo ""

python app.py --client "$CLIENT_DIR" --port "$PORT"

echo ""
echo "程式已結束，按任意鍵關閉..."
read -n 1
