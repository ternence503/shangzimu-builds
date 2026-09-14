#!/usr/bin/env python3
"""簡易圖形介面的 Whisper 語音轉字幕工具 (CPU 版)。"""

from __future__ import annotations

import os
import threading
import ctypes
import sys
import io
import asyncio
import shutil
import subprocess
import tempfile
import re
import copy
import json
from pathlib import Path
from subtitle_layout import layout_subtitles, split_subtitle_at, has_split_timing
from subtitle_workspace import (read_document, serialize_srt, serialize_document, save_new_file,
                                next_revision_path, write_recovery)
from typing import Dict, Iterable, List, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ModuleNotFoundError as exc:
    raise SystemExit("目前的 Python 未啟用 tkinter，請安裝 tcl-tk 後再執行本工具。") from exc

try:
    # faster-whisper（CTranslate2 後端）：內建 Silero VAD，可從源頭去掉靜音幻覺，
    # 試用版只使用此本機引擎，不安裝原始 Whisper、torch 或 LLVM 編譯依賴。
    from faster_whisper import WhisperModel as _FasterWhisperModel
except Exception:  # pragma: no cover
    _FasterWhisperModel = None

FASTER_WHISPER_AVAILABLE = _FasterWhisperModel is not None

try:
    from opencc import OpenCC
except Exception:  # pragma: no cover
    OpenCC = None
try:
    import edge_tts
except Exception:  # pragma: no cover
    edge_tts = None

MODEL_OPTIONS: List[str] = [
    "base",
    "small",
    "medium",
    "large",
    "turbo",
]

MEDIA_FILE_PATTERNS = (
    "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.wma "
    "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.mpeg *.mpg"
)

APP_AUTHOR = "Ternence"
APP_VERSION = "v1.5.0-full-test.1"
APP_SIGNATURE = f"{APP_AUTHOR} {APP_VERSION}"
TTS_VOICE_OPTIONS: Dict[str, str] = {
    # 台灣腔
    "台灣女聲・活潑": "zh-TW-HsiaoYuNeural",    # Friendly, Positive（台灣國語腔）
    "台灣女聲・清亮": "zh-TW-HsiaoChenNeural",  # Friendly, Positive（台灣腔，咬字清晰）
    "台灣男聲・沉穩": "zh-TW-YunJheNeural",     # Friendly, Positive（台灣男聲）
    # 粵語腔
    "粵語女聲・活潑": "zh-HK-HiuGaaiNeural",   # Friendly, Positive（粵語女聲，語氣輕快）
    "粵語女聲・溫柔": "zh-HK-HiuMaanNeural",   # Friendly, Positive（粵語女聲，語氣柔和）
    "粵語男聲・友善": "zh-HK-WanLungNeural",   # Friendly, Positive（粵語男聲）
    # 普通話
    "普通話女聲・活潑": "zh-CN-XiaoyiNeural",  # Lively
    "普通話女聲・溫柔": "zh-CN-XiaoxiaoNeural", # Warm
    "普通話男聲・熱情": "zh-CN-YunjianNeural",  # Passion
    "普通話男聲・陽光": "zh-CN-YunxiNeural",   # Lively, Sunshine
    "普通話男聲・穩重": "zh-CN-YunyangNeural",  # Professional, Reliable
    "普通話男聲・可愛": "zh-CN-YunxiaNeural",  # Cute（偏童趣少年聲）
}
TTS_RATE_OPTIONS = ["-10%", "0%", "+5%", "+10%", "+20%", "+30%", "+40%", "+50%", "+60%", "+75%", "+100%"]
TTS_PITCH_OPTIONS = ["-6Hz", "-4Hz", "-2Hz", "0Hz", "+2Hz", "+4Hz", "+6Hz", "+8Hz", "+10Hz"]
TTS_MAX_CHARS = 900
TTS_SCRIPT_MODE_TARGETS: Dict[str, Optional[int]] = {
    "原文直出": None,
    "2 分鐘精簡版": 420,
    "短影音版": 220,
}
TTS_DIGIT_MAP = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}

class _SilentStream(io.TextIOBase):
    def write(self, _data: str) -> int:
        return len(_data or "")

    def flush(self) -> None:  # pragma: no cover
        return None


def _ensure_stdio() -> None:
    if sys.stdout is None:
        sys.stdout = _SilentStream()
    if sys.stderr is None:
        sys.stderr = _SilentStream()


# temperature 用 fallback 序列（不是單一 0.0）：只有給多個溫度，Whisper 才會在
# compression_ratio / logprob 判定為幻覺時「升溫重試」，門檻才真正生效；
# 若寫死 0.0 等於沒有退避溫度，壓縮比門檻形同虛設，這是舊版幻覺沒擋掉的主因之一。
TRANSCRIBE_TEMPERATURE = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

DEFAULT_OPTIONS = {
    "temperature": TRANSCRIBE_TEMPERATURE,
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.4,
    "compression_ratio_threshold": 2.0,
}

# faster-whisper 的 Silero VAD 參數：靜音超過這個長度才切段，避免把正常停頓也吃掉。
VAD_PARAMETERS = {"min_silence_duration_ms": 500}

# CPU 上用 int8 量化：速度快、記憶體省，實測對中文辨識品質影響可忽略。
FASTER_COMPUTE_TYPE = "int8"


def _format_timestamp(seconds: float, *, separator: str) -> str:
    if seconds is None:
        seconds = 0.0
    seconds = max(0.0, float(seconds))
    milliseconds = round(seconds * 1000)
    total_seconds, ms = divmod(milliseconds, 1000)
    minutes, sec = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if separator == ",":
        return f"{hours:02}:{minutes:02}:{sec:02},{ms:03}"
    return f"{hours:02}:{minutes:02}:{sec:02}.{ms:03}"


def _format_hms(seconds: float) -> str:
    """把秒數格式化成 HH:MM:SS，用於轉錄進度顯示。"""
    total = int(max(0.0, float(seconds or 0.0)))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    return f"{hours:02}:{minutes:02}:{sec:02}"


def _format_srt(segments: Iterable[Dict[str, float]]) -> str:
    lines: List[str] = []
    index = 1
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = _format_timestamp(seg.get("start", 0.0), separator=",")
        end = _format_timestamp(seg.get("end", 0.0), separator=",")
        lines.append(str(index))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
        index += 1
    return "\n".join(lines).strip() + "\n"


