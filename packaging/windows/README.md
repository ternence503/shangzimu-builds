# 上字幕 Windows 原生完整封裝

狀態（2026-09-14）：GitHub Windows Server 2022 原生建置、實際 frozen 語音／SRT、Inno 安裝器及安裝已執行。移動至中文／空白路徑的 App 已通過真實系統防火牆連線前後對照與離線辨識。已安裝捷徑仍在複驗，並新增 PE 依賴稽核；**這不是乾淨 Windows 10/11、搜尋／重啟／SmartScreen 或最終交付完成的證明。**

## 決策

採 Windows x64 Python 3.12 + PyInstaller onedir，再用 Inno Setup 製作自包含安裝程式。使用者不用裝 Python、pip、FFmpeg 或另下載模型。安裝到 `%LOCALAPPDATA%\Programs\ShangZiMu`，建立開始選單「上字幕」；移走安裝來源仍可啟動。程式與模型和使用者進度分開，解除安裝不刪 AppData 進度。

不得以 Mac 產出的 ZIP 或 build 腳本宣稱 Windows 產品已完成。不能跨平台封裝 Windows 原生 DLL。首次下載第三方工具只屬建置者準備工作，不由 App 執行。

## 輸入與建置

先準備 Windows x64 Python 3.12（含 Tk）、Inno Setup 6，以及以下資源：

```
resources/
  models/faster-small/{config.json,model.bin,tokenizer.json,vocabulary.txt,.model_ready.json}
  bin/{ffmpeg.exe,ffprobe.exe}
  examples/排版示範.json
  guide.txt
  THIRD-PARTY-NOTICES.txt
  licenses/{components.json,python-packages/,inno-setup/ChineseTraditional.isl,...}
```

FFmpeg 與 FFprobe 必須是 Windows x64 PE；notices 必須涵蓋實際 binaries 的授權、來源、版本與必要 source offer，不可把 Mac binaries 改副檔名。模型必須附 schema 1 的完整 SHA256 manifest、通過 `download_model.model_ready(full=True)`，並可 `WhisperModel(..., local_files_only=True)` 載入；還需模型授權、套件授權合規覆核。

`ci_prepare.py` 固定模型來源 revision；`prepare_language.py` 固定 Inno 6.7.1 繁體中文語言來源及 hash。元件清單／原始 notices 收集是 inventory-only，不等於再散布授權全部完成。CI 不上传安裝成品、模型或音訊。

`check_dependencies.py` 稽核 x64 PE 的直接／延遲 imports，不借用建置機 MSVC runtime。只有精確宣告的 NumPy／PyAV loader 目錄及系統 Win32／API-set 名稱可解析；不會用所有子目錄的同名 DLL 掩蓋缺漏。靜態 imports 不涵蓋任意 `LoadLibrary` 或硬體驅動。

在 Windows 執行：

```powershell
.\Build.ps1 -PythonExe 'C:\Python312\python.exe' -PreparedResources 'D:\prepared\resources' -InnoCompiler 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' -Version '1.4.0' -BuildRoot 'D:\builds\ShangZiMu-new'
```

BuildRoot 必須不存在，腳本不遞迴清除舊資料。原生 build 會驗輸入、檢查套件、記錄解析版本、建置、執行 frozen `--self-test`，通過後才編譯安裝程式。此測試不能取代下列乾淨系統驗收。

## 發佈前必須完成

- 在無 Python／pip／FFmpeg 的乾淨 Windows 10/11 x64 實機或 VM 安裝。
- 移走來源資料夾，重新啟動與登出／重開機後從開始選單搜尋「上字幕」「字幕」啟動。
- 斷網驗證模型載入、實際講座／短影片轉錄、JSON 編輯／重開、SRT 匯出；確認無終端機視窗。
- 測視窗大小、中文 username 與空白路徑、唯讀輸出位置、使用者 cancel、安裝更新及解除安裝後 JSON 未刪。
- 驗剪映實際 SRT 匯入；有需要在 Windows 檔案防毒環境檢測 DLL。
- 確認 Authenticode 簽署／SmartScreen 風險及第三方授權。沒有憑證不可宣稱已簽署。

參考：[PyInstaller spec](https://pyinstaller.org/en/stable/spec-files.html)、[Inno Setup 無管理員安裝](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)。
