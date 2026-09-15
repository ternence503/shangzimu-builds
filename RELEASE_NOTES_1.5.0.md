# 上字幕 1.5.0 全功能公開測試版

這次把「上字幕」從單一語音轉字幕工具，擴充為可直接安裝的完整字幕工作台。安裝包已包含執行環境、影音工具、small 語音模型及本機人聲分離功能，不需要另外安裝 Python。

## 主要功能

- 本機語音轉字幕：適合講座、訪談及長短影片，影音不會上傳第三方伺服器。
- 五種辨識模型：small 可直接使用；base、medium、large、turbo 第一次選用時下載公開模型。
- 字幕整理：自然切句、換行、字數與行數控制、專有名詞保護、手動修改、拆分、合併及撤銷。
- 專案保存：以 JSON 保留文字、排版設定及細部時間，下次可繼續；另可匯出 Final Cut Pro／剪映使用的 SRT。
- 本機歌詞辨識：可先以 UMX-HQ 分離人聲，再輸出 TXT、LRC 及 SRT。
- 文字轉語音：使用 Microsoft Edge 線上語音服務，每次傳送文字前都會要求確認。

## 下載選擇

- Apple M 系列 Mac：`shangzimu-1.5.0-mac-arm64-full-test-unnotarized.pkg`
- Intel Mac：`shangzimu-1.5.0-mac-x86_64-full-test-unnotarized.pkg`
- Windows 10／11 64 位元 Intel／AMD：`shangzimu-1.5.0-windows-x64-full-test-unsigned.exe`

`sources.zip` 是來源與授權材料，不是安裝程式。`SHA256SUMS.txt` 與 verification zip 供核對下載檔及驗證紀錄。

## 測試版注意事項

Mac 尚未做 Developer ID 簽署與 Apple 公證；Windows 尚未做 Authenticode 簽署。請只從本專案 GitHub Release 下載，依個別應用程式的系統提示處理，不要關閉整台電腦的安全防護。不同音質、多人重疊、歌唱咬字及強伴奏仍可能造成錯字，輸出後請人工校對。

Apple 晶片版已由實際使用者在另一台 Mac 完成下載、安裝與使用測試。自動建置另在三種原生系統環境檢查安裝、啟動、本機語音轉錄、SRT、依賴完整性與人聲分離；其結果不代表所有硬體、公司政策或作業系統版本皆已覆蓋。
