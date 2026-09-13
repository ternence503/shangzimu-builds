# CLAUDE.md

## 目前封裝分支（優先於以下歷史）

`build/shangzimu-bundled-app`：preview.6 GUI，47 單元測試及 6 封裝契約測試；`packaging/entry.py` 是「上字幕」原生包入口，包含 multiprocessing.freeze_support，禁止恢復執行時安裝／下載模型。Mac／Windows 原生包使用同一份 Mac _internal GUI 模組，兩平台腳本包仍各自維護。CI 在原生三平台建置，僅公開程式碼／測試流程，不建立正式 Release 或上傳二進位／影音。原生包版本 metadata 1.4.1 不代表已發行。

Intel Mac 隔離封裝已通過 OS 級禁止網路與開發路徑讀取的合成語音／SRT／Tk 測試；Windows OS 網路隔離、三平台乾淨安裝及搜尋／重啟、Developer ID 公證與完整再散布授權尚未通過。不得用單元測試或 CI 建置成功替代這些验收。封裝資源 THIRD-PARTY-NOTICES 目前僅為內部測試限制標示，不是完整授權文件。

最新preview.4：自然語句分塊與容量拆分獨立，layout_subtitles新增split_clauses=True，GUI開關保存到settings。常見詞組／中文序數及可靠字詞保護，換行以動態規劃取代貪婪填滿，避免極短尾行；仍非完整語意模型。所有切點需時間完整對齊，保留全文及外側起訖。新增所選字幕真實多行文字預覽。44測試與Mac Tk smoke通過，不等於實際影片/FCP/剪映驗收。保留preview.3移除舊引擎的修正。

最新版本 preview.3：修正真實 Intel/x86_64 Mac 安裝 LLVM 編譯問題，完全移除 GUI 的原始 whisper 匯入／型別及 openai-whisper 安裝依賴；不再需要 torch／numba／llvmlite。兩平台 installer 採 --only-binary=:all:。此機 pip dry-run 預編譯依賴解析成功，40測試及Mac Tk smoke通過；未实际安裝或下載模型。下面preview.2為先前功能背景，不應恢復舊引擎依賴。

## 隔離字幕排版試用版

本工作樹基於正式 8039a16 製作 `v1.4.0-layout-preview.2`，未發布或修改 SSD 原包。Mac／Windows GUI 現在相同，執行環境按平台搜尋 ffmpeg/ffprobe。只允許本機字幕處理，TTS 與歌詞分離分頁停用，small 模型從 WHISPER_FASTER_MODEL_DIR 已驗證目錄以 local_files_only=True 載入，不下載或 fallback。

新手改善：獨立 SubtitlePreview venv／模型／版本／Windows 捷徑，Mac Homebrew 系統工具仍共用；下載暫存、重試與完整性／本機載入驗證後才提升。Windows PS1 使用 UTF-8 BOM、-Exe/-Arguments 具名 array 及安全 native stderr 探測，保持 BOM。字幕有關閉／取消保存保護、最近50步復原、本機原子備份與恢復。包內新手指南及範例為最新版說明。38 項純方法／替身測試與 Mac Tk smoke 通過，不等於模型、首次安裝或真人新手驗收。

新主轉錄保存獨立資料夾、時間原稿 JSON，主轉錄輸出不再硬裁八秒；歌詞流程仍沿用舊邏輯。重排可不重辨識，保存修訂專案保留原稿、設定與手動換行。`python3 -m unittest discover -s tests -v` 驗證純函式與真實輸出方法，不需要模型。不得將合成時間示例或 GUI 控制項 smoke 當成真實音畫同步／模型準確率／離線安裝驗證。

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案說明

這是 Ternence 開發的 Whisper 語音工具（v1.4.0），提供圖形化介面，支援 Mac 與 Windows。

## 每次開啟先閱讀

開新對話或由其他 AI / 人員接手這個專案時，請先依序閱讀：

1. Ternence 提供的全域背景文件「Ternence 的開發背景資訊」
2. 本專案的 `CLAUDE.md`
3. `Whisper_開發版_整理版/README.md`

