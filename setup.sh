#!/bin/bash
set -e
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${NC}"; }
info() { echo -e "${YELLOW}ℹ️  $1${NC}"; }

cd "$(dirname "$0")"

info "建立虛擬環境..."
python3.11 -m venv .venv
source .venv/bin/activate
ok "虛擬環境就緒"

info "安裝套件..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
ok "套件安裝完成"

info "安裝 Playwright 瀏覽器..."
python3 -m playwright install chromium
ok "Playwright 就緒"

info "建立必要資料夾..."
mkdir -p clients exports

if [ ! -f ".env" ]; then
  cat > .env << 'ENVEOF'
ANTHROPIC_API_KEY=sk-ant-請填入你的API金鑰
ENVEOF
  ok ".env 建立完成（請填入 API Key）"
fi

echo ""
echo -e "${GREEN}=============================="
echo -e "  安裝完成！"
echo -e "==============================${NC}"
echo ""
echo "啟動方式：雙擊 啟動監控.command"
echo "（首次使用需先 chmod +x 啟動監控.command）"
