#!/usr/bin/env python3
"""準備真正用於轉錄的本機 faster-whisper 模型；不處理使用者音訊。"""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import time
import uuid
REQUIRED = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
MARKER = ".model_ready.json"

def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

def model_ready(directory, full=False):
    directory = pathlib.Path(directory)
    try:
        manifest = json.loads((directory / MARKER).read_text(encoding="utf-8"))
        if manifest.get("schema") != 1 or not all(name in manifest["files"] for name in REQUIRED): return False
        for name, record in manifest["files"].items():
            if pathlib.Path(name).name != name: return False
            path = directory / name
            if not path.is_file() or path.stat().st_size != record["size"] or record["size"] <= 0: return False
            if full and digest(path) != record["sha256"]: return False
        return True
    except (OSError, ValueError, KeyError, TypeError): return False

def download_model(name, output_dir, retries=3):
    if name != "small": raise ValueError("此內部試用版只準備通用 small 模型。")
    root = pathlib.Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "faster-small"
    if model_ready(target, full=True):
        print("語音模型完整性驗證完成，可離線使用。", flush=True)
        return target
    from huggingface_hub import snapshot_download
    from faster_whisper import WhisperModel
    staging = root / ".faster-small-download"
    for attempt in range(1, retries + 1):
        try:
            print(f"準備語音模型（第 {attempt}/{retries} 次）；只下載程式模型，不上傳音訊。", flush=True)
            snapshot_download(repo_id="Systran/faster-whisper-small", local_dir=str(staging), allow_patterns=[*REQUIRED, "preprocessor_config.json"])
            if any(not (staging / item).is_file() or (staging / item).stat().st_size == 0 for item in REQUIRED): raise ValueError("模型檔案不完整")
            model = WhisperModel(str(staging), device="cpu", compute_type="int8", local_files_only=True)
            del model
            files = {item: {"size": (staging / item).stat().st_size, "sha256": digest(staging / item)} for item in REQUIRED}
            (staging / MARKER).write_text(json.dumps({"schema": 1, "model": name, "files": files}), encoding="utf-8")
            if target.exists(): target.rename(root / ("faster-small-backup-" + uuid.uuid4().hex[:8]))
            staging.rename(target)
            print("模型下載與本機載入驗證完成。", flush=True)
            return target
        except Exception as exc:
            print(f"模型準備尚未完成：{exc}", flush=True)
            if attempt == retries: raise RuntimeError("請確認網路與剩餘磁碟空間，再雙擊啟動檔重試；已下載的部分會續傳。") from exc
            time.sleep(2)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", nargs="?", default="small")
    parser.add_argument("--output", "-o", default="models")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = pathlib.Path(args.output).resolve()
    if args.check: raise SystemExit(0 if model_ready(root / "faster-small", full=True) else 1)
    download_model(args.model, root)

if __name__ == "__main__": main()