目的：

- 先確認工作硬碟、Git 規則、其他專案隔離原則
- 再理解 Whisper 專案自己的架構與目前功能
- 最後確認開發版 GUI 的使用方式與環境建立流程

## 目錄結構

```
Whisper/
├── Whisper_開發版_整理版/       ← 開發主目錄（平常在這裡工作）
├── Whisper_Mac_一鍵安裝版/      ← Mac 新手發佈包
├── Whisper_Windows_一鍵安裝版/  ← Windows 新手發佈包
├── docs/                        ← 截圖等文件資源
└── archive_old_2026-02-26/     ← 舊版備份
```

## 開發環境建立與啟動

開發版位於 `Whisper_開發版_整理版/`，需 Python 3.12 + ffmpeg + tcl-tk（透過 Homebrew）。

```bash
# 第一次：建立 .venv 並安裝依賴
cd Whisper_開發版_整理版
./setup_dev_env.sh

# 啟動 GUI
./run_whisper_gui.sh

# 命令列轉錄（自動語言）
./run_whisper_auto.sh <音檔路徑>

# 命令列轉錄（指定中文）
./run_whisper_zh.sh <音檔路徑>
```

依賴套件（`requirements-dev.txt`）：
- `openai-whisper==20250625`（fallback 引擎）
- `faster-whisper>=1.1.0`（v1.4.0 起的**主要**轉錄引擎，CTranslate2 後端＋內建 Silero VAD）
- `opencc-python-reimplemented>=0.1.7`（簡繁轉換）
- `edge-tts>=7.2.8`（文字轉語音）
- `demucs>=4.0.1`（歌詞辨識分頁的人聲分離）
- `pip-system-certs>=5.0`（SSL 信任作業系統憑證庫，見下方技術決策）

## 核心架構

所有版本（開發版、Mac 版、Windows 版）共用相同的單檔 GUI 程式架構：

- **`whisper_gui.py`**（開發版）/ `whisper_gui_mac.py` / `whisper_gui_win.py`：單一檔案 tkinter 應用
- **`WhisperApp` class**：包含全部 UI 建構、轉錄、歌詞辨識與 TTS 邏輯
  - 介面以 `ttk.Notebook` 分成「語音轉字幕」「文字轉語音」「歌詞辨識」三個分頁
  - 轉錄、TTS、歌詞辨識都在背景 thread 執行，UI 不卡頓
  - 停止轉錄使用 `ctypes.pythonapi.PyThreadState_SetAsyncExc`（強制中止 thread）
  - 已載入的模型快取在 `self.model_cache` dict，避免重複載入
- **轉錄引擎（v1.4.0 起）**：優先用 **faster-whisper**（`_FasterWhisperModel`），透過 `self._transcribe()` 統一入口分派；沒裝時自動退回 openai-whisper。兩條路徑都回傳同結構 dict（`language`/`text`/`segments`），後續繁化、去重、輸出流程完全共用。faster-whisper 模型快取在 `self.faster_model_cache`（與 openai 的 `self.model_cache` 分開），CPU 上用 `compute_type="int8"`
- **VAD 去幻覺（v1.4.0 起，最關鍵）**：faster-whisper 開 `vad_filter=True` + Silero VAD，先切掉靜音段，講者走動/換場/沉默的空檔根本不進模型，從**源頭**消除「我只想說×45」那類靜音幻覺（語言選擇器、事後去重都治不了的根因）
- **即時進度**：`_transcribe(..., progress_cb)` 逐段回報 `segment.end / info.duration`，狀態列顯示「轉錄中… 42%（00:25:30 / 01:00:12）」，長檔不再看起來像當機
- **輸出格式**：`.txt`、`.srt`、`.vtt`，存放於與輸入檔同目錄，檔名格式為 `{原檔名}_{偵測語言}.{副檔名}`
- **抗幻覺（三層）**：① VAD 從源頭跳過靜音（見上）；② `_dedupe_repeated_segments()` 過濾重複幻覺，v1.4.0 升級為**兩層**——`_collapse_repeated_phrase()` 收斂「單一 segment 內部自我重複」（如整段 `我只想說,我只想說,…`），再擋「跨段連續重複」；③ `_clamp_segment_durations()` 把單塊字幕顯示時長夾在 `MAX_SUBTITLE_DURATION`（8 秒）內，避免 VAD 跳過靜音後最後一句 end 被拉到下一句開口（實測看過一塊被拉到 26 分鐘）害字幕掛在畫面上——只夾 srt/vtt 時間軸，不動文字與 `.txt`。`.txt` 輸出為每個 segment 一行，不是整段無斷句字串
- **中文繁化**：偵測語言為中文時，使用 OpenCC config `s2twp` 轉為繁體中文（`_to_traditional`）
- **歌詞辨識**（v1.3.0 新增）：選用 Demucs 分離人聲（`python -m demucs --two-stems=vocals --mp3`，子行程）再用 Whisper 辨識，輸出 `.txt`/`.lrc`/`.srt`
  - **務必使用 `--mp3` 輸出**（見下方技術決策，避免 torchaudio/torchcodec/ffmpeg ABI 版本地獄）
