# 全功能版驗收狀態（2026-09-16）

上字幕 1.5.0 全功能公開測試版已完成 Mac Apple 晶片、Mac Intel 與 Windows x64 的原生建置、安裝、啟動及功能驗收，並已公開發布。

## 發布結果

- 公開版本：`v1.5.0-test.1`
- 發布頁：https://github.com/ternence503/shangzimu-builds/releases/tag/v1.5.0-test.1
- 來源版本：`4b65dad76c0908bc8ac0cd88e85fc344e96e7b4d`
- 三系統驗收：https://github.com/ternence503/shangzimu-builds/actions/runs/34986570695
- GitHub 專案：公開，預設分支為 `main`
- 舊 `ternence503/whisper-gui` 專案：已設為私人，避免使用者誤下載舊版。

## 已驗證

- 三平台都由同一來源版本建立，沒有混用舊安裝包。
- Mac arm64、Mac x86_64：在乾淨 runner 安裝到「應用程式」並執行實際 App。
- Windows x64：安裝並執行實際 App，確認開始選單捷徑。
- 五種語音辨識模型、細部時間、字幕專案 JSON 與 SRT 流程。
- 字幕排版、自然語句切句、人工修字／換行與輸出。
- 歌詞辨識流程、人聲分離及 TXT／LRC／SRT 輸出。
- 文字轉語音的分段、合併、影音解碼，以及送出前的隱私確認。
- App 搬移後離線辨識、模型完整性及原生相依閉包。
- 安裝包、對應原始碼與授權材料均提供 SHA-256 校驗。

## 隱私與限制

- 語音辨識、字幕處理與人聲分離在本機執行；公開模型隨安裝包提供，不需把音訊上傳到第三方服務。
- 文字轉語音使用第三方雲端服務，每次送出文字前都會要求確認。
- 目前是未正式簽署的公開測試版。macOS 可能需要在「系統設定 → 隱私權與安全性」允許開啟；Windows 可能顯示 SmartScreen 提醒。
- 通過的是安裝、執行與功能流程驗收，不代表所有真實錄音條件下的辨識準確率都相同。

## 發布檔案

- `shangzimu-1.5.0-mac-arm64-full-test-unnotarized.pkg`
- `shangzimu-1.5.0-mac-x86_64-full-test-unnotarized.pkg`
- `shangzimu-1.5.0-windows-x64-full-test-unsigned.exe`
- 三平台對應來源與授權材料、驗收證據及 `SHA256SUMS.txt`
