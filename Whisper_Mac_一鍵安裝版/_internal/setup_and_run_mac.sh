#!/bin/bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DATA_DIR="$HOME/Library/Application Support/WhisperGUI-SubtitlePreview"
VENV_DIR="$APP_DATA_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
MODELS_DIR="$APP_DATA_DIR/models"
mkdir -p "$APP_DATA_DIR/logs"
LOG_FILE="$APP_DATA_DIR/logs/last-launch.log"
exec > >(tee "$LOG_FILE") 2>&1
trap 'echo "準備未完成。請確認網路、磁碟空間與公司安裝權限，再雙擊啟動檔重試。"; echo "紀錄位置：$LOG_FILE"' ERR
CURRENT_VERSION="$(<"$SCRIPT_DIR/version.txt")"
export WHISPER_PREVIEW=1 WHISPER_LOCAL_ONLY=1
export WHISPER_MODEL_DIR="$MODELS_DIR/original"
export WHISPER_FASTER_MODEL_DIR="$MODELS_DIR/faster-small"
export WHISPER_APP_DATA_DIR="$APP_DATA_DIR"
export HF_HUB_DISABLE_TELEMETRY=1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "字幕排版試用版：首次準備需要網路；您的音訊與字幕不會上傳。"
echo "安裝位置與正式版分開。請保留解壓後的整個資料夾。"
echo "紀錄位置：$LOG_FILE"
if ! command -v brew >/dev/null 2>&1; then
  echo "[1/3] 準備系統工具。Homebrew 可能要求電腦登入密碼（輸入時不顯示字元）。"
  BREW_INSTALL_SCRIPT="$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  /bin/bash -c "$BREW_INSTALL_SCRIPT"
fi
for formula in python@3.12 python-tk@3.12 ffmpeg; do
  if ! brew list --versions "$formula" >/dev/null 2>&1; then brew install "$formula"; fi
done
ffmpeg -version >/dev/null
ffprobe -version >/dev/null
BASE_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
if [[ -x "$VENV_PYTHON" ]] && ! "$VENV_PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
  echo "保留舊的試用環境備份，重新建立可用環境。"
  mv "$VENV_DIR" "$APP_DATA_DIR/venv-backup-$(date +%Y%m%d%H%M%S)-$$"
fi
if [[ ! -x "$VENV_PYTHON" ]]; then "$BASE_PYTHON" -m venv "$VENV_DIR"; fi
INSTALLED_VERSION=""
if [[ -f "$VENV_DIR/.installed_version" ]]; then INSTALLED_VERSION="$(<"$VENV_DIR/.installed_version")"; fi
if [[ "$INSTALLED_VERSION" != "$CURRENT_VERSION" ]] || ! "$VENV_PYTHON" -c 'import faster_whisper, opencc, tkinter, pip_system_certs' >/dev/null 2>&1; then
  echo "[2/3] 準備轉錄程式，下載較大，請保持網路連線。"
  "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
  "$VENV_PYTHON" -m pip install --only-binary=:all: -r "$SCRIPT_DIR/requirements-mac.txt"
  "$VENV_PYTHON" -c 'import faster_whisper, opencc, tkinter, pip_system_certs'
fi
echo "[3/3] 驗證並準備本機通用語音模型。"
"$VENV_PYTHON" "$SCRIPT_DIR/download_model.py" small --output "$MODELS_DIR"
printf '%s\n' "$CURRENT_VERSION" > "$VENV_DIR/.installed_version"
export HF_HUB_OFFLINE=1
echo "準備完成，開啟字幕工具。"
"$VENV_PYTHON" "$SCRIPT_DIR/whisper_gui_mac.py"