- **字幕校對**（v1.4.0 新增，分頁名「字幕校對」，**目前僅開發版**）：第 4 個分頁，用**本地 Ollama LLM** 依上下文校對辨識錯字（同音字、成語），規則式對照表做不到（不懂語意）。核心在 `_proofread_lines()`：把字幕逐行分段（`PROOFREAD_CHUNK_LINES=40`）送 `POST /api/chat`（`_ollama_chat`，走 stdlib `urllib`，不加依賴），逐段附帶「已校對前文」維持跨句一致性（李→林）。**安全設計**：只校對純文字、時間軸與行數完全不碰；每段回傳用 `_parse_numbered_lines()` 驗行號齊全，對不上就整段保留原文；輸出 `{stem}_校對.srt`＋`{stem}_校對對照.txt`（改動清單供人工覆核）。提示詞走**保守策略**（只改同音／近音字，不同音不亂猜，避免把「物質」誤校成「心理」這種語意猜測）。預設模型 `qwen2.5:14b`（中文校對開源最強；64GB 記憶體可用 32b）。沒裝 Ollama／沒下載模型會跳提示，不影響其他分頁
- **文字轉語音**：使用 `edge-tts` 產生 `.mp3`，長文會先分段再透過 `ffmpeg` 合併
  - 使用 `asyncio.new_event_loop()` + task cancellation 實現即時停止
  - GUI 提供語速選項：`-10%`、`0%`、`+5%`、`+10%`、`+20%`、`+30%`、`+40%`、`+50%`、`+60%`、`+75%`、`+100%`（預設 `+5%`）
  - GUI 提供音高選項：`-6Hz`、`-4Hz`、`-2Hz`、`0Hz`、`+2Hz`、`+4Hz`、`+6Hz`、`+8Hz`、`+10Hz`（預設 `+2Hz`）
  - 12 種聲音，分台灣腔 / 粵語腔 / 普通話三組（見下方聲音清單）
  - 已有保守型「朗讀優化」：只調整斷句、時間、電話、網址的朗讀形式，不改活動資訊本身
  - 輸出模式：`原文直出`、`2 分鐘精簡版`、`短影音版`
  - 精簡模式為本地規則式濃縮，會優先保留日期、時間、地點與 CTA 句

## 聲音清單（v1.2.0）

| 標籤 | Edge TTS Voice |
|------|----------------|
| 台灣女聲・活潑 | zh-TW-HsiaoYuNeural |
| 台灣女聲・清亮 | zh-TW-HsiaoChenNeural |
| 台灣男聲・沉穩 | zh-TW-YunJheNeural |
| 粵語女聲・活潑 | zh-HK-HiuGaaiNeural |
| 粵語女聲・溫柔 | zh-HK-HiuMaanNeural |
| 粵語男聲・友善 | zh-HK-WanLungNeural |
| 普通話女聲・活潑 | zh-CN-XiaoyiNeural |
| 普通話女聲・溫柔 | zh-CN-XiaoxiaoNeural |
| 普通話男聲・熱情 | zh-CN-YunjianNeural |
| 普通話男聲・陽光 | zh-CN-YunxiNeural |
| 普通話男聲・穩重 | zh-CN-YunyangNeural |
| 普通話男聲・可愛 | zh-CN-YunxiaNeural |

