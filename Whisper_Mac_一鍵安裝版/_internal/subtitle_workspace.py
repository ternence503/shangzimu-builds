"""Local subtitle documents and non-overwriting exports (standard library only)."""

import json
import math
import re
import os
import tempfile
from pathlib import Path


def _seconds(value):
    match = re.fullmatch(r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError("字幕時間格式需為 00:00:00,000。")
    hours, minutes, seconds, millis = map(int, match.groups())
    if minutes > 59 or seconds > 59:
        raise ValueError("字幕的分、秒數值不正確。")
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def validate_cues(cues):
    if not isinstance(cues, list) or not cues:
        raise ValueError("檔案沒有可用的字幕。")
    previous_start = -1.0
    validated = []
    for index, cue in enumerate(cues, 1):
        try:
            start, end = float(cue["start"]), float(cue["end"])
            text = cue["text"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"第 {index} 塊字幕資料不完整。") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f"第 {index} 塊字幕的時間範圍不正確。")
        if start < previous_start:
            raise ValueError("字幕需按照開始時間排序。")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"第 {index} 塊字幕沒有文字。")
        if re.search(r"\n\s*\n", text):
            raise ValueError(f"第 {index} 塊字幕中不能有空白行；可使用單次換行。")
        validated.append(dict(cue, start=start, end=end, text=text.strip()))
        previous_start = start
    return validated


def parse_srt(content):
    blocks = re.split(r"\n[ \t]*\n", content.lstrip("\ufeff").replace("\r\n", "\n").strip())
    cues = []
    for number, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if len(lines) < 2 or "-->" not in lines[0]:
            raise ValueError(f"第 {number} 塊字幕的 SRT 格式不完整。")
        start, end = lines[0].split("-->", 1)
        # Positioning extensions are not part of the timing value.
        cues.append({"start": _seconds(start), "end": _seconds(end.strip().split()[0]),
                     "text": "\n".join(lines[1:])})
    return validate_cues(cues)


def _timestamp(seconds):
    millis = round(float(seconds) * 1000)
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def serialize_srt(cues):
    return "\n\n".join(
        f"{i}\n{_timestamp(c['start'])} --> {_timestamp(c['end'])}\n{c['text']}"
        for i, c in enumerate(validate_cues(cues), 1)
    ) + "\n"


def read_document(path, with_metadata=False):
    path = Path(path)
    content = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".srt":
        cues = parse_srt(content)
        return (cues, {"kind": "source"}) if with_metadata else cues
    document = json.loads(content)
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("不支援這個字幕專案版本。")
    cues = validate_cues(document.get("segments"))
    if "original_segments" in document:
        document["original_segments"] = validate_cues(document["original_segments"])
    return (cues, document) if with_metadata else cues


def save_new_file(path, content):
    """Use exclusive creation; never replace an existing original or revision."""
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def serialize_document(cues, kind="source", settings=None, original_segments=None):
    document = {"version": 1, "kind": kind, "segments": validate_cues(cues)}
    if settings is not None:
        document["settings"] = settings
    if original_segments is not None:
        document["original_segments"] = validate_cues(original_segments)
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def next_revision_path(path):
    """Suggest a free revision name; exclusive creation still protects against races."""
    path = Path(path)
    if not path.exists():
        return path
    for number in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_v{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("版本檔案太多，請選擇另一個檔名或資料夾。")


def write_recovery(path, content):
    """Atomically replace only the app's designated recovery document."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="recovery-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
