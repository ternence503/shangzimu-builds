"""Fail closed on missing/corrupt/non-Windows resources before freezing."""
import argparse
import hashlib
import json
import struct
import importlib.util
from pathlib import Path

FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")

def check_pe(path):
    with Path(path).open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError(f"Not a Windows PE executable: {path}")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0" or struct.unpack("<H", stream.read(2))[0] != 0x8664:
            raise ValueError(f"Windows x64 executable required: {path}")

def validate(resources, load_model=True):
    resources = Path(resources)
    model = resources / "models" / "faster-small"
    installer = Path(__file__).resolve().parents[2] / "Whisper_Mac_一鍵安裝版" / "_internal" / "download_model.py"
    module_spec = importlib.util.spec_from_file_location("bundled_model_validation", installer)
    model_checks = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(model_checks)
    if not model_checks.model_ready(model, full=True):
        raise ValueError(f"Model requires schema 1 readiness manifest and matching SHA256: {model}")
    manifest = {}
    for name in FILES:
        path = model / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing model file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        manifest[name] = {"size": path.stat().st_size, "sha256": digest.hexdigest()}
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        check_pe(resources / "bin" / name)
    for path in (resources / "guide.txt", resources / "THIRD-PARTY-NOTICES.txt",
                 resources / "examples" / "排版示範.json"):
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Required resource missing: {path}")
    if load_model:
        from faster_whisper import WhisperModel
        WhisperModel(str(model), device="cpu", compute_type="int8", local_files_only=True)
    return manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("resources", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.resources), ensure_ascii=False, indent=2))
