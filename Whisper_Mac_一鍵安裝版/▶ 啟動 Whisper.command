#!/bin/bash
cd "$(dirname "$0")"
/bin/bash ./_internal/setup_and_run_mac.sh "$@"
EXIT_CODE=$?
if [[ "$EXIT_CODE" -ne 0 ]]; then
  echo ""
  echo "尚未完成。請確認網路與安裝權限，再雙擊本啟動檔重試；紀錄位置見上方。"
  read -n 1 -s -r -p "按任意鍵關閉..."
  echo ""
fi
exit "$EXIT_CODE"
