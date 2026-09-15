# 上字幕

把錄音與影片轉成文字，整理成可匯入 Final Cut Pro／剪映的 SRT 字幕。適合講座、課程、訪談與影片剪輯，減少手動切句、換行的時間。

## 發布狀態

### 1.5.0 全功能公開測試版

1.5.0 包含四個完整工作區：本機語音轉字幕、需逐次確認才傳送文字的雲端文字轉語音、本機歌詞辨識與 UMX-HQ 人聲分離，以及字幕整理。辨識可選 base／small／medium／large／turbo；small 已內建，其他模型第一次選用時才下載公開模型檔，影音不會因此上傳。

👉 [下載 1.5.0 Mac／Windows 完整安裝程式](https://github.com/ternence503/shangzimu-builds/releases/tag/v1.5.0-test.1)

| 你的電腦 | 在下載頁選擇的安裝檔 |
|---|---|
| Mac Apple M 系列晶片 | [下載 Apple 晶片版](https://github.com/ternence503/shangzimu-builds/releases/download/v1.5.0-test.1/shangzimu-1.5.0-mac-arm64-full-test-unnotarized.pkg) |
| Mac Intel | [下載 Intel 版](https://github.com/ternence503/shangzimu-builds/releases/download/v1.5.0-test.1/shangzimu-1.5.0-mac-x86_64-full-test-unnotarized.pkg) |
| Windows 64 位元 Intel／AMD | [下載 Windows 版](https://github.com/ternence503/shangzimu-builds/releases/download/v1.5.0-test.1/shangzimu-1.5.0-windows-x64-full-test-unsigned.exe) |

一般使用者只需下載自己的平台安裝檔。「Code → Download ZIP」與 `sources.zip` 是原始碼／授權材料，不是安裝程式。校驗碼和驗證紀錄也附在同一下載頁。

## 功能與隱私

- 本機轉錄音檔／影片，中文內容轉為繁體。
- 依可靠細部時間自然切句，調整字數、行數與不拆開的詞。
- 預覽、修改文字／換行、手動切分／合併、撤銷修改。
- 匯出 SRT；保存 JSON 專案，下次繼續。

安裝包包含執行環境、影音工具與 small 模型，安裝後不需自行安裝 Python 或下載模型。轉錄不需網路，也不會將影音送到第三方伺服器；下載安裝包需要網路，外部資料同步則依你選擇的儲存位置而定。

small 模型可安裝後直接使用；其餘模型首次使用需連網下載。語音轉字幕、字幕整理、歌詞辨識與人聲分離都在本機處理。文字轉語音使用 Microsoft Edge 線上語音服務，每次傳送文字前都會要求確認。辨識、歌詞與切句結果仍需人工校對。

## 安裝與驗證

請看 [安裝與使用指引](INSTALL.md)。Mac 最低建置目標為 macOS 14；Windows 目標為 Windows 10／11 x64，非 ARM／32 位元。這是目標範圍，不是完整相容驗證清單。

每個下載檔都由同一版本原始碼在對應作業系統原生建置，並在 GitHub Actions 通過依賴檢查、實際合成語音轉錄與 SRT、系統禁網、安裝及啟動。Apple 晶片版另已由實際使用者在另一台 Mac 完成下載、安裝與使用測試。下載頁附 SHA-256 校驗碼、驗證紀錄及第三方材料。

Mac 未做 Developer ID 簽署與 Apple 公證；Windows 未做 Authenticode 簽署，因此仍屬公開測試版。不同公司安全政策、所有 Windows 10／11 組合、重新開機、更新與解除安裝尚未全面覆蓋。

[舊版資料](README-v1.4.0-history.md) 僅供歷史參考，其下載、模型與啟動脚本不適用這次完整封裝版。