def _format_vtt(segments: Iterable[Dict[str, float]]) -> str:
    lines: List[str] = ["WEBVTT", ""]
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = _format_timestamp(seg.get("start", 0.0), separator=".")
        end = _format_timestamp(seg.get("end", 0.0), separator=".")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _format_lrc(segments: Iterable[Dict[str, float]]) -> str:
    lines: List[str] = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start = seg.get("start", 0.0)
        minutes = int(start // 60)
        seconds = start % 60
        lines.append(f"[{minutes:02d}:{seconds:05.2f}]{text}")
    return "\n".join(lines) + "\n"


_REPEAT_STRIP_PATTERN = re.compile(r"[\s,，。！？!?.、]")
_SEP_PATTERN = re.compile(r"[,，、\s]")

# 字幕單塊最長顯示秒數。開了 VAD 後，靜音段被跳過，跳過前的最後一句 end 會被
# 拉長到下一句開口為止（實測看過一塊被拉到 26 分鐘），字幕會一直卡在畫面上。
# 這裡把過長的 end 夾住，該靜音空檔就變成沒字幕（正確），不影響文字內容與 txt。
MAX_SUBTITLE_DURATION = 8.0


def _clamp_segment_durations(
    segments: Iterable[Dict[str, object]], max_dur: float = MAX_SUBTITLE_DURATION
) -> List[Dict[str, object]]:
    """夾住每塊字幕的顯示時長，避免 VAD 靜音空檔造成字幕掛在畫面上好幾分鐘。

    只縮短過長的 end（不動 start、不動文字），所以不會產生時間軸重疊，
    也不會漏字；被夾掉的那段空檔本來就是沒有人聲的靜音，無字幕才正確。
    """
    clamped: List[Dict[str, object]] = []
    for seg in segments:
        try:
            start = float(seg.get("start", 0.0) or 0.0)
            end = float(seg.get("end", 0.0) or 0.0)
        except (TypeError, ValueError):
            clamped.append(seg)
            continue
        if end - start > max_dur:
            seg = dict(seg)
            seg["end"] = start + max_dur
        clamped.append(seg)
    return clamped


def _collapse_repeated_phrase(text: str, keep: int = 2) -> str:
    """收斂「單一段落內部」自我重複的幻覺，例如
    「我只想說,我只想說,…（重複 45 次）」或「能夠能夠能夠」「小小的小小的」。

    做法：去掉分隔符後找出從頭連續鋪滿整段的最短重複單元，若重複次數過多
    （且覆蓋整段 8 成以上），就收斂成 keep 次。太短的字串（<8 字）不處理，
    避免誤傷正常的疊字（例如「謝謝」「好好」）。
    """
    stripped = str(text or "").strip()
    core = _REPEAT_STRIP_PATTERN.sub("", stripped)
    n = len(core)
    if n < 8:
        return stripped
    had_sep = bool(_SEP_PATTERN.search(stripped))
    for unit_len in range(1, min(n // 3, 12) + 1):
        unit = core[:unit_len]
        reps = 0
        idx = 0
        while core[idx:idx + unit_len] == unit:
            reps += 1
            idx += unit_len
        # reps 夠多且連續重複部分覆蓋整段 8 成以上，才判定為幻覺循環
        if reps >= keep + 1 and idx >= n * 0.8:
            if had_sep:
                return "，".join([unit] * keep)
            return unit * keep
    return stripped


def _dedupe_repeated_segments(
    segments: Iterable[Dict[str, object]], max_repeats: int = 2
) -> List[Dict[str, object]]:
    """兩層過濾 Whisper 在靜音/配樂段落的重複幻覺：

    1. 段內自我重複：單一 segment 文字自己重複數十次 → 收斂成 max_repeats 次。
    2. 跨段連續重複：相鄰 segment 文字相同且連續超過 max_repeats 次 → 捨棄多餘的。

    正常的歌詞疊句或口語重複（通常 1~2 次）不會被誤殺。
    """
    deduped: List[Dict[str, object]] = []
    run_key: Optional[str] = None
    run_count = 0
    for seg in segments:
        raw_text = str(seg.get("text", "") or "").strip()
        text = _collapse_repeated_phrase(raw_text, keep=max_repeats)
        if text != raw_text:
            seg = dict(seg)
            seg["text"] = text
        key = _REPEAT_STRIP_PATTERN.sub("", text)
        if key and key == run_key:
            run_count += 1
        else:
            run_key = key
            run_count = 1
        if not key or run_count <= max_repeats:
            deduped.append(seg)
    return deduped


def _slice_long_sentence(sentence: str, max_chars: int) -> List[str]:
    """硬切過長字句時優先在空白處斷開，避免切在詞中間造成 TTS 唸出怪音。

    沒有標點的長文字（例如 Whisper 中文輸出）常常整段都超過 max_chars，
    若找不到空白可斷（例如真的整段無空格），才退回原本的硬切字元數。
    """
    pieces: List[str] = []
    remaining = sentence
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        split_at = window.rfind(" ")
        if split_at <= 0:
            split_at = max_chars
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _configure_runtime_environment() -> None:
    base_path = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)

    for directory in [base_path, os.path.join(base_path, "ffmpeg")]:
        suffix = ".exe" if sys.platform == "win32" else ""
        if all(os.path.isfile(os.path.join(directory, name + suffix)) for name in ("ffmpeg", "ffprobe")):
            current_path = os.environ.get("PATH", "")
            if directory not in current_path.split(os.pathsep):
                os.environ["PATH"] = os.pathsep.join([directory, current_path]) if current_path else directory
            break

    model_dir = os.path.join(base_path, "models")
    if os.path.isdir(model_dir) and not os.environ.get("WHISPER_MODEL_DIR"):
        os.environ["WHISPER_MODEL_DIR"] = model_dir


_configure_runtime_environment()
_ensure_stdio()



class WhisperApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("上字幕｜本機轉錄・字幕整理")
        self.root.geometry("860x820")
        self.root.minsize(720, 760)
        self.faster_model_cache: Dict[str, object] = {}
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.tts_stop_event = threading.Event()
        self.tts_worker_thread: Optional[threading.Thread] = None

        self.audio_path_var = tk.StringVar()
        self.model_var = tk.StringVar(value=MODEL_OPTIONS[1])
        self.status_var = tk.StringVar(value="選擇音檔或影片後點擊開始")
        self.output_paths_var = tk.StringVar(value="")
        self.word_timestamps_var = tk.BooleanVar(value=True)
        self.language_var = tk.StringVar(value="自動偵測")
        self.converter_cache: Dict[str, object] = {}
        self.opencc_unavailable_notified = False
        self.edge_tts_unavailable_notified = False
        self.tts_voice_label_var = tk.StringVar(value="台灣女聲・活潑")
        self.tts_rate_var = tk.StringVar(value="+5%")
        self.tts_pitch_var = tk.StringVar(value="+2Hz")
        self.tts_output_path_var = tk.StringVar()
        self.tts_status_var = tk.StringVar(value="貼上文字後點擊產生音檔")
        self.tts_result_var = tk.StringVar(value="")
        self.tts_optimize_var = tk.BooleanVar(value=True)
        self.tts_script_mode_var = tk.StringVar(value="原文直出")
        self.tts_preview_mode_var = tk.StringVar(value="目前輸出預覽")

        self.lyrics_audio_path_var = tk.StringVar()
        self.lyrics_model_var = tk.StringVar(value=MODEL_OPTIONS[2])  # medium 預設
        self.lyrics_language_var = tk.StringVar(value="自動偵測")
        self.lyrics_use_demucs_var = tk.BooleanVar(value=True)
        self.lyrics_status_var = tk.StringVar(value="選擇音樂檔後點擊開始")
        self.lyrics_output_paths_var = tk.StringVar(value="")
        self.lyrics_stop_event = threading.Event()
        self.lyrics_worker_thread: Optional[threading.Thread] = None

        self.layout_source = []
        self.layout_result = []
        self.layout_dirty = False
        self.layout_history = []
        self.last_saved_path = ""
        self.recovery_failed = False
        data_dir = os.environ.get("WHISPER_PREVIEW_DATA_DIR") or os.environ.get("WHISPER_APP_DATA_DIR")
        if not data_dir:
            data_dir = str(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "Library" / "Application Support"))) / "WhisperGUI-SubtitlePreview")
        self.recovery_path = Path(data_dir) / "recovery" / "subtitle.json"
        self.layout_source_path = ""
        self.layout_preset_var = tk.StringVar(value="橫式講座／長片")
        self.layout_chars_var = tk.StringVar(value="18")
        self.layout_lines_var = tk.StringVar(value="2")
        self.layout_terms_var = tk.StringVar()
        self.layout_clauses_var = tk.BooleanVar(value=True)
        self.layout_status_var = tk.StringVar(value="完成轉錄後會帶入原稿，也可匯入既有 SRT 或字幕專案。")
        self.layout_capability_var = tk.StringVar(value="先選音檔完成轉錄，或匯入字幕；本機處理，不上傳影音。")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(0, self._restore_recovery)

    def _layout_settings(self):
        try:
            chars, lines = int(self.layout_chars_var.get()), int(self.layout_lines_var.get())
            if not 4 <= chars <= 80 or not 1 <= lines <= 4:
                raise ValueError
        except ValueError:
            chars, lines = 18, 2
        return {"max_chars": chars, "max_lines": lines,
                "split_clauses": self.layout_clauses_var.get(),
                "preset": self.layout_preset_var.get(), "terms": self.layout_terms_var.get()}

    def _autosave_layout(self):
        if not self.layout_result:
            return
        try:
            document = json.loads(serialize_document(self.layout_result, kind="layout",
                settings=self._layout_settings(), original_segments=self.layout_source))
            document["source_path"] = self.layout_source_path
            write_recovery(self.recovery_path, json.dumps(document, ensure_ascii=False))
        except (ValueError, OSError) as exc:
            if not self.recovery_failed:
                self.recovery_failed = True
                messagebox.showwarning("自動備份未成功", f"目前修改仍在畫面上，請立即保存字幕專案。\n{exc}")

    def _restore_recovery(self):
        if not self.recovery_path.exists():
            return
        try:
            cues, document = read_document(self.recovery_path, with_metadata=True)
            if not messagebox.askyesno("繼續上次工作", "找到上次工作的本機備份。要恢復字幕、換行與設定嗎？"):
                return
            self._set_layout_source(document.get("original_segments", cues), document.get("source_path", "字幕"),
                                    formatted=cues, settings=document.get("settings"))
            self.layout_dirty = True
            self.notebook.select(3)
            self.layout_status_var.set("已恢復本機備份；完成後請按「儲存進度，下次繼續」。")
        except (ValueError, OSError) as exc:
            messagebox.showwarning("備份無法恢復", f"請匯入先前保存的字幕專案。\n{exc}")

    def _confirm_project_saved(self, title):
        if not self.layout_dirty:
            return True
        answer = messagebox.askyesnocancel(title,
            "字幕專案尚未保存（匯出 SRT 不等於保存專案）。\n是：先保存專案；否：繼續但不保存；取消：留在目前工作。")
        if answer is None:
            return False
        if answer:
            return self.save_layout_project()
        return True

    def on_close(self):
        if getattr(self, "layout_editing", False):
            messagebox.showinfo("字幕編輯中", "請先在編輯視窗保存或取消這次修改，再關閉工具。")
            return
        running = any(thread and thread.is_alive() for thread in
                      (self.worker_thread, self.lyrics_worker_thread, self.tts_worker_thread))
        if running:
            messagebox.showinfo("工作尚未完成", "請先按停止，等工作停止後再關閉，避免失去尚未完成的轉錄。")
            return
        if not self._confirm_project_saved("關閉字幕工具"):
            return
        self._autosave_layout()
        self.root.destroy()

    def _remember_layout(self):
        if self.layout_result:
            self.layout_history.append((copy.deepcopy(self.layout_result),
                                        list(getattr(self, "layout_auto_warnings", [])), self._layout_settings()))
            self.layout_history = self.layout_history[-50:]

    def undo_layout(self):
        if not self.layout_history:
            self.layout_status_var.set("目前沒有可復原的操作。")
            return
        self.layout_result, self.layout_auto_warnings, settings = self.layout_history.pop()
        self.layout_chars_var.set(str(settings["max_chars"]))
        self.layout_lines_var.set(str(settings["max_lines"]))
        self.layout_preset_var.set(settings["preset"])
        self.layout_terms_var.set(settings["terms"])
        self.layout_clauses_var.set(settings.get("split_clauses", True))
        self.layout_dirty = True
        self._refresh_layout_tree()
        self._autosave_layout()
        self.layout_status_var.set("已復原上一步；本機備份已更新，完成後請保存專案。")

    def _open_path(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            else:
                subprocess.Popen(["open", str(path)])
        except OSError as exc:
            messagebox.showerror("無法開啟", f"請手動開啟：{path}\n{exc}")

    def open_start_guide(self):
        resources = os.environ.get("SHANGZIMU_RESOURCES")
        self._open_path(Path(resources) / "guide-full.txt" if resources else Path(__file__).resolve().parent.parent / "新手指南.txt")

    def open_saved_folder(self):
        if self.last_saved_path:
            self._open_path(Path(self.last_saved_path).parent)
        else:
            self.layout_status_var.set("請先另存 SRT 或保存字幕專案。")

    def load_layout_example(self):
        resources = os.environ.get("SHANGZIMU_RESOURCES")
        path = Path(resources) / "examples" / "排版示範.json" if resources else Path(__file__).resolve().parent.parent / "範例" / "排版示範.json"
        try:
            self._set_layout_source(read_document(path), str(path))
            self.notebook.select(3)
        except (ValueError, OSError) as exc:
            messagebox.showerror("無法開啟範例", str(exc))

    def _notify_runtime_warning(self, message: str, *, flag: str) -> None:
        if getattr(self, flag, False):
            return
        setattr(self, flag, True)
        self._update_status(message)
        self.root.after(0, lambda: messagebox.showwarning("提醒", message))

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.bind_all("<<Paste>>", self._handle_global_paste, add="+")
        for _seq in ("<Command-v>", "<Command-V>", "<Meta-v>", "<Meta-V>",
                     "<Control-v>", "<Control-V>", "<Shift-Insert>"):
            self.root.bind_all(_seq, self._handle_global_paste, add="+")

        container = ttk.Frame(self.root, padding=16)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        help_row = ttk.Frame(container)
        help_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(help_row, text="① 選檔轉錄 → ② 整理字幕 → ③ 匯出 SRT", foreground="#444").pack(side="left")
        ttk.Button(help_row, text="使用說明", command=self.open_start_guide).pack(side="right")
        ttk.Button(help_row, text="先試範例", command=self.load_layout_example).pack(side="right", padx=6)

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        transcribe_frame = ttk.Frame(self.notebook, padding=20)
        transcribe_frame.columnconfigure(1, weight=1)
        transcribe_frame.rowconfigure(7, weight=1)
        self.notebook.add(transcribe_frame, text="語音轉字幕")
        self._build_transcribe_tab(transcribe_frame)

        tts_outer = ttk.Frame(self.notebook)
        tts_outer.columnconfigure(0, weight=1)
        tts_outer.rowconfigure(0, weight=1)
        self.notebook.add(tts_outer, text="文字轉語音（雲端，傳送前確認）")
        self._build_tts_scrollable_tab(tts_outer)

        lyrics_frame = ttk.Frame(self.notebook, padding=20)
        lyrics_frame.columnconfigure(1, weight=1)
        lyrics_frame.rowconfigure(7, weight=1)
        self.notebook.add(lyrics_frame, text="歌詞辨識（本機）")
        self._build_lyrics_tab(lyrics_frame)

        layout_frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(layout_frame, text="字幕排版")
        self._build_layout_tab(layout_frame)

    def _build_layout_tab(self, frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        toolbar = ttk.Frame(frame)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="匯入 SRT／字幕專案", command=self.import_layout_source).pack(side="left")
        self.layout_preset_box = ttk.Combobox(toolbar, textvariable=self.layout_preset_var,
            values=["橫式講座／長片", "直式短片"], state="readonly", width=18)
        self.layout_preset_box.pack(side="left", padx=8)
        self.layout_preset_box.bind("<<ComboboxSelected>>", self._layout_preset_changed)
        ttk.Label(toolbar, text="每行字數").pack(side="left")
        ttk.Spinbox(toolbar, from_=4, to=80, textvariable=self.layout_chars_var, width=4).pack(side="left", padx=4)
        ttk.Label(toolbar, text="每塊行數").pack(side="left")
        ttk.Spinbox(toolbar, from_=1, to=4, textvariable=self.layout_lines_var, width=3).pack(side="left", padx=4)

        terms = ttk.Frame(frame)
        terms.grid(row=1, column=0, sticky="ew", pady=8)
        terms.columnconfigure(1, weight=1)
        ttk.Label(terms, text="不拆開的詞：").grid(row=0, column=0)
        ttk.Entry(terms, textvariable=self.layout_terms_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(terms, text="例如：講者姓名、公司名（用逗號分隔）").grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(terms, text="依自然語句切成依序出現的字幕（需要可靠細部時間）",
                        variable=self.layout_clauses_var).grid(row=2, column=1, sticky="w", pady=4)
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        groups = [
            ("① 自動整理", [
                ("自動切句與換行", self.apply_subtitle_layout, "依上方設定整理；重新整理會回到原稿。", "apply"),
                ("撤銷剛才的修改", self.undo_layout, "回到上一次修改前。", "undo")]),
            ("② 檢查與修改", [
                ("修改這句字幕", self.edit_layout_cue, "改文字、換行；有細部時間才能拆成兩句。", "edit"),
                ("與下一句合併", self.merge_layout_cue, "把選取字幕與下一句合成一段。", "merge"),
                ("查看需要確認的字幕", self.show_layout_warnings, "檢查過長、顯示太快等提醒。", "warnings")]),
            ("③ 完成與儲存", [
                ("匯出給剪輯軟體（SRT）", self.export_layout_srt, "給 Final Cut Pro／剪映使用；不等於儲存進度。", "export"),
                ("儲存進度，下次繼續", self.save_layout_project, "保存文字、設定與細部時間（JSON）。", "save"),
                ("查看已儲存的檔案", self.open_saved_folder, "打開目前字幕的輸出資料夾。", "folder")])]
        self.layout_action_buttons = {}
        self.layout_step_groups = []
        self.layout_step_summaries = []
        self.layout_action_help = groups
        for column, (title, actions) in enumerate(groups):
            buttons.columnconfigure(column, weight=1, uniform="layout_steps")
            group = ttk.Labelframe(buttons, text=title, padding=2)
            group.grid(row=0, column=column, sticky="nsew", padx=(0, 6))
            group.columnconfigure(0, weight=1)
            self.layout_step_groups.append(group)
            for row, (label, command, explanation, key) in enumerate(actions):
                button = ttk.Button(group, text=label, command=command)
                button.grid(row=row * 2, column=0, sticky="ew", pady=(2, 0))
                self.layout_action_buttons[key] = button
            summary = ttk.Label(group, text=["重新整理會回到原稿，可撤銷修改。",
                "先選一句再修改；細部時間齊全才能切句。",
                "SRT 給剪輯軟體；JSON 保存編輯進度。" ][column], wraplength=250)
            self.layout_step_summaries.append(summary)
        ttk.Button(buttons, text="按鈕用途說明", command=self.show_layout_action_help).grid(
            row=1, column=2, sticky="e", pady=(4, 0))
        self.layout_selection_hint = tk.StringVar(value="請先在下方選一句字幕，再修改或合併。")
        self.layout_hint_label = ttk.Label(buttons, textvariable=self.layout_selection_hint, wraplength=450)
        self.layout_hint_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.layout_capability_var,
                  wraplength=680).grid(row=3, column=0, sticky="w", pady=(0, 8))

        panes = ttk.Frame(frame)
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=2)
        panes.rowconfigure(0, weight=1)
        panes.grid(row=4, column=0, sticky="nsew")
        original = ttk.Labelframe(panes, text="原稿", padding=6)
        original.grid_propagate(False)
        original.rowconfigure(0, weight=1)
        original.columnconfigure(0, weight=1)
        self.layout_original_preview = tk.Text(original, wrap="word", width=28, height=6, state=tk.DISABLED)
        self.layout_original_preview.grid(row=0, column=0, sticky="nsew")
        original_scroll = ttk.Scrollbar(original, command=self.layout_original_preview.yview)
        original_scroll.grid(row=0, column=1, sticky="ns")
        self.layout_original_preview.config(yscrollcommand=original_scroll.set)
        original.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        formatted = ttk.Labelframe(panes, text="排版結果（雙擊可編輯）", padding=6)
        formatted.grid_propagate(False)
        formatted.rowconfigure(0, weight=1)
        formatted.columnconfigure(0, weight=1)
        self.layout_tree = ttk.Treeview(formatted, columns=("time", "text"), show="headings", selectmode="browse", height=6)
        self.layout_tree.heading("time", text="時間")
        self.layout_tree.heading("text", text="字幕（↵ 表示換行）")
        self.layout_tree.column("time", width=120, minwidth=100, stretch=False)
        self.layout_tree.column("text", width=290, minwidth=180)
        self.layout_tree.grid(row=0, column=0, sticky="nsew")
        result_scroll = ttk.Scrollbar(formatted, command=self.layout_tree.yview)
        result_scroll.grid(row=0, column=1, sticky="ns")
        self.layout_tree.config(yscrollcommand=result_scroll.set)
        self.layout_tree.bind("<Double-1>", lambda _event: self.edit_layout_cue())
        self.layout_tree.bind("<<TreeviewSelect>>", self.preview_selected_layout)
        ttk.Label(formatted, text="所選字幕預覽（實際換行；不是影片版面模擬）").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.layout_selected_preview = tk.Text(formatted, height=2, wrap="word", state=tk.DISABLED)
        self.layout_selected_preview.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        formatted.grid(row=0, column=1, sticky="nsew")
        ttk.Label(frame, textvariable=self.layout_status_var, wraplength=680).grid(row=5, column=0, sticky="w", pady=8)
        self._update_layout_action_states()
        self.layout_controls = buttons
        self.layout_content_panes = panes
        buttons.bind("<Configure>", self._resize_layout_controls)

    def _resize_layout_controls(self, event):
        if event.widget is not self.layout_controls:
            return
        narrow = event.width < 850
        for column in range(3):
            self.layout_controls.columnconfigure(column, weight=1 if not narrow or column == 0 else 0,
                                                  uniform="" if narrow else "layout_steps")
        for index, group in enumerate(self.layout_step_groups):
            group.grid(row=index if narrow else 0, column=0 if narrow else index,
                       columnspan=3 if narrow else 1, sticky="ew", padx=(0, 0 if narrow else 6))
            actions = self.layout_action_help[index][1]
            for column in range(3):
                group.columnconfigure(column, weight=1 if narrow or column == 0 else 0,
                                      uniform="actions" if narrow else "")
            for position, (_, _, _, key) in enumerate(actions):
                self.layout_action_buttons[key].grid(row=0 if narrow else position,
                    column=position if narrow else 0, sticky="ew", padx=(0, 4), pady=2)
            summary = self.layout_step_summaries[index]
            summary.config(wraplength=max(100, event.width - 40 if narrow else event.width // 3 - 36))
            if narrow:
                summary.grid_remove()
            else:
                summary.grid(row=len(actions), column=0, columnspan=1, sticky="ew", pady=(2, 0))
        footer_row = 3 if narrow else 1
        self.layout_hint_label.grid(row=footer_row)
        self.layout_hint_label.config(wraplength=max(100, event.width - 170))
        for child in self.layout_controls.winfo_children():
            if isinstance(child, ttk.Button):
                child.grid(row=footer_row)

    def show_layout_action_help(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("字幕按鈕用途說明")
        dialog.geometry("600x480")
        dialog.minsize(360, 280)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        text = tk.Text(dialog, wrap="word", padx=12, pady=12)
        text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(dialog, command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.config(yscrollcommand=scroll.set)
        for title, actions in self.layout_action_help:
            text.insert(tk.END, title + "\n")
            for label, _, explanation, _ in actions:
                text.insert(tk.END, label + "\n" + explanation + "\n\n")
        text.config(state=tk.DISABLED)
        ttk.Button(dialog, text="關閉", command=dialog.destroy).grid(row=1, column=0, pady=8)

    def _update_layout_action_states(self):
        if not hasattr(self, "layout_action_buttons"):
            return
        selection = self.layout_tree.selection()
        index = int(selection[0]) if selection else -1
        selected = 0 <= index < len(self.layout_result)
        states = {"apply": bool(self.layout_source), "edit": selected,
                  "merge": selected and index + 1 < len(self.layout_result),
                  "export": bool(self.layout_result), "save": bool(self.layout_result),
                  "warnings": bool(self.layout_result),
                  "undo": bool(getattr(self, "layout_history", []))}
        for key, enabled in states.items():
            self.layout_action_buttons[key].config(state="normal" if enabled else "disabled")
        hint = "請先在下方選一句字幕，再修改或合併。"
        if selected:
            hint = f"已選第 {index + 1} 句，可修改文字與換行。"
            if index + 1 == len(self.layout_result):
                hint += " 這是最後一句，沒有下一句可合併。"
        self.layout_selection_hint.set(hint)

    def _layout_preset_changed(self, _event=None) -> None:
        self.layout_chars_var.set("10" if self.layout_preset_var.get() == "直式短片" else "18")
        self.layout_lines_var.set("2")

    def _set_layout_source(self, cues, path, formatted=None, settings=None) -> None:
        if not cues:
            return False
        if getattr(self, "layout_editing", False):
            self.pending_layout_source = (cues, path, formatted, settings)
            return
        if not self._confirm_project_saved("替換目前排版"):
            return False
        self.layout_dirty = False
        self.layout_history = []
        self.last_saved_path = ""
        self.layout_source = cues
        self.layout_source_path = path
        self.layout_result = []
        self.layout_auto_warnings = []
        if isinstance(settings, dict):
            self.layout_chars_var.set(str(settings.get("max_chars", 18)))
            self.layout_lines_var.set(str(settings.get("max_lines", 2)))
            self.layout_preset_var.set(settings.get("preset", "橫式講座／長片"))
            self.layout_terms_var.set(settings.get("terms", ""))
            self.layout_clauses_var.set(settings.get("split_clauses", True))
        self.layout_original_preview.config(state=tk.NORMAL)
        self.layout_original_preview.delete("1.0", tk.END)
        self.layout_original_preview.insert(tk.END, serialize_srt(cues))
        self.layout_original_preview.config(state=tk.DISABLED)
        self._refresh_layout_tree()
        if formatted is None:
            self.apply_subtitle_layout()
        else:
            self.layout_result = formatted
            self.layout_auto_warnings = []
            self._refresh_layout_tree()
            self.layout_status_var.set("已恢復保存的排版與手動修改；原稿仍可重新套用。")
            self._autosave_layout()
        return True

    def import_layout_source(self) -> None:
        path = filedialog.askopenfilename(title="匯入字幕", filetypes=[("字幕或字幕專案", "*.srt *.json")])
        if not path:
            return
        try:
            cues, metadata = read_document(path, with_metadata=True)
            if metadata.get("kind") == "layout":
                self._set_layout_source(metadata.get("original_segments", cues), path,
                    formatted=cues, settings=metadata.get("settings"))
            else:
                self._set_layout_source(cues, path)
            self.notebook.select(3)
        except (ValueError, OSError) as exc:
            messagebox.showerror("無法匯入", str(exc))

    def apply_subtitle_layout(self) -> None:
        if not self.layout_source:
            self.layout_status_var.set("請先完成轉錄或匯入字幕。")
            return
        if self.layout_dirty and not messagebox.askyesno("重新排版", "重新套用會捨棄尚未保存的手動修改，回到原稿。繼續嗎？"):
            return
        try:
            chars, lines = int(self.layout_chars_var.get()), int(self.layout_lines_var.get())
            if not 4 <= chars <= 80 or not 1 <= lines <= 4:
                raise ValueError("每行字數需為 4–80，每塊行數需為 1–4。")
            terms = [term.strip() for term in re.split(r"[,，\n]", self.layout_terms_var.get()) if term.strip()]
            cues, warnings = layout_subtitles(self.layout_source, chars, lines, terms,
                                             split_clauses=self.layout_clauses_var.get())
        except ValueError as exc:
            messagebox.showerror("排版設定", str(exc))
            return
        self._remember_layout()
        self.layout_result = cues
        self.layout_dirty = True
        self.layout_auto_warnings = warnings
        self._refresh_layout_tree()
        warnings = self.layout_warnings
        summary = f"原稿 {len(self.layout_source)} 塊 → 排版 {len(cues)} 塊。"
        if warnings:
            summary += f" {len(warnings)} 項需確認：" + "；".join(warnings[:3])
            if len(warnings) > 3:
                summary += "（可按「查看需要確認的字幕」）"
        self.layout_status_var.set(summary)
        self._autosave_layout()

    def _refresh_layout_tree(self) -> None:
        self._recheck_layout_warnings()
        for item in self.layout_tree.get_children():
            self.layout_tree.delete(item)
        for i, cue in enumerate(self.layout_result):
            time = f"{cue['start']:.2f}–{cue['end']:.2f} 秒"
            source = cue.get("source_index", i + 1)
            review = any(f"原稿第 {source} 塊" in w for w in getattr(self, "layout_warnings", []))
            display = ("[需確認] " if review else "") + cue["text"].replace("\n", " ↵ ")
            self.layout_tree.insert("", "end", iid=str(i), values=(time, display),
                tags=("review",) if review else ())
        self.layout_tree.tag_configure("review", background="#fff0c2")
        if self.layout_result:
            self.layout_tree.selection_set("0")
        self.preview_selected_layout()
        if not self.layout_result:
            self.layout_capability_var.set("先匯入字幕或完成轉錄，再整理換行。")
        elif not any(has_split_timing(cue) for cue in self.layout_result):
            self.layout_capability_var.set("此字幕沒有可靠細部時間：可換行／合併，不能切成多塊。需要切句請回到語音轉字幕重新轉錄。")
        else:
            self.layout_capability_var.set("可依語音時間切句；黃色項目需確認。完成後先儲存進度，再匯出給剪輯軟體。")

    def preview_selected_layout(self, _event=None):
        self._update_layout_action_states()
        selection = self.layout_tree.selection()
        text = "請選擇一塊字幕，查看實際換行。"
        if selection and int(selection[0]) < len(self.layout_result):
            text = self.layout_result[int(selection[0])]["text"]
        self.layout_selected_preview.config(state=tk.NORMAL)
        self.layout_selected_preview.delete("1.0", tk.END)
        self.layout_selected_preview.insert("1.0", text)
        self.layout_selected_preview.config(state=tk.DISABLED)

    def _recheck_layout_warnings(self) -> None:
        warnings = list(getattr(self, "layout_auto_warnings", []))
        try:
            chars, lines = int(self.layout_chars_var.get()), int(self.layout_lines_var.get())
            if not 4 <= chars <= 80 or not 1 <= lines <= 4:
                raise ValueError
        except ValueError:
            self.layout_warnings = ["排版設定無效，請修正每行字數與行數。"]
            return
        previous_end = 0
        for index, cue in enumerate(self.layout_result, 1):
            source = cue.get("source_index", index)
            label = f"原稿第 {source} 塊（排版第 {index} 塊）"
            parts = cue["text"].splitlines()
            if any(len(line) > chars for line in parts):
                warnings.append(label + "：有一行超過設定字數。")
            if len(parts) > lines:
                warnings.append(label + "：行數超過設定。")
            duration = cue["end"] - cue["start"]
            if duration <= 0:
                warnings.append(label + "：時間範圍無效。")
            elif len(re.sub(r"\s", "", cue["text"])) / duration > 15:
                warnings.append(label + "：閱讀速度偏快，請預覽確認。")
            if cue["start"] < previous_end:
                warnings.append(label + "：與前一塊時間重疊，請確認原稿。")
            previous_end = max(previous_end, cue["end"])
        self.layout_warnings = list(dict.fromkeys(warnings))

    def show_layout_warnings(self) -> None:
        warnings = getattr(self, "layout_warnings", [])
        dialog = tk.Toplevel(self.root)
        dialog.title("排版檢查清單")
        dialog.geometry("620x380")
        preview = tk.Text(dialog, wrap="word", padx=10, pady=10)
        preview.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(dialog, command=preview.yview)
        scroll.pack(side="right", fill="y")
        preview.config(yscrollcommand=scroll.set)
        preview.insert("1.0", "\n\n".join(warnings) if warnings else "自動排版未發現需提示的項目；仍建議在剪輯工具預覽。")
        preview.config(state=tk.DISABLED)

    def edit_layout_cue(self) -> None:
        if getattr(self, "layout_editing", False):
            return
        selection = self.layout_tree.selection()
        if not selection:
            self.layout_status_var.set("請先選取一塊排版字幕。")
            return
        index = int(selection[0])
        cue = self.layout_result[index]
        dialog = tk.Toplevel(self.root)
        dialog.title(f"編輯第 {index + 1} 塊字幕")
        dialog.geometry("540x260")
        dialog.transient(self.root)
        dialog.grab_set()
        self.layout_editing = True

        def closed(event):
            if event.widget is not dialog:
                return
            self.layout_editing = False
            pending = getattr(self, "pending_layout_source", None)
            if pending:
                self.pending_layout_source = None
                self.root.after(0, lambda: self._set_layout_source(*pending))

        dialog.bind("<Destroy>", closed)
        ttk.Label(dialog, text="Enter 插入換行。手動切句：把游標放在兩句之間，再按下方按鈕。",
                  wraplength=510).pack(padx=12, pady=10)
        editor = tk.Text(dialog, wrap="word", height=6)
        editor.pack(fill="both", expand=True, padx=12)
        editor.insert("1.0", cue["text"])
        editor.focus_set()

        def cancel_edit():
            if editor.get("1.0", "end-1c") != cue["text"] and not messagebox.askyesno(
                    "取消這次修改", "編輯視窗有尚未保存的文字。確定放棄這次修改？", parent=dialog):
                return
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", cancel_edit)

        def save(split=False):
            text = editor.get("1.0", "end-1c").strip()
            if not text or re.search(r"\n\s*\n", text):
                messagebox.showwarning("字幕文字", "請保留文字，且不要加入空白行。", parent=dialog)
                return
            edited = dict(cue, text=text)
            try:
                if split:
                    cursor = len(editor.get("1.0", "insert"))
                    leading = len(editor.get("1.0", "end-1c")) - len(editor.get("1.0", "end-1c").lstrip())
                    replacements = split_subtitle_at(edited, cursor - leading)
                else:
                    replacements = [edited]
            except ValueError as exc:
                messagebox.showwarning("無法安全切句", str(exc), parent=dialog)
                return
            self._remember_layout()
            self.layout_result[index:index + 1] = replacements
            self.layout_dirty = True
            self.layout_auto_warnings = []
            self._refresh_layout_tree()
            self._autosave_layout()
            self.layout_status_var.set("已手動修改；請另存 SRT 或保存專案。重新套用會回到原稿。")
            dialog.destroy()

        row = ttk.Frame(dialog)
        row.pack(pady=10)
        ttk.Button(row, text="保存文字／換行", command=save).pack(side="left", padx=4)
        split_button = ttk.Button(row, text="在游標處切成兩塊", command=lambda: save(True))
        split_button.pack(side="left", padx=4)
        if not has_split_timing(cue):
            split_button.config(state=tk.DISABLED)
            ttk.Label(dialog, text="這塊字幕沒有細部時間，只能改文字／換行；需要切句請重新轉錄。",
                      wraplength=510).pack(padx=12, pady=4)
        ttk.Button(row, text="取消", command=cancel_edit).pack(side="left", padx=4)

    def merge_layout_cue(self) -> None:
        selection = self.layout_tree.selection()
        if not selection or int(selection[0]) + 1 >= len(self.layout_result):
            self.layout_status_var.set("請選取一塊後面仍有字幕的項目。")
            return
        index = int(selection[0])
        first, second = self.layout_result[index:index + 2]
        self._remember_layout()
        merged = dict(first, end=max(first["end"], second["end"]), text=first["text"] + "\n" + second["text"])
        merged["words"] = list(first.get("words", [])) + list(second.get("words", []))
        self.layout_result[index:index + 2] = [merged]
        self.layout_dirty = True
        self.layout_auto_warnings = []
        self._refresh_layout_tree()
        self._autosave_layout()
        self.layout_status_var.set("已合併；請確認行數與閱讀速度，再另存。")

    def _save_layout(self, project=False) -> None:
        if not self.layout_result:
            self.layout_status_var.set("尚無排版結果可保存。")
            return False
        self._recheck_layout_warnings()
        suffix = ".json" if project else ".srt"
        stem = os.path.splitext(os.path.basename(self.layout_source_path))[0] or "字幕"
        folder = str(Path(self.layout_source_path).parent) if self.layout_source_path else str(Path.home() / "Documents")
        if not os.access(folder, os.W_OK):
            folder = str(Path.home() / "Documents")
        try:
            suggested = next_revision_path(Path(folder) / (stem + "_排版" + suffix))
        except (ValueError, OSError) as exc:
            messagebox.showerror("無法準備檔名", f"請選擇可寫入的資料夾或另一個檔名。\n{exc}")
            return False
        path = filedialog.asksaveasfilename(title="保存可繼續編輯的字幕專案" if project else "匯出給剪輯工具的 SRT",
            defaultextension=suffix, initialfile=suggested.name, initialdir=str(suggested.parent),
            filetypes=[("字幕專案" if project else "SRT 字幕", "*" + suffix)])
        if not path:
            return False
        try:
            settings = self._layout_settings()
            content = serialize_document(self.layout_result, kind="layout", settings=settings,
                original_segments=self.layout_source) if project else serialize_srt(self.layout_result)
            save_new_file(path, content)
        except FileExistsError:
            messagebox.showwarning("請另存新檔", "此檔案已存在，請換一個檔名。試用版不覆蓋原稿或先前版本。")
            return False
        except (ValueError, OSError) as exc:
            messagebox.showerror("無法保存", str(exc))
            return False
        self.last_saved_path = path
        self.layout_status_var.set(f"{'專案已保存，可下次繼續編輯' if project else 'SRT 已匯出，請到剪輯工具預覽；專案仍需另外保存'}：{path}")
        if project:
            self.layout_dirty = False
        self._autosave_layout()
        warnings = getattr(self, "layout_warnings", [])
        if warnings:
            self.show_layout_warnings()
        return True

    def export_layout_srt(self) -> None:
        return self._save_layout(False)

    def save_layout_project(self) -> None:
        return self._save_layout(True)

    def _build_tts_scrollable_tab(self, parent: ttk.Frame) -> None:
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        tts_frame = ttk.Frame(canvas, padding=20)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        window_id = canvas.create_window((0, 0), window=tts_frame, anchor="nw")

        def update_scrollregion(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_inner_frame(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        tts_frame.bind("<Configure>", update_scrollregion)
        canvas.bind("<Configure>", resize_inner_frame)

        def on_mousewheel(event) -> str:
            if canvas.winfo_height() >= tts_frame.winfo_reqheight():
                return "break"
            delta = event.delta
            if delta == 0 and getattr(event, "num", None) in (4, 5):
                delta = 120 if event.num == 4 else -120
            if delta:
                canvas.yview_scroll(int(-delta / 120), "units")
            return "break"

        canvas.bind("<MouseWheel>", on_mousewheel)
        canvas.bind("<Button-4>", on_mousewheel)
        canvas.bind("<Button-5>", on_mousewheel)
        tts_frame.bind("<MouseWheel>", on_mousewheel)
        tts_frame.bind("<Button-4>", on_mousewheel)
        tts_frame.bind("<Button-5>", on_mousewheel)

        canvas.bind("<FocusIn>", lambda _e: self.tts_text.focus_set() if hasattr(self, "tts_text") else None)
        canvas.bind("<Button-1>", lambda _e: self.tts_text.focus_set() if hasattr(self, "tts_text") else None)

        tts_frame.columnconfigure(1, weight=1)
        tts_frame.rowconfigure(5, weight=1)
        tts_frame.rowconfigure(8, weight=1)
        self._build_tts_tab(tts_frame)

    def _build_transcribe_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="音檔/影片：").grid(row=0, column=0, sticky="w")
        audio_entry = ttk.Entry(frame, textvariable=self.audio_path_var)
        audio_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(frame, text="瀏覽", command=self.browse_file).grid(
            row=0, column=2, sticky="e"
        )

        ttk.Label(frame, text="辨識設定：").grid(
            row=1, column=0, sticky="w", pady=(12, 0)
        )
        model_box = ttk.Combobox(
            frame,
            textvariable=self.model_var,
            values=MODEL_OPTIONS,
            state="readonly",
        )
        model_box.grid(row=1, column=1, sticky="w", pady=(12, 0))
        self.model_combo = model_box

        options_frame = ttk.Labelframe(
            frame,
            text="最佳化選項",
            padding=12,
        )
        options_frame.grid(row=2, column=0, columnspan=3, sticky="ew")
        options_frame.columnconfigure(1, weight=1)

        desc = (
            "small 模型已內建；其他模型首次使用下載後即可離線。影音辨識在本機，不上傳影音。"
            " 長影片可能需要較久，完成後會自動進入字幕排版。"
        )
        ttk.Label(options_frame, text=desc, wraplength=640, foreground="#444").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        lang_row = ttk.Frame(options_frame)
        lang_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(lang_row, text="語言：").pack(side="left")
        lang_box = ttk.Combobox(
            lang_row,
            textvariable=self.language_var,
            values=["自動偵測", "繁體中文 (zh)", "英文 (en)", "日文 (ja)", "韓文 (ko)"],
            state="readonly",
            width=14,
        )
        lang_box.pack(side="left")
        ttk.Label(lang_row, text="  （若輸出亂碼或重複文字，請指定語言）", foreground="#666").pack(side="left")

        ttk.Checkbutton(
            options_frame,
            text="取得細部語音時間，供字幕自動切句（稍增運算時間）",
            variable=self.word_timestamps_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        ttk.Label(
            options_frame,
            text="中文內容會自動轉繁體；外語內容維持原文。",
            foreground="#444",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=3, pady=(16, 16), sticky="ew")
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(button_row, text="開始轉錄", command=self.start_transcription)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.stop_button = ttk.Button(
            button_row, text="停止", command=self.stop_transcription, state=tk.DISABLED
        )
        self.stop_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(frame, textvariable=self.status_var, foreground="#1c5f2c").grid(
            row=4, column=0, columnspan=3, sticky="w"
        )

        ttk.Label(frame, textvariable=self.output_paths_var, wraplength=640).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(8, 12)
        )

        next_row = ttk.Frame(frame)
        next_row.grid(row=6, column=0, columnspan=3, sticky="ew")
        ttk.Label(next_row, text="轉錄結果預覽：").pack(side="left")
        ttk.Button(next_row, text="整理字幕 →", command=lambda: self.notebook.select(3)).pack(side="right")
        ttk.Button(next_row, text="開啟轉錄資料夾", command=self.open_transcription_folder).pack(side="right", padx=4)

        self.preview = tk.Text(frame, wrap="word", height=12)
        self.preview.grid(row=7, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(7, weight=1)
        self.preview.config(state=tk.DISABLED)

        ttk.Label(
            frame,
            text=f"by {APP_SIGNATURE}",
            foreground="#666",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(frame, text="清除", command=self.clear_preview).grid(
            row=8, column=2, sticky="e", pady=(8, 0)
        )

    def _build_lyrics_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="音樂檔：").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.lyrics_audio_path_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(frame, text="瀏覽", command=self.browse_lyrics_file).grid(
            row=0, column=2, sticky="e"
        )

        ttk.Label(frame, text="Whisper 模型：").grid(
            row=1, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Combobox(
            frame,
            textvariable=self.lyrics_model_var,
            values=MODEL_OPTIONS,
            state="readonly",
        ).grid(row=1, column=1, sticky="w", pady=(12, 0))

        options_frame = ttk.Labelframe(frame, text="選項", padding=12)
        options_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        options_frame.columnconfigure(1, weight=1)

        lang_row = ttk.Frame(options_frame)
        lang_row.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(lang_row, text="語言：").pack(side="left")
        ttk.Combobox(
            lang_row,
            textvariable=self.lyrics_language_var,
            values=["自動偵測", "繁體中文 (zh)", "英文 (en)", "日文 (ja)", "韓文 (ko)"],
            state="readonly",
            width=14,
        ).pack(side="left")

        ttk.Checkbutton(
            options_frame,
            text="先分離人聲（本機；降低伴奏干擾，仍需校對歌詞）",
            variable=self.lyrics_use_demucs_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w")

        ttk.Label(
            options_frame,
            text="輸出：.txt 純歌詞、.lrc 帶時間戳歌詞、.srt 字幕",
            foreground="#444",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=3, pady=(16, 16), sticky="ew")
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        self.lyrics_start_button = ttk.Button(
            button_row, text="開始辨識", command=self.start_lyrics
        )
        self.lyrics_start_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.lyrics_stop_button = ttk.Button(
            button_row, text="停止", command=self.stop_lyrics, state=tk.DISABLED
        )
        self.lyrics_stop_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(frame, textvariable=self.lyrics_status_var, foreground="#1c5f2c").grid(
            row=4, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(frame, textvariable=self.lyrics_output_paths_var, wraplength=640).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(8, 12)
        )
        ttk.Label(frame, text="歌詞預覽：").grid(row=6, column=0, columnspan=3, sticky="w")

        self.lyrics_preview = tk.Text(frame, wrap="word", height=12)
        self.lyrics_preview.grid(row=7, column=0, columnspan=3, sticky="nsew")
        self.lyrics_preview.config(state=tk.DISABLED)

        ttk.Label(frame, text=f"by {APP_SIGNATURE}", foreground="#666").grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        ttk.Button(frame, text="清除", command=self.clear_lyrics_preview).grid(
            row=8, column=2, sticky="e", pady=(8, 0)
        )

    def browse_lyrics_file(self) -> None:
        path = filedialog.askopenfilename(
            title="選擇音樂檔",
            filetypes=[("音訊/影片", MEDIA_FILE_PATTERNS), ("所有檔案", "*.*")],
        )
        if path:
            self.lyrics_audio_path_var.set(path)

    def start_lyrics(self) -> None:
        audio_path = self.lyrics_audio_path_var.get().strip()
        if not audio_path:
            messagebox.showwarning("提醒", "請先選擇音樂檔")
            return
        if not os.path.isfile(audio_path):
            messagebox.showerror("錯誤", "找不到指定的檔案，請重新選擇")
            return
        if self.lyrics_worker_thread and self.lyrics_worker_thread.is_alive():
            messagebox.showinfo("提醒", "目前已有辨識正在進行")
            return

        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("請稍候", "語音轉字幕正在使用辨識引擎，完成或停止後再辨識歌詞。")
            return
        self.lyrics_output_dir = os.path.dirname(os.path.abspath(audio_path))
        if not os.access(self.lyrics_output_dir, os.W_OK):
            folder = filedialog.askdirectory(title="影音資料夾不能寫入，請選擇歌詞儲存資料夾")
            if not folder:
                return
            self.lyrics_output_dir = folder

        self.lyrics_stop_event.clear()
        self._update_lyrics_control_states(True)
        worker = threading.Thread(
            target=self._lyrics_worker,
            args=(audio_path, self.lyrics_model_var.get(), self.lyrics_use_demucs_var.get()),
            daemon=True,
        )
        self.lyrics_worker_thread = worker
        worker.start()

    def stop_lyrics(self) -> None:
        if not self.lyrics_worker_thread or not self.lyrics_worker_thread.is_alive():
            return
        self.lyrics_stop_event.set()
        self._update_lyrics_status("停止中；若正在準備模型，將於該步驟結束後停止。")
        self.lyrics_stop_button.config(state=tk.DISABLED)

    def _update_lyrics_status(self, message: str) -> None:
        self.root.after(0, lambda: self.lyrics_status_var.set(message))

    def _update_lyrics_control_states(self, running: bool) -> None:
        start_state = tk.DISABLED if running else tk.NORMAL
        stop_state = tk.NORMAL if running else tk.DISABLED
        self.lyrics_start_button.config(state=start_state)
        self.lyrics_stop_button.config(state=stop_state)

    def _update_lyrics_preview(self, text: str) -> None:
        def update() -> None:
            self.lyrics_preview.config(state=tk.NORMAL)
            self.lyrics_preview.delete("1.0", tk.END)
            self.lyrics_preview.insert(tk.END, text.strip() or "(空白)")
            self.lyrics_preview.config(state=tk.DISABLED)
        self.root.after(0, update)

    def clear_lyrics_preview(self) -> None:
        self.lyrics_preview.config(state=tk.NORMAL)
        self.lyrics_preview.delete("1.0", tk.END)
        self.lyrics_preview.config(state=tk.DISABLED)
        self.lyrics_output_paths_var.set("")
        self.lyrics_status_var.set("已清除，可重新選擇音樂檔")

    def _lyrics_worker(self, audio_path: str, model_name: str, use_demucs: bool) -> None:
        tmp_dir = None
        try:
            vocal_path = audio_path

            if use_demucs:
                self._update_lyrics_status("正在本機分離人聲，音樂不會上傳...")
                tmp_dir = tempfile.mkdtemp(prefix="shangzimu-vocals-")
                vocal_path = os.path.join(tmp_dir, "vocals.wav")
                resources = Path(os.environ.get("SHANGZIMU_RESOURCES", ""))
                worker = resources / "workers" / "vocals" / ("VocalWorker.exe" if sys.platform == "win32" else "VocalWorker")
                if not worker.is_file():
                    raise RuntimeError("安裝包缺少人聲分離工具，請重新安裝完整版本。")
                ffmpeg = self._find_ffmpeg()
                if not ffmpeg:
                    raise RuntimeError("安裝包缺少音訊工具，請重新安裝完整版本。")
                # A separate executable owns PyTorch and a separate Python
                # runtime. Never invoke the GUI executable as a Python CLI.
                with open(os.path.join(tmp_dir, "worker.log"), "w+", encoding="utf-8") as log:
                    worker_env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
                    proc = subprocess.Popen([str(worker), "--input", audio_path,
                        "--output", vocal_path, "--models", str(resources / "models" / "vocals"),
                        "--ffmpeg", ffmpeg], stdout=log, stderr=log, env=worker_env)
                    try:
                        while proc.poll() is None:
                            if self.lyrics_stop_event.wait(0.2):
                                raise SystemExit
                        if proc.returncode != 0:
                            log.seek(0)
                            raise RuntimeError("本機人聲分離失敗：" + log.read()[-3000:])
                    finally:
                        if proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait(timeout=5)
                if not os.path.isfile(vocal_path):
                    raise RuntimeError("人聲分離未產生有效音訊。")
                self._update_lyrics_status("人聲分離完成，載入模型中...")
            else:
                self._update_lyrics_status("載入模型中...")

            if self.lyrics_stop_event.is_set():
                raise SystemExit

            self._update_lyrics_status("辨識歌詞中（使用 CPU），請稍候...")
            lang_selection = self.lyrics_language_var.get()
            opts: Dict[str, object] = dict(DEFAULT_OPTIONS)
            if lang_selection != "自動偵測":
                opts["language"] = lang_selection.split("(")[-1].rstrip(")")

            def _lyrics_progress(cur: float, total: float) -> None:
                pct = int(cur / total * 100) if total else 0
                self._update_lyrics_status(
                    f"辨識歌詞中… {pct}%（{_format_hms(cur)} / {_format_hms(total)}）"
                )

            raw_result = self._transcribe(
                vocal_path, model_name, opts, self.lyrics_stop_event, _lyrics_progress
            )
            result = self._normalize_chinese_output(raw_result)

            if self.lyrics_stop_event.is_set():
                raise SystemExit

            output_paths, preview_text = self._write_lyrics_outputs(audio_path, result)
            detected_lang = result.get("language") or "unknown"
            self._update_lyrics_status(f"完成！偵測語言：{detected_lang}. 檔案已產生。")
            self.root.after(0, lambda: self.lyrics_output_paths_var.set(
                "\n".join(f"{k.upper()}: {v}" for k, v in output_paths.items())
            ))
            self._update_lyrics_preview(preview_text)

        except SystemExit:
            self._update_lyrics_status("已停止。")
            self.root.after(0, lambda: self.lyrics_output_paths_var.set(""))
            self._update_lyrics_preview("")
        except Exception as exc:  # pylint: disable=broad-except
            self._update_lyrics_status("發生錯誤")
            msg = str(exc)
            self.root.after(0, lambda: messagebox.showerror("錯誤", msg))
        finally:
            if tmp_dir and os.path.isdir(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)
            self.lyrics_worker_thread = None
            self.lyrics_stop_event.clear()
            self.root.after(0, lambda: self._update_lyrics_control_states(False))

    def _write_lyrics_outputs(
        self, audio_path: str, result: Dict[str, object]
    ) -> "tuple[Dict[str, str], str]":
        base_dir = getattr(self, 'lyrics_output_dir', None) or os.path.dirname(audio_path)
        audio_name = os.path.splitext(os.path.basename(audio_path))[0]
        detected_lang = str(result.get("language", "") or "").lower() or "auto"

        # 歌詞的副歌/疊句正常就會重複 3~6 次，門檻要比語音轉字幕（預設 2 次）寬鬆，
        # 只擋真正失控的幻覺循環（實測過的案例是連續 14 次），不要誤刪真正的副歌歌詞
        segments = _dedupe_repeated_segments(result.get("segments", []) or [], max_repeats=8)
        segments = _clamp_segment_durations(segments)

        text_lines = [str(seg.get("text", "") or "").strip() for seg in segments]
        text_lines = [line for line in text_lines if line]
        text_content = "\n".join(text_lines) if text_lines else result.get("text", "").strip()

        output_dir = Path(tempfile.mkdtemp(prefix=f"{audio_name}_lyrics_", dir=base_dir))
        txt_path = str(output_dir / f"{audio_name}_lyrics_{detected_lang}.txt")
        save_new_file(txt_path, text_content + "\n")

        lrc_path = str(output_dir / f"{audio_name}_lyrics_{detected_lang}.lrc")
        save_new_file(lrc_path, _format_lrc(segments))

        srt_path = str(output_dir / f"{audio_name}_lyrics_{detected_lang}.srt")
        save_new_file(srt_path, _format_srt(segments))

        return {"txt": txt_path, "lrc": lrc_path, "srt": srt_path}, text_content

    def _build_tts_tab(self, frame: ttk.Frame) -> None:
        ttk.Label(frame, text="聲音：").grid(row=0, column=0, sticky="w")
        voice_box = ttk.Combobox(
            frame,
            textvariable=self.tts_voice_label_var,
            values=list(TTS_VOICE_OPTIONS.keys()),
            state="readonly",
            width=20,
        )
        voice_box.grid(row=0, column=1, sticky="w")

        controls = ttk.Frame(frame)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)
        controls.columnconfigure(5, weight=1)

        ttk.Label(controls, text="語速：").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.tts_rate_var,
            values=TTS_RATE_OPTIONS,
            state="readonly",
            width=8,
        ).grid(row=0, column=1, sticky="w", padx=(0, 24))

        ttk.Label(controls, text="音高：").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.tts_pitch_var,
            values=TTS_PITCH_OPTIONS,
            state="readonly",
            width=8,
        ).grid(row=0, column=3, sticky="w")

        ttk.Label(controls, text="輸出模式：").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(
            controls,
            textvariable=self.tts_script_mode_var,
            values=list(TTS_SCRIPT_MODE_TARGETS.keys()),
            state="readonly",
            width=18,
        ).grid(row=1, column=1, sticky="w", pady=(10, 0))

        ttk.Label(frame, text="輸出檔案：").grid(row=2, column=0, sticky="w", pady=(12, 0))
        output_row = ttk.Frame(frame)
        output_row.grid(row=2, column=1, sticky="ew", pady=(12, 0))
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.tts_output_path_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(output_row, text="選擇", command=self.choose_tts_output_path).grid(
            row=0, column=1, sticky="e"
        )

        ttk.Label(
            frame,
            text="貼上旁白文字後即可輸出 mp3。可保留原文，或先產生 2 分鐘精簡版 / 短影音版，再做朗讀優化。",
            foreground="#444",
            wraplength=700,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 8))

        ttk.Label(frame, text="文字內容：").grid(row=4, column=0, columnspan=2, sticky="w")
        import_row = ttk.Frame(frame)
        import_row.grid(row=4, column=1, sticky="e", pady=(0, 4))
        ttk.Button(import_row, text="匯入文字檔", command=self.import_tts_text_file).grid(
            row=0, column=0, sticky="e"
        )
        ttk.Button(import_row, text="貼上剪貼簿", command=self.paste_tts_text).grid(
            row=0, column=1, sticky="e", padx=(8, 0)
        )
        ttk.Button(import_row, text="清除", command=self.clear_tts_inputs).grid(
            row=0, column=2, sticky="e", padx=(8, 0)
        )
        self.tts_text = tk.Text(frame, wrap="word", height=16)
        self.tts_text.grid(row=5, column=0, columnspan=2, sticky="nsew")
        self._bind_text_shortcuts(self.tts_text)

        optimize_row = ttk.Frame(frame)
        optimize_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        optimize_row.columnconfigure(3, weight=1)
        ttk.Checkbutton(
            optimize_row,
            text="朗讀優化",
            variable=self.tts_optimize_var,
            command=self.refresh_tts_preview,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(optimize_row, text="預覽模式：").grid(row=0, column=1, sticky="w", padx=(12, 6))
        ttk.Combobox(
            optimize_row,
            textvariable=self.tts_preview_mode_var,
            values=["原文預覽", "目前輸出預覽"],
            state="readonly",
            width=12,
        ).grid(row=0, column=2, sticky="w")
        self.tts_script_mode_var.trace_add("write", lambda *_args: self.refresh_tts_preview())
        self.tts_preview_mode_var.trace_add("write", lambda *_args: self.refresh_tts_preview())
        ttk.Button(optimize_row, text="更新預覽", command=self.refresh_tts_preview).grid(
            row=0, column=3, sticky="e"
        )

        ttk.Label(frame, text="預覽內容：").grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.tts_preview_text = tk.Text(frame, wrap="word", height=10)
        self.tts_preview_text.grid(row=8, column=0, columnspan=2, sticky="nsew")
        self.tts_preview_text.config(state=tk.DISABLED)

        tts_button_row = ttk.Frame(frame)
        tts_button_row.grid(row=9, column=0, columnspan=2, pady=(16, 12), sticky="ew")
        tts_button_row.columnconfigure(0, weight=1)
        tts_button_row.columnconfigure(1, weight=1)
        self.tts_start_button = ttk.Button(
            tts_button_row, text="產生音檔", command=self.start_tts_generation
        )
        self.tts_start_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.tts_stop_button = ttk.Button(
            tts_button_row, text="停止", command=self.stop_tts_generation, state=tk.DISABLED
        )
        self.tts_stop_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(frame, textvariable=self.tts_status_var, foreground="#1c5f2c").grid(
            row=10, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, textvariable=self.tts_result_var, wraplength=700).grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            frame,
            text=f"by {APP_SIGNATURE}",
            foreground="#666",
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="選擇音檔或影片",
            filetypes=[
                ("音訊/影片檔案", MEDIA_FILE_PATTERNS),
                ("所有檔案", "*.*"),
            ],
        )
        if path:
            self.audio_path_var.set(path)

    def choose_tts_output_path(self) -> None:
        initial_name = self._default_tts_filename()
        path = filedialog.asksaveasfilename(
            title="選擇輸出音檔位置",
            defaultextension=".mp3",
            initialfile=initial_name,
            filetypes=[("MP3 音檔", "*.mp3")],
        )
        if path:
            self.tts_output_path_var.set(path)

    def import_tts_text_file(self) -> None:
        path = filedialog.askopenfilename(
            title="選擇文字檔",
            filetypes=[
                ("文字檔", "*.txt *.md *.text"),
                ("所有檔案", "*.*"),
            ],
        )
        if not path:
            return
        content: Optional[str] = None
        # 依序嘗試：utf-8-sig（含/不含 BOM 的 UTF-8）→ cp950（台灣繁體 Big5）→ gb18030（簡體）
        for encoding in ("utf-8-sig", "cp950", "gb18030"):
            try:
                with open(path, "r", encoding=encoding, errors="strict") as handle:
                    content = handle.read()
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if content is None:
            messagebox.showerror(
                "錯誤",
                "無法辨識文字檔編碼，請將檔案另存為 UTF-8 格式後再試。",
            )
            return

        self.tts_text.delete("1.0", tk.END)
        self.tts_text.insert("1.0", content)
        self.tts_text.focus_set()
        self._update_tts_status(f"已匯入文字檔：{os.path.basename(path)}")
        self.refresh_tts_preview()

    def start_transcription(self) -> None:
        audio_path = self.audio_path_var.get().strip()
        if not audio_path:
            messagebox.showwarning("提醒", "請先選擇要轉錄的音檔或影片")
            return
        if not os.path.isfile(audio_path):
            messagebox.showerror("錯誤", "找不到指定的檔案，請重新選擇")
            return

        model_name = self.model_var.get()

        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("提醒", "目前已經有轉錄正在進行")
            return

        if self.lyrics_worker_thread and self.lyrics_worker_thread.is_alive():
            messagebox.showinfo("請稍候", "歌詞辨識正在使用辨識引擎，完成或停止後再轉錄。")
            return

        self.transcribe_output_dir = os.path.dirname(os.path.abspath(audio_path))
        if not os.access(self.transcribe_output_dir, os.W_OK):
            messagebox.showinfo("選擇字幕儲存位置", "影音所在資料夾不能寫入。請選擇字幕的儲存資料夾，影音不會被修改。")
            folder = filedialog.askdirectory(title="選擇字幕儲存資料夾")
            if not folder:
                return
            self.transcribe_output_dir = folder

        self.stop_event.clear()
        self._update_control_states(True)
        self._update_status("載入模型中（使用 CPU），請稍候...")
        worker = threading.Thread(
            target=self._transcribe_worker,
            args=(audio_path, model_name, self.word_timestamps_var.get()),
            daemon=True,
        )
        self.worker_thread = worker
        worker.start()

    def stop_transcription(self) -> None:
        if not self.worker_thread or not self.worker_thread.is_alive():
            return
        self.stop_event.set()
        self._update_status("已請求停止，將在目前片段完成後停止（大檔案可能需稍等）...")
        self.stop_button.config(state=tk.DISABLED)

    def _interrupt_thread(self, thread: threading.Thread, exc_type=SystemExit) -> None:
        ident = thread.ident
        if ident is None:
            return
        result = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(ident), ctypes.py_object(exc_type)
        )
        if result > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(ident), None)

    def _update_control_states(self, running: bool) -> None:
        start_state = tk.DISABLED if running else tk.NORMAL
        stop_state = tk.NORMAL if running else tk.DISABLED
        self.start_button.config(state=start_state)
        self.stop_button.config(state=stop_state)

    def _update_tts_control_states(self, running: bool) -> None:
        start_state = tk.DISABLED if running else tk.NORMAL
        stop_state = tk.NORMAL if running else tk.DISABLED
        self.tts_start_button.config(state=start_state)
        self.tts_stop_button.config(state=stop_state)

    def _update_status(self, message: str) -> None:
        self.root.after(0, lambda: self.status_var.set(message))

    def _update_outputs_label(self, paths: Dict[str, str]) -> None:
        if not paths:
            self.root.after(0, lambda: self.output_paths_var.set(""))
            return
        pretty = "\n".join(f"{kind.upper()}: {path}" for kind, path in paths.items())
        self.root.after(0, lambda: self.output_paths_var.set(pretty))

    def _update_preview(self, text: str) -> None:
        def update() -> None:
            self.preview.config(state=tk.NORMAL)
            self.preview.delete("1.0", tk.END)
            self.preview.insert(tk.END, text.strip() or "(空白)")
            self.preview.config(state=tk.DISABLED)

        self.root.after(0, update)

    def _update_tts_status(self, message: str) -> None:
        self.root.after(0, lambda: self.tts_status_var.set(message))

    def _update_tts_result(self, message: str) -> None:
        self.root.after(0, lambda: self.tts_result_var.set(message))

    def _update_tts_preview(self, text: str) -> None:
        def update() -> None:
            self.tts_preview_text.config(state=tk.NORMAL)
            self.tts_preview_text.delete("1.0", tk.END)
            self.tts_preview_text.insert(tk.END, text.strip() or "(空白)")
            self.tts_preview_text.config(state=tk.DISABLED)

        self.root.after(0, update)

    def _on_tab_changed(self, _event=None) -> None:
        if hasattr(self, "tts_text") and self.notebook.index("current") == 1:
            self.root.after(50, self.tts_text.focus_set)

    def _bind_text_shortcuts(self, widget: tk.Text) -> None:
        widget.bind("<<Paste>>", lambda _e: self.root.after(10, self.refresh_tts_preview), add="+")

    def _handle_global_paste(self, _event=None) -> str | None:
        if self.notebook.index("current") != 1:
            return None
        self.paste_tts_text()
        return "break"

    def paste_tts_text(self) -> None:
        try:
            clipboard = self.root.clipboard_get()
        except Exception:  # pylint: disable=broad-except
            clipboard = ""
        if not clipboard:
            messagebox.showwarning("提醒", "剪貼簿目前沒有可貼上的文字")
            return

        target = self.root.focus_get()
        if not isinstance(target, tk.Text):
            target = self.tts_text

        try:
            if target.tag_ranges(tk.SEL):
                target.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            pass

        target.insert(tk.INSERT, clipboard)
        target.focus_set()
        self.refresh_tts_preview()

    def _get_model(self, model_name: str) -> object:
        raise RuntimeError(self._model_repair_message("本機辨識引擎尚未就緒。"))

    def _model_repair_message(self, reason: str) -> str:
        if os.environ.get("SHANGZIMU_RESOURCES"):
            return reason + "請關閉上字幕，使用完整安裝包重新安裝；不要刪除已保存的字幕專案。若仍失敗，請將此錯誤訊息提供給管理者；影音不會上傳。"
        return reason + "請關閉程式，連網重新雙擊「▶ 啟動 Whisper」修復；影音不會上傳。"

    def _get_faster_model(self, model_name: str) -> object:
        if model_name not in self.faster_model_cache:
            # Switching models must release the previous engine before loading
            # another large model, rather than retaining all five in RAM.
            self.faster_model_cache.clear()
            from full_model_manager import resolve_model
            directory = resolve_model(model_name,
                os.environ.get("WHISPER_FASTER_MODEL_DIR", ""),
                Path(os.environ.get("WHISPER_APP_DATA_DIR", tempfile.gettempdir())) / "models",
                progress=self._update_status)
            if self.stop_event.is_set() and self.worker_thread is threading.current_thread():
                raise SystemExit
            self._update_status(
                "載入本機語音模型中（不會連網下載），接著開始轉錄…"
            )
            try:
                self.faster_model_cache[model_name] = _FasterWhisperModel(
                    str(directory), device="cpu", compute_type=FASTER_COMPUTE_TYPE, local_files_only=True
                )
            except Exception as exc:
                raise RuntimeError(self._model_repair_message("模型無法載入。")) from exc
        return self.faster_model_cache[model_name]

    def open_transcription_folder(self):
        folder = getattr(self, "transcription_folder", "")
        if folder:
            self._open_path(folder)
        else:
            self._update_status("完成轉錄後，即可開啟新產生的字幕資料夾。")

    def _show_transcription_layout(self, cues, audio_path):
        if self._set_layout_source(cues, audio_path):
            self.notebook.select(3)

    def _transcribe(
        self,
        audio_path: str,
        model_name: str,
        options: Dict[str, object],
        stop_event: Optional[threading.Event] = None,
        progress_cb: Optional[callable] = None,
    ) -> Dict[str, object]:
        """統一的轉錄入口：優先用 faster-whisper（含 VAD），否則退回 openai-whisper。

        兩條路徑都回傳同樣結構的 dict（language / text / segments），
        後續的繁化、去重、輸出流程完全不用改。
        progress_cb(current_sec, total_sec) 用來即時回報進度（只有 faster-whisper 支援）。
        """
        if FASTER_WHISPER_AVAILABLE:
            return self._faster_transcribe(
                audio_path, model_name, options, stop_event, progress_cb
            )
        self._get_model(model_name)  # Friendly repair error; never download a fallback model.

    def _faster_transcribe(
        self,
        audio_path: str,
        model_name: str,
        options: Dict[str, object],
        stop_event: Optional[threading.Event] = None,
        progress_cb: Optional[callable] = None,
    ) -> Dict[str, object]:
        """用 faster-whisper 轉錄，並把結果轉成 openai-whisper 的 dict 結構。

        關鍵是 vad_filter=True：先用 Silero VAD 切掉靜音段，講者走動/換場/沉默
        的空檔根本不進模型，從源頭消除「我只想說×45」那類靜音幻覺。
        """
        opts = dict(options)
        language = opts.get("language")
        word_timestamps = bool(opts.get("word_timestamps", False))
        model = self._get_faster_model(model_name)
        segments_gen, info = model.transcribe(
            audio_path,
            language=language,
            temperature=opts.get("temperature", TRANSCRIBE_TEMPERATURE),
            condition_on_previous_text=opts.get("condition_on_previous_text", False),
            no_speech_threshold=opts.get("no_speech_threshold", 0.4),
            compression_ratio_threshold=opts.get("compression_ratio_threshold", 2.0),
            log_prob_threshold=opts.get("logprob_threshold", -1.0),
            vad_filter=True,
            vad_parameters=VAD_PARAMETERS,
            word_timestamps=word_timestamps,
            beam_size=5,
        )

        total_dur = float(getattr(info, "duration", 0.0) or 0.0)
        segments: List[Dict[str, object]] = []
        text_parts: List[str] = []
        for seg in segments_gen:  # 惰性 generator，實際運算在這裡逐段發生
            if stop_event is not None and stop_event.is_set():
                raise SystemExit
            seg_dict: Dict[str, object] = {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
            }
            if word_timestamps and getattr(seg, "words", None):
                seg_dict["words"] = [
                    {
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability,
                    }
                    for w in seg.words
                ]
            segments.append(seg_dict)
            text_parts.append(seg.text)
            if progress_cb is not None and total_dur > 0:
                progress_cb(min(float(seg.end or 0.0), total_dur), total_dur)

        return {
            "language": info.language,
            "text": "".join(text_parts),
            "segments": segments,
        }

    def _build_options(self, word_timestamps: bool) -> Dict[str, object]:
        opts: Dict[str, object] = dict(DEFAULT_OPTIONS)
        if word_timestamps:
            opts["word_timestamps"] = True
        lang_selection = self.language_var.get()
        if lang_selection != "自動偵測":
            # 取出括號內的語言代碼，例如 "中文 (zh)" → "zh"
            lang_code = lang_selection.split("(")[-1].rstrip(")")
            opts["language"] = lang_code
        return opts

    @staticmethod
    def _is_chinese_language(lang: str) -> bool:
        normalized = (lang or "").strip().lower()
        return normalized.startswith("zh") or normalized in {"chinese", "cn"}

    def _to_traditional(self, text: str) -> str:
        if not text:
            return text
        if OpenCC is None:
            self._notify_runtime_warning(
                "未安裝 OpenCC，中文可能維持簡體字型。請先重新執行 01 安裝流程。",
                flag="opencc_unavailable_notified",
            )
            return text
        config = "s2twp"
        converter = self.converter_cache.get(config)
        if converter is None:
            converter = OpenCC(config)
            self.converter_cache[config] = converter
        return converter.convert(text)

    def _normalize_chinese_output(self, result: Dict[str, object]) -> Dict[str, object]:
        detected_lang = str(result.get("language", "") or "")
        if not self._is_chinese_language(detected_lang):
            return result

        converted: Dict[str, object] = dict(result)
        raw_segments = result.get("segments", []) or []
        converted_segments: List[Dict[str, object]] = []

        converted["text"] = self._to_traditional(str(result.get("text", "") or ""))
        for raw_seg in raw_segments:
            if not isinstance(raw_seg, dict):
                continue
            seg = dict(raw_seg)
            seg["text"] = self._to_traditional(str(raw_seg.get("text", "") or ""))
            raw_words = raw_seg.get("words")
            if raw_words:
                converted_words = []
                for raw_word in raw_words:
                    if isinstance(raw_word, dict):
                        w = dict(raw_word)
                        w["word"] = self._to_traditional(str(raw_word.get("word", "") or ""))
                        converted_words.append(w)
                    else:
                        converted_words.append(raw_word)
                seg["words"] = converted_words
            converted_segments.append(seg)
        converted["segments"] = converted_segments
        return converted

    @staticmethod
    def _sanitize_filename(text: str) -> str:
        normalized = re.sub(r"\s+", "_", text.strip())
        normalized = re.sub(r"[^\w\u4e00-\u9fff_-]", "", normalized)
        return normalized[:24] or "tts_output"

    @staticmethod
    def _read_digits(value: str) -> str:
        return "".join(TTS_DIGIT_MAP.get(char, char) for char in value if char.isdigit())

    @staticmethod
    def _format_spoken_hour(hour_text: str, meridiem: str) -> str:
        hour = int(hour_text)
        meridiem = (meridiem or "").strip()

        if meridiem in {"下午", "晚上"} and hour > 12:
            hour -= 12
        elif meridiem == "中午" and hour == 0:
            hour = 12
        elif meridiem == "凌晨" and hour == 12:
            hour = 0

        return f"{hour}點"

    def _spoken_time(self, match: re.Match[str]) -> str:
        start_meridiem = match.group("start_meridiem") or ""
        start_hour = match.group("start_hour")
        start_minute = match.group("start_minute")
        end_meridiem = match.group("end_meridiem") or start_meridiem
        end_hour = match.group("end_hour")
        end_minute = match.group("end_minute")

        start_text = f"{start_meridiem}{self._format_spoken_hour(start_hour, start_meridiem)}"
        if start_minute != "00":
            start_text += f"{int(start_minute)}分"

        if not end_hour:
            return start_text

        end_text = f"{end_meridiem}{self._format_spoken_hour(end_hour, end_meridiem)}"
        if end_minute and end_minute != "00":
            end_text += f"{int(end_minute)}分"
        return f"{start_text}到{end_text}"

    def _spoken_phone(self, match: re.Match[str]) -> str:
        parts = re.split(r"[-\s]+", match.group(0).strip())
        return "，".join(self._read_digits(part) for part in parts if part)

    def _spoken_url(self, match: re.Match[str]) -> str:
        url = match.group(0).strip().rstrip(".,);]")
        spoken = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
        spoken = spoken.replace("www.", "www ")
        spoken = spoken.replace(".", " 點 ")
        spoken = spoken.replace("/", " slash ")
        spoken = spoken.replace("-", " dash ")
        spoken = spoken.replace("_", " underscore ")
        spoken = spoken.replace("#", " 井號 ")
        spoken = spoken.replace("?", " 問號 ")
        spoken = spoken.replace("=", " 等於 ")
        spoken = spoken.replace("&", " 和 ")
        spoken = re.sub(r'\s+', ' ', spoken).strip()
        return f"網址 {spoken}"

    def _normalize_tts_paragraphs(self, text: str) -> str:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        paragraphs: List[str] = []
        current: List[str] = []

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                continue
            current.append(line)
        if current:
            paragraphs.append(" ".join(current))

        cleaned = []
        for paragraph in paragraphs:
            paragraph = re.sub(r"[ \t]+", " ", paragraph).strip()
            paragraph = re.sub(r"([。！？!?；;])(?=[^\s\n])", r"\1\n", paragraph)
            paragraph = re.sub(r"([：:])(?!\d)(?=[^\s\n])", r"\1\n", paragraph)
            cleaned.append(paragraph)
        return "\n\n".join(cleaned)

    def _optimize_tts_text(self, text: str) -> str:
        optimized = self._normalize_tts_paragraphs(text)
        optimized = re.sub(
            r"(?<!\w)"
            r"(?P<start_meridiem>凌晨|清晨|早上|上午|中午|下午|晚上)?\s*"
            r"(?P<start_hour>[01]?\d|2[0-3])[:：](?P<start_minute>[0-5]\d)"
            r"(?:\s*[~-]\s*(?P<end_meridiem>凌晨|清晨|早上|上午|中午|下午|晚上)?\s*"
            r"(?P<end_hour>[01]?\d|2[0-3])[:：](?P<end_minute>[0-5]\d))?",
            self._spoken_time,
            optimized,
        )
        optimized = re.sub(
            r"(?:\+886[-\s]?)?(?:0\d{1,2}|9\d{2})[-\s]?\d{3,4}[-\s]?\d{3,4}",
            self._spoken_phone,
            optimized,
        )
        optimized = re.sub(r"https?://\S+|www\.\S+", self._spoken_url, optimized)
        optimized = re.sub(r"\n{3,}", "\n\n", optimized)
        return optimized.strip()

    @staticmethod
    def _split_tts_sentences(text: str) -> List[str]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = [part.strip() for part in normalized.split("\n") if part.strip()]
        sentences: List[str] = []
        for paragraph in paragraphs:
            parts = [item.strip() for item in re.split(r"(?<=[。！？!?])\s*", paragraph) if item.strip()]
            sentences.extend(parts or [paragraph])
        return sentences

    @staticmethod
    def _extract_chinese_terms(text: str) -> List[str]:
        stop_terms = {
            "我們", "你們", "大家", "這次", "這場", "這個", "這些", "一個", "一起", "可以",
            "如果", "以及", "還有", "不是", "就是", "不只", "現場", "活動", "分享",
        }
        terms = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
        return [term for term in terms if term not in stop_terms]

    def _score_tts_sentence(self, sentence: str, index: int, total: int, term_weights: Dict[str, int]) -> int:
        score = 0
        length = len(sentence)
        if index == 0:
            score += 8
        if index >= max(total - 2, 0):
            score += 5
        if index <= 2:
            score += 2
        if 12 <= length <= 60:
            score += 3
        elif length > 100:
            score -= 2

        strong_patterns = [
            r"\d+月\d+日",
            r"(週|星期)[一二三四五六日天]",
            r"\d+[:：]\d+",
            r"\d+點",
            r"市.+區.+路",
            r"\d+樓",
            r"報名|參加|到場|歡迎|邀請|現場見",
            r"作者|老師|主講|分享",
            r"贈送|送出|加碼|摸彩|抽獎|好禮",
            r"下午茶|晚餐|美食",
        ]
        keyword_patterns = [
            r"活動|講座|商會|分會|旁白",
            r"收穫|驚喜|啟發|成長|突破",
            r"工具|方法|筆記|思維|行動",
        ]
        for pattern in strong_patterns:
            if re.search(pattern, sentence):
                score += 6
        for pattern in keyword_patterns:
            if re.search(pattern, sentence):
                score += 3

        if re.search(r"\d", sentence):
            score += 2

        for term, weight in term_weights.items():
            if term in sentence:
                score += weight
        return score

    def _condense_tts_text(self, text: str, target_chars: int) -> str:
        normalized = self._normalize_tts_paragraphs(text)
        if not normalized:
            return ""
        if len(normalized) <= target_chars:
            return normalized

        sentences = self._split_tts_sentences(normalized)
        if len(sentences) <= 2:
            return normalized[:target_chars].strip()

        term_counts: Dict[str, int] = {}
        for sentence in sentences:
            for term in self._extract_chinese_terms(sentence):
                term_counts[term] = term_counts.get(term, 0) + 1
        term_weights = {
            term: min(count, 3)
            for term, count in term_counts.items()
            if count >= 2
        }

        required_patterns = [
            r"\d+月\d+日|(?:週|星期)[一二三四五六日天]|\d+[:：]\d+|\d+點",
            r"市.+區.+路|\d+樓|地址|地點",
            r"報名|參加|歡迎|邀請|現場見|不要錯過",
        ]

        selected_indexes = set()
        total_length = 0

        for pattern in required_patterns:
            for index, sentence in enumerate(sentences):
                if index in selected_indexes:
                    continue
                if re.search(pattern, sentence):
                    selected_indexes.add(index)
                    total_length += len(sentence)
                    break

        ranked = sorted(
            (
                (
                    self._score_tts_sentence(sentence, index, len(sentences), term_weights),
                    index,
                    sentence,
                )
                for index, sentence in enumerate(sentences)
                if index not in selected_indexes
            ),
            key=lambda item: (-item[0], item[1]),
        )

        min_sentences = 3 if len(sentences) >= 3 else len(sentences)
        soft_limit = int(target_chars * 1.15)
        for _score, index, sentence in ranked:
            need_more_sentences = len(selected_indexes) < min_sentences
            fits_budget = total_length + len(sentence) <= soft_limit
            if need_more_sentences or fits_budget:
                selected_indexes.add(index)
                total_length += len(sentence)

        if not selected_indexes:
            selected_indexes.add(0)

        ordered = sorted(selected_indexes)
        condensed = "\n".join(sentences[index] for index in ordered).strip()

        if len(condensed) > soft_limit:
            trimmed_indexes = ordered[:]
            while len(trimmed_indexes) > min_sentences:
                candidate = trimmed_indexes[-1]
                if re.search(required_patterns[2], sentences[candidate]):
                    break
                trimmed_indexes.pop()
                condensed = "\n".join(sentences[index] for index in trimmed_indexes).strip()
                if len(condensed) <= soft_limit:
                    break
        return condensed

    def _build_tts_script(self, text: str) -> str:
        normalized = self._normalize_tts_paragraphs(text)
        target_chars = TTS_SCRIPT_MODE_TARGETS.get(self.tts_script_mode_var.get())
        if target_chars:
            return self._condense_tts_text(normalized, target_chars)
        return normalized

    def _get_tts_effective_text(self) -> str:
        text = self.tts_text.get("1.0", tk.END).strip()
        if not text:
            return ""
        text = self._build_tts_script(text)
        if self.tts_optimize_var.get():
            return self._optimize_tts_text(text)
        return text

    def refresh_tts_preview(self) -> None:
        source = self.tts_text.get("1.0", tk.END).strip()
        if not source:
            self._update_tts_preview("")
            return
        if self.tts_preview_mode_var.get() == "原文預覽":
            preview_text = source
        else:
            preview_text = self._get_tts_effective_text()
        self._update_tts_preview(preview_text)

    def _default_tts_filename(self) -> str:
        sample = self.tts_text.get("1.0", "2.0").strip() if hasattr(self, "tts_text") else ""
        mode = self.tts_script_mode_var.get()
        suffix_map = {
            "原文直出": "",
            "2 分鐘精簡版": "_2min",
            "短影音版": "_short",
        }
        suffix = suffix_map.get(mode, "")
        return f"{self._sanitize_filename(sample)}{suffix}.mp3"

    def _get_tts_output_path(self) -> str:
        current = self.tts_output_path_var.get().strip()
        if current:
            return current
        default_name = self._default_tts_filename()
        desktop = os.path.expanduser("~/Desktop")
        base_dir = desktop if os.path.isdir(desktop) else os.getcwd()
        return os.path.join(base_dir, default_name)

    @staticmethod
    def _chunk_tts_text(text: str, max_chars: int = TTS_MAX_CHARS) -> List[str]:
        paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
        chunks: List[str] = []
        current = ""

        def push(value: str) -> None:
            value = value.strip()
            if value:
                chunks.append(value)

        for paragraph in paragraphs:
            sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])", paragraph) if s.strip()]
            for sentence in sentences or [paragraph]:
                if len(sentence) > max_chars:
                    pieces = _slice_long_sentence(sentence, max_chars)
                else:
                    pieces = [sentence]
                for piece in pieces:
                    candidate = f"{current}\n{piece}".strip() if current else piece
                    if len(candidate) <= max_chars:
                        current = candidate
                    else:
                        push(current)
                        current = piece
            if current:
                push(current)
                current = ""
        push(current)
        result_chunks = [c for c in chunks if c] or [text.strip()]
        return [c for c in result_chunks if c]

    def _ensure_tts_dependency(self) -> bool:
        if edge_tts is not None:
            return True
        self._notify_runtime_warning(
            "未安裝 edge-tts，請先重新執行 01 安裝流程後再使用文字轉語音。",
            flag="edge_tts_unavailable_notified",
        )
        return False

    def start_tts_generation(self) -> None:
        text = self._get_tts_effective_text()
        if not text:
            messagebox.showwarning("提醒", "請先貼上要轉成語音的文字內容")
            return
        if not self._ensure_tts_dependency():
            return
        if self.tts_worker_thread and self.tts_worker_thread.is_alive():
            messagebox.showinfo("提醒", "目前已經有文字轉語音正在進行")
            return

        if not messagebox.askyesno("文字將傳送至第三方雲端",
                "此功能使用 Microsoft Edge 線上語音服務，並非本機運算。\n"
                "以下文字將傳送至該服務；請勿包含未授權的公司機密或個資。\n\n"
                f"共 {len(text)} 字，預覽：\n{text[:300]}\n\n是否同意傳送並產生語音？"):
            return

        output_path = self._get_tts_output_path()
        if os.path.exists(output_path):
            overwrite = messagebox.askyesno(
                "檔案已存在",
                f"輸出檔案已存在：\n{output_path}\n\n是否覆蓋？",
            )
            if not overwrite:
                return
        self.tts_output_path_var.set(output_path)
        self.tts_stop_event.clear()
        self._update_tts_control_states(True)
        self._update_tts_status("準備產生音檔...")
        self._update_tts_result("")
        worker = threading.Thread(
            target=self._tts_worker,
            args=(
                text,
                TTS_VOICE_OPTIONS[self.tts_voice_label_var.get()],
                self.tts_rate_var.get(),
                self.tts_pitch_var.get(),
                output_path,
            ),
            daemon=True,
        )
        self.tts_worker_thread = worker
        worker.start()

    def stop_tts_generation(self) -> None:
        if not self.tts_worker_thread or not self.tts_worker_thread.is_alive():
            return
        self.tts_stop_event.set()
        self._update_tts_status("停止中，請稍候...")
        self.tts_stop_button.config(state=tk.DISABLED)

    async def _save_tts_chunk(self, text: str, voice: str, rate: str, pitch: str, output_path: str) -> None:
        communicator = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
        await communicator.save(output_path)

    async def _run_tts_chunks(
        self,
        chunks: List[str],
        voice: str,
        rate: str,
        pitch: str,
        temp_dir: str,
    ) -> List[str]:
        """依序合成各分段，每 0.1 秒檢查停止事件，可即時取消。"""
        chunk_paths: List[str] = []
        for index, chunk in enumerate(chunks, start=1):
            if self.tts_stop_event.is_set():
                raise SystemExit
            chunk_path = os.path.join(temp_dir, f"{index:03d}.mp3")
            self._update_tts_status(f"正在合成第 {index}/{len(chunks)} 段...")
            task = asyncio.ensure_future(
                self._save_tts_chunk(chunk, voice, rate, pitch, chunk_path)
            )
            while not task.done():
                await asyncio.sleep(0.1)
                if self.tts_stop_event.is_set():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass  # 取消時忽略 edge-tts 中途中斷的例外
                    raise SystemExit
            await task  # 傳遞 edge-tts 本身的例外
            chunk_paths.append(chunk_path)
        return chunk_paths

    def _find_ffmpeg(self) -> Optional[str]:
        local = os.path.join(os.path.dirname(__file__), "ffmpeg")
        if os.path.isfile(local):
            return local
        return shutil.which("ffmpeg")

    def _concat_mp3_chunks(self, chunk_paths: List[str], output_path: str) -> None:
        ffmpeg_path = self._find_ffmpeg()
        if ffmpeg_path is None:
            raise RuntimeError("找不到 ffmpeg，無法合併分段音檔。")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as concat_handle:
            concat_file = concat_handle.name
            for chunk_path in chunk_paths:
                escaped = chunk_path.replace("'", "'\\''")
                concat_handle.write(f"file '{escaped}'\n")
        try:
            subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_file,
                    "-c", "copy",
                    output_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            if os.path.exists(concat_file):
                os.remove(concat_file)

    def _tts_worker(self, text: str, voice: str, rate: str, pitch: str, output_path: str) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            chunks = self._chunk_tts_text(text)
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            self._update_tts_status(f"開始合成，共 {len(chunks)} 段...")

            with tempfile.TemporaryDirectory(prefix="whisper_tts_") as temp_dir:
                chunk_paths = loop.run_until_complete(
                    self._run_tts_chunks(chunks, voice, rate, pitch, temp_dir)
                )
                if len(chunk_paths) == 1:
                    shutil.copyfile(chunk_paths[0], output_path)
                else:
                    self._update_tts_status("正在合併分段音檔...")
                    self._concat_mp3_chunks(chunk_paths, output_path)

            self._update_tts_status("完成！音檔已產生。")
            self._update_tts_result(f"MP3: {output_path}")
        except SystemExit:
            self._update_tts_status("文字轉語音已停止。")
            self._update_tts_result("")
        except Exception as exc:  # pylint: disable=broad-except
            self._update_tts_status("文字轉語音失敗，請稍後再試")
            self._update_tts_result("")
            message = str(exc)
            self.root.after(0, lambda: messagebox.showerror("錯誤", message))
        finally:
            loop.close()
            self.tts_worker_thread = None
            self.tts_stop_event.clear()
            # 完成後清空路徑，下次會重新根據內容產生新檔名，避免靜默覆蓋
            self.root.after(0, lambda: self.tts_output_path_var.set(""))
            self.root.after(0, lambda: self._update_tts_control_states(False))

    def _transcribe_worker(
        self, audio_path: str, model_name: str, word_timestamps: bool
    ) -> None:
        try:
            self._update_status("轉錄中（使用 CPU），處理時間取決於檔案長度與模型大小...")
            options = self._build_options(word_timestamps)

            def _progress(cur: float, total: float) -> None:
                pct = int(cur / total * 100) if total else 0
                self._update_status(
                    f"轉錄中… {pct}%（{_format_hms(cur)} / {_format_hms(total)}）"
                )

            raw_result = self._transcribe(
                audio_path, model_name, options, self.stop_event, _progress
            )
            result = self._normalize_chinese_output(raw_result)
            if self.stop_event.is_set():
                raise SystemExit

            output_paths, preview_text = self._write_outputs(audio_path, result)
            self.transcription_folder = os.path.dirname(output_paths["srt"])
            detected_lang = result.get("language") or "unknown"
            self._update_status(
                f"轉錄完成！已保存原稿，接著整理字幕（語言：{detected_lang}）。"
            )
            self._update_outputs_label(output_paths)
            self._update_preview(preview_text)
            source_cues = _dedupe_repeated_segments(result.get("segments", []) or [])
            self.root.after(0, lambda: self._show_transcription_layout(source_cues, audio_path))
        except SystemExit:
            self._update_status("轉錄已停止。")
            self._update_outputs_label({})
            self._update_preview("")
        except Exception as exc:  # pylint: disable=broad-except
            self._handle_error(exc)
        finally:
            self.worker_thread = None
            self.stop_event.clear()
            self.root.after(0, lambda: self._update_control_states(False))

    def _write_outputs(
        self, audio_path: str, result: Dict[str, object]
    ) -> "tuple[Dict[str, str], str]":
        source_dir = getattr(self, "transcribe_output_dir", "") or os.path.dirname(audio_path)
        audio_name = os.path.splitext(os.path.basename(audio_path))[0]
        detected_lang = str(result.get("language", "") or "").lower() or "auto"
        suffix = detected_lang
        base_dir = tempfile.mkdtemp(prefix=f"{audio_name}_{suffix}_字幕_", dir=source_dir)

        segments = _dedupe_repeated_segments(result.get("segments", []) or [])
        source_segments = segments
        # Keep the raw timing intact; the layout workflow splits using word timing.

        text_lines = [str(seg.get("text", "") or "").strip() for seg in segments]
        text_lines = [line for line in text_lines if line]
        text_content = "\n".join(text_lines) if text_lines else result.get("text", "").strip()

        text_path = os.path.join(base_dir, f"{audio_name}_{suffix}.txt")
        with open(text_path, "w", encoding="utf-8") as txt_file:
            txt_file.write(text_content + "\n")

        srt_content = _format_srt(segments)
        srt_path = os.path.join(base_dir, f"{audio_name}_{suffix}.srt")
        with open(srt_path, "w", encoding="utf-8") as srt_file:
            srt_file.write(srt_content)

        vtt_content = _format_vtt(segments)
        vtt_path = os.path.join(base_dir, f"{audio_name}_{suffix}.vtt")
        with open(vtt_path, "w", encoding="utf-8") as vtt_file:
            vtt_file.write(vtt_content)

        paths = {"txt": text_path, "srt": srt_path, "vtt": vtt_path}
        if source_segments:
            project_path = os.path.join(base_dir, f"{audio_name}_{suffix}_時間原稿.json")
            save_new_file(project_path, serialize_document(source_segments))
            paths["字幕專案"] = project_path
        return paths, text_content

    def _handle_error(self, exc: Exception) -> None:
        self._update_status("發生錯誤，請稍後再試")
        self._update_outputs_label({})
        self._update_preview("")
        message = str(exc)
        self.root.after(0, lambda: messagebox.showerror("錯誤", message))

    def clear_preview(self) -> None:
        self.preview.config(state=tk.NORMAL)
        self.preview.delete("1.0", tk.END)
        self.preview.config(state=tk.DISABLED)
        self.output_paths_var.set("")
        self.status_var.set("已清除結果，可重新選擇音檔或影片")

    def clear_tts_inputs(self) -> None:
        self.tts_text.delete("1.0", tk.END)
        self.tts_output_path_var.set("")
        self.tts_result_var.set("")
        self.tts_status_var.set("已清除內容，可重新貼上文字產生音檔")
        self._update_tts_preview("")


def main() -> None:
    root = tk.Tk()
    WhisperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