## 重要技術決策

- **v1.4.0 改用 faster-whisper 為主引擎（openai-whisper 保留為 fallback）**：舊版最大的痛點是講座/長檔在靜音、換場、測麥、閒聊等**沒有人聲**的段落產生大量重複幻覺（`我只想說×45`、`能夠 能夠 能夠`…），而且指定語言、`temperature=0`、事後去重都治不了根因。faster-whisper 內建 **Silero VAD**（`vad_filter=True`），把靜音段直接排除、不進模型，從源頭解決；同時底層是 **CTranslate2，完全不依賴 torch**，剛好避開下面 demucs 那串 torch/torchaudio/torchcodec/ffmpeg ABI 地獄，字幕這條路更穩、更好打包。實作上用 `self._transcribe()` 統一分派，faster-whisper 缺席時自動 `import` 失敗→退回 openai-whisper，確保任何環境都能跑。附帶修掉一個舊 bug：`temperature` 原本寫死 `0.0`（單一值）會讓 `compression_ratio_threshold` 的「升溫重試」失效，改回 fallback 序列 `(0.0, 0.2, …, 1.0)` 門檻才真正生效。
- **VAD 造成的字幕超長顯示 → `_clamp_segment_durations()`**：開 VAD 後，被跳過的靜音空檔會讓「空檔前最後一句」的 `end` 被拉長到下一句開口為止（實測一塊 26 分鐘）。用 `MAX_SUBTITLE_DURATION=8` 秒夾住 `end`，該空檔變成無字幕（正確），只影響 srt/vtt 時間軸、不動文字與 `.txt`。
- **SSL 信任作業系統憑證庫（`pip-system-certs`）**：公司網路的防火牆/防毒會對 HTTPS 做 SSL 檢查並用自己的自簽憑證，macOS/Windows 系統本身信任這張憑證，但 Python 預設不信任，導致下載 Whisper/Demucs 模型時出現 `CERTIFICATE_VERIFY_FAILED`。`pip-system-certs` 透過 `.pth` 在解譯器啟動時自動套用，**不需要任何程式碼配合**，而且涵蓋 `subprocess` 啟動的子行程（例如歌詞辨識叫用的 `python -m demucs`）。之前用 `truststore.inject_into_ssl()` 手動注入只能保護呼叫的那個程序本身，沒辦法保護 demucs 子行程，2026-06-29 已全面換成 `pip-system-certs`，三個版本都移除了手動 inject 的程式碼，純粹靠這個套件存在於 venv 裡生效。
- **Demucs 輸出務必用 `--mp3`，不要用預設 `.wav`**：demucs 預設輸出 wav 會呼叫 `torchaudio.save()`，新版 torchaudio 把 wav 存檔的後端換成 `torchcodec`，而 `torchcodec` 需要對應 ABI 版本的 ffmpeg 動態函式庫（例如 libavutil.56），但 Homebrew 的 `ffmpeg` formula 一直追最新版（2026-06 已到 ffmpeg 8.x），版本對不上會出現 `Library not loaded: @rpath/libavutil.56.dylib`。改用 `--mp3` 輸出會走 demucs 自己的 `lameenc` 編碼器，完全不經過 torchaudio/torchcodec，不需要額外裝 `torchcodec`，也不受 Homebrew ffmpeg 版本影響。
- **轉錄結尾幻覺重複**：`_dedupe_repeated_segments()` 過濾掉同一句話連續重複超過 2 次的 segment（去標點後比對），這是 Whisper 在靜音/配樂段落常見的幻覺，跟語言誤判是不同的成因，語言選擇器解決不了這種情況。

