# 上字幕

把錄音與影片轉成文字，整理成可匯入 Final Cut Pro／剪映的 SRT 字幕。適合講座、課程、訪談與影片剪輯，減少手動切句、換行的時間。

## 發布狀態

**公開測試版準備中，完整安裝包尚未發布。** 使用者已同意未正式簽署的測試版；第三方授權與對應來源材料仍待補齊。

完成後將在 [Releases](https://github.com/ternence503/shangzimu-builds/releases) 提供 Mac Intel、Mac Apple 晶片、Windows x64 安裝包、版本限制及 SHA256。沒有對應成品表示尚未發布；「Code → Download ZIP」是原始碼，不是安裝包。

## 功能與隱私

- 本機轉錄音檔／影片，中文內容轉為繁體。
- 依可靠細部時間自然切句，調整字數、行數與不拆開的詞。
- 預覽、修改文字／換行、手動切分／合併、撤銷修改。
- 匯出 SRT；保存 JSON 專案，下次繼續。

完整封裝版的目標是包含執行環境、影音工具與 small 模型，安裝後不需自行安裝 Python 或下載模型。轉錄不需將影音送到第三方伺服器；下載安裝包需要網路，外部資料同步則依你選擇的儲存位置而定。

本測試版只有 small 模型，雲端文字轉語音與歌詞分離停用。辨識與切句結果仍需校對。

## 安裝與驗證

請看 [安裝與使用指引](INSTALL.md)。Mac 最低建置目標為 macOS 14；Windows 目標為 Windows 10／11 x64，非 ARM／32 位元。這是目標範圍，不是完整相容驗證清單。

上游基準 cc226d71864a4e36c70deb6be572f1ad1ff7111b 的 [三平台原生建置驗證](https://github.com/ternence503/whisper-gui/actions/runs/34793061049) 已通過，包含依賴、合成語音轉錄與 SRT、系統禁網、安裝與啟動等。Windows 使用 Server 2022 runner；不等於乾淨 Windows 10／11 使用者介面驗收，也不代表本 repo 後續改動全部通過。

Mac 未做 Developer ID 簽署與 Apple 公證；Windows 未做 Authenticode 簽署。乾淨終端系統的安全提示、搜尋、重新開機、更新與解除安裝驗收仍待補齊。

[舊版資料](README-v1.4.0-history.md) 僅供歷史參考，其下載、模型與啟動脚本不適用這次完整封裝版。
