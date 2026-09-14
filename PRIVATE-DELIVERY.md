# 上字幕私人封裝與交付

本 repo 為私人內部建置，不是正式發行。原始碼基準為公開 whisper-gui 的 cc226d71864a4e36c70deb6be572f1ad1ff7111b，三平台驗證 run 34793061049 通過。

僅手動啟動 workflow，且每個 job 必須確認此 repo 名稱及 PRIVATE。Actions 先停用，待額度或費用授權確認；不變更帳號的支出預算或付款設定。

每項原生工作最多 40 分鐘；每平台 artifact 小於 1 GiB、保留 7 日。額度查詢 API 缺 user scope，未擴張 OAuth 權限；替代瀏覽器尚未登入，不能核實剩餘額度。依 GitHub 官方標準 runner 單價，三項工作滿 40 分鐘的運算費為 US$5.36，另有少量私人 artifact 儲存費。啟動前須取得單批明確費用上限，不自動重跑或更改付款／預算設定。

安裝成品通過原生依賴、移動路徑、系統禁網轉錄及實際安裝驗收後才保存。artifact 保留 7 日，只含明確安裝程式、實際 build dependency lock、元件清單、去除路徑／文字的驗收證據與 SHA256／來源 manifest。不上传私人影音、合成語音檔、整個臨時資料夾、venv、credentials；模型只隨完整安裝程式封裝，不單獨公开或上传。

Mac pkg 目前是 ad-hoc 測試簽署，不是 Developer ID／公證；Windows installer 尚未 Authenticode 簽署。成品標示內部驗證、未正式簽署、不可再散布，不交作使用者最後測試完成品。

components.json 由前置環境產生，actual-build-dependency-lock.txt 在 Windows 來自真正 freeze venv。私人流程把前置環境解析版本固定供 freeze venv 安裝，保存前再逐項比對版本，不一致即失敗；這項新 gate 尚未執行原生 CI。即使一致，也不代表元件清單精確等於所有 bundle 原生依賴或授權已完整清關。最終 notices、來源材料、乾淨終端 OS 搜尋／重啟／安全提示／更新解除安裝與正式簽署公證尚待完成。

不建立 Release／tag，不修改公開 repo 或 SSD 正式工作樹。
