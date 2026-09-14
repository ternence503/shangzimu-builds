# 上字幕

把錄音與影片轉成文字，整理成可匯入 Final Cut Pro／剪映的 SRT 字幕。適合講座、課程、訪談與影片剪輯，減少手動切句、換行的時間。

## 發布狀態

### 1.5.0 全功能版：封裝與安裝後驗收中，尚未上架

目前分支包含五種語音模型（base／small／medium／large／turbo）、本機歌詞辨識與 UMX-HQ 人聲分離、傳送前逐次確認的雲端文字轉語音，以及字幕整理。第一次使用其他語音模型需要下載公開模型檔；影音不會因此上傳。完整功能操作說明見 [全功能使用指南](packaging/guide-full.txt)。

已完成原始碼環境的五模型中英文轉錄、12 種配音音色、長文字分段合成與本機分離試驗；不等於新安裝包已驗收。仍需完成封裝後四頁實測、系統禁網、安裝、停止與跨平台檢查。這台 Mac 的本機建置因執行環境限制最低為 macOS 26，不能宣称適用 macOS 14；較舊系統相容成品需以原生建置及依賴檢查確認。

下方下載連結仍是 **1.4.1 限定功能版**，不是全功能版。新安裝包通過驗收後會建立獨立下載入口，不會以原始碼更新代替安裝包交付。

**1.4.1 公開測試版：完整封裝安裝程式，未正式簽署。**

👉 [下載 Mac／Windows 安裝程式](https://github.com/ternence503/shangzimu-builds/releases/tag/v1.4.1-test.1)

| 你的電腦 | 在下載頁選擇的安裝檔 |
|---|---|
| Mac Apple M 系列晶片 | [下載 Apple 晶片版安裝程式](https://github.com/ternence503/shangzimu-builds/releases/download/v1.4.1-test.1/shangzimu-1.4.1-mac-arm64-test-unnotarized.pkg) |
| Mac Intel | [下載 Intel 版安裝程式](https://github.com/ternence503/shangzimu-builds/releases/download/v1.4.1-test.1/shangzimu-1.4.1-mac-x86_64-test-unnotarized.pkg) |
| Windows 64 位元 Intel／AMD | [下載 Windows 安裝程式](https://github.com/ternence503/shangzimu-builds/releases/download/v1.4.1-test.1/shangzimu-1.4.1-windows-x64-test-unsigned.exe) |

一般使用者只需下載自己的平台安裝檔。「Code → Download ZIP」與 `sources.zip` 是原始碼／授權材料，不是安裝程式。校驗碼和驗證紀錄也附在同一下載頁。

## 功能與隱私

- 本機轉錄音檔／影片，中文內容轉為繁體。
- 依可靠細部時間自然切句，調整字數、行數與不拆開的詞。
- 預覽、修改文字／換行、手動切分／合併、撤銷修改。
- 匯出 SRT；保存 JSON 專案，下次繼續。

安裝包包含執行環境、影音工具與 small 模型，安裝後不需自行安裝 Python 或下載模型。轉錄不需網路，也不會將影音送到第三方伺服器；下載安裝包需要網路，外部資料同步則依你選擇的儲存位置而定。

本測試版只有 small 模型，雲端文字轉語音與歌詞分離停用。辨識與切句結果仍需校對。

## 安裝與驗證

請看 [安裝與使用指引](INSTALL.md)。Mac 最低建置目標為 macOS 14；Windows 目標為 Windows 10／11 x64，非 ARM／32 位元。這是目標範圍，不是完整相容驗證清單。

本次安裝包來源為 `d6f6fca2df7cfb855c2dfe41734b64721dba7103`，[三平台原生建置驗證](https://github.com/ternence503/shangzimu-builds/actions/runs/34807571562) 全數通過，包含依賴閉包、實際合成語音轉錄與 SRT、系統禁網、安裝與啟動。影音工具與 PyAV 由可核對來源自建，第三方材料與校驗紀錄附於下載頁。Windows 使用 Server 2022 runner；不等於所有乾淨 Windows 10／11 電腦的介面與相容性驗收。

Mac 未做 Developer ID 簽署與 Apple 公證；Windows 未做 Authenticode 簽署。乾淨終端系統的安全提示、搜尋、重新開機、更新與解除安裝驗收仍待補齊。

[舊版資料](README-v1.4.0-history.md) 僅供歷史參考，其下載、模型與啟動脚本不適用這次完整封裝版。