## 發佈流程（版本更新）

> ⚠️ **2026-03-26 重構後，Mac/Windows 實際執行的程式都在 `_internal/` 底下**（`▶ 啟動 Whisper.command` / `.bat` 會 cd 進 `_internal` 才跑 `whisper_gui_mac.py`/`whisper_gui_win.py`）。
> 複製到舊的頂層路徑（沒有 `_internal/`）只會產生一份不會被執行的死檔案——2026-06-29 修 bug 時就因為這份過時說明，先誤改了 `Whisper_Mac_一鍵安裝版/whisper_gui_mac.py`（頂層、未被 git 追蹤的殘留檔），後來才發現真正會跑的是 `Whisper_Mac_一鍵安裝版/_internal/whisper_gui_mac.py`。修改前務必先用 `grep -n whisper_gui *.sh` 之類的方式確認該版本真正引用的路徑。

1. 在 `Whisper_開發版_整理版/whisper_gui.py` 完成修改
2. 同步到 Mac 版：`cp whisper_gui.py ../Whisper_Mac_一鍵安裝版/_internal/whisper_gui_mac.py`
3. 同步到 Win 版：`cp whisper_gui.py ../Whisper_Windows_一鍵安裝版/_internal/whisper_gui_win.py`，然後將 `_configure_runtime_environment` 替換為 Windows 版本
   - Mac 版與開發版的 `_configure_runtime_environment` **相同**，整檔覆蓋即可；只有 Windows 版這個函式不同（搜尋 `ffmpeg/` 子目錄並確認 `ffprobe.exe`）。同步後用 `diff mac win` 確認差異**只落在這個函式內**。
4. 若有動到依賴：三份 `requirements-*.txt`（`requirements-dev.txt`／`requirements-mac.txt`／`requirements-win.txt`）都要同步加同一個套件（例如 v1.4.0 的 `faster-whisper>=1.1.0`）
5. 更新 `APP_VERSION` 字串（三個檔案）
6. 更新各 README 與本 CLAUDE.md 的版本資訊
7. 執行清理腳本後打包發佈

## 版本間差異

| 版本 | 說明 |
|------|------|
| 開發版 | 使用 `setup_dev_env.sh` 建立 `.venv`，ffmpeg 由 Homebrew 安裝 |
| Mac 版 | `setup_and_run_mac.sh` 包含完整 Homebrew + Python + ffmpeg 安裝流程，含 `download_model.py`；單一啟動點 `▶ 啟動 Whisper.command` |
| Windows 版 | 使用 PowerShell (`setup_and_run.ps1`) + `▶ 啟動 Whisper.bat`；環境存於 `%LOCALAPPDATA%\WhisperGui\`；自動建立桌面捷徑 |

## 目前待辦

- **字幕校對是否併入 Mac/Win 一鍵安裝版待決策**：目前只在開發版。難點是它需要**本地 Ollama + qwen2.5 模型（約 9GB）**，對新手一鍵安裝包是額外的重量與安裝步驟。選項：(a) 打包時不含、僅開發版；(b) Mac/Win 安裝流程加「選用：安裝 Ollama」步驟；(c) 做成外掛/獨立小工具。決定後再同步 `whisper_gui_mac.py`/`whisper_gui_win.py` 並處理版本號。
- **精簡模式目前是規則式版本**：適合活動旁白、口播文案的第一輪壓縮，但還不是語意理解型摘要。
- 若後續要再強化，優先方向應為：
  - 針對活動文案再補強「主題 / 好處 / 講者 / CTA」的句型權重
  - 讓使用者可自訂目標長度或字數，而不只固定的 2 分鐘 / 短影音
  - 若未來允許外部模型，再評估加入真正的語意式摘要流程

## 打包給新手前

先執行清理腳本，移除 `.venv`、模型快取、macOS 暫存檔：

```bash
# Mac 版
./Whisper_Mac_一鍵安裝版/99-打包前清理.command

# Windows 版
Whisper_Windows_一鍵安裝版\99-打包前清理.bat
```
