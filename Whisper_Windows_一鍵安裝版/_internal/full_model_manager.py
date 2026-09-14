"""Validated local Whisper models; network calls only retrieve public model files.

No audio/text is accepted by this module. Downloaded revisions are pinned before
transfer, loaded offline, hashed, then atomically promoted to the model directory.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

MODELS = ("base", "small", "medium", "large", "turbo")
REQUIRED = ("config.json", "model.bin", "tokenizer.json")
VOCABULARIES = ("vocabulary.txt", "vocabulary.json")
MARKER = ".model_ready.json"
RETRIES = 3
LOCK_TIMEOUT = 1800
DISK_MARGIN = 256 * 1024 * 1024


def _digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def model_ready(directory, full=True, expected_model=None):
    """Accept the legacy small marker as well as newer JSON vocabularies."""
    directory = Path(directory)
    try:
        manifest = json.loads((directory / MARKER).read_text(encoding="utf-8"))
        if expected_model is not None and manifest.get('model') != expected_model:
            return False
        files = manifest["files"]
        if manifest.get("schema") != 1 or not all(name in files for name in REQUIRED):
            return False
        if not any(name in files for name in VOCABULARIES):
            return False
        for name, record in files.items():
            if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
                return False
            path = directory / name
            if path.is_symlink() or not path.is_file():
                return False
            if record["size"] <= 0 or path.stat().st_size != record["size"]:
                return False
            if full and _digest(path) != record["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _notify(progress, message):
    if progress is not None:
        progress(message)


@contextlib.contextmanager
def _model_lock(path, progress):
    """Kernel-backed per-model lock, released even when a downloader exits."""
    with Path(path).open("a+b") as stream:
        # msvcrt requires a byte to lock. flock does not, but sharing the format
        # lets the same code and test contract run on both desktop platforms.
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        started = time.monotonic()
        notified = False
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() - started >= LOCK_TIMEOUT:
                    raise RuntimeError("另一個視窗仍在準備這個模型，請稍後重試。")
                if not notified:
                    _notify(progress, "另一個視窗正在準備相同模型，等待完成後直接使用。")
                    notified = True
                time.sleep(0.25)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _remote_info(name):
    from faster_whisper.utils import _MODELS
    from huggingface_hub import HfApi
    repository = _MODELS[name]
    info = HfApi(token=False).model_info(repository, files_metadata=True, timeout=30)
    # Never send a locally cached account token for these public models.
    return repository, info


def _plan_files(info):
    siblings = {item.rfilename: item for item in info.siblings}
    vocabulary = next((name for name in VOCABULARIES if name in siblings), None)
    required = [*REQUIRED, vocabulary] if vocabulary else list(REQUIRED)
    if vocabulary is None or any(name not in siblings for name in required):
        raise ValueError("公開模型缺少必要檔案，未進行安裝。")
    selected = required + [name for name in ("preprocessor_config.json", "README.md", "LICENSE") if name in siblings]
    if not info.sha or any(not isinstance(siblings[name].size, int) or siblings[name].size <= 0 for name in selected):
        raise ValueError("無法確認模型版本或下載大小，請稍後重試。")
    return selected, siblings


def _check_disk(root, staging, selected, siblings):
    total = sum(siblings[name].size for name in selected)
    # HF preserves partial downloads inside its staging cache. Account for those
    # bytes without treating a partially downloaded file as usable.
    present = sum(path.stat().st_size for path in staging.rglob("*") if path.is_file() and not path.is_symlink()) if staging.exists() else 0
    needed = max(total - min(present, total), 0) + DISK_MARGIN
    if shutil.disk_usage(root).free < needed:
        raise OSError(f"磁碟空間不足：此模型還需要約 {needed / 1024 ** 3:.1f} GB 可用空間；已下載資料會保留。")


def _download(repository, revision, staging, selected):
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=repository, revision=revision, local_dir=str(staging),
                      allow_patterns=selected, token=False, max_workers=2)


def _validate_load(staging):
    from faster_whisper import WhisperModel
    model = WhisperModel(str(staging), device="cpu", compute_type="int8", local_files_only=True)
    del model


def _write_marker(name, repository, revision, staging, selected, siblings):
    records = {}
    for filename in selected:
        path = staging / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size != siblings[filename].size:
            raise ValueError(f"模型檔案不完整：{filename}")
        checksum = _digest(path)
        remote_lfs = getattr(siblings[filename], "lfs", None)
        expected = remote_lfs.get("sha256") if isinstance(remote_lfs, dict) else getattr(remote_lfs, "sha256", None)
        if expected and checksum != expected:
            raise ValueError(f"模型檔案校驗失敗：{filename}")
        records[filename] = {"size": path.stat().st_size, "sha256": checksum}
    _validate_load(staging)
    temporary = staging / (MARKER + ".tmp")
    temporary.write_text(json.dumps({"schema": 1, "model": name, "source_repo": repository,
                                    "source_revision": revision, "files": records}, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, staging / MARKER)
    if not model_ready(staging, full=True):
        raise ValueError("模型完整性驗證未通過。")


def resolve_model(name, bundled_directory, user_models_directory, progress=None) -> Path:
    """Resolve one of five supported models, downloading only if necessary.

    ``progress`` receives human-readable status strings. The caller must not
    enable HF_HUB_OFFLINE during a download; no environment is mutated here.
    An interrupted transfer remains in .faster-{name}-download for resumption.
    """
    if name not in MODELS:
        raise ValueError("請選擇 base、small、medium、large 或 turbo 模型。")
    bundled = Path(bundled_directory) if bundled_directory is not None else None
    if name == "small" and bundled is not None and model_ready(bundled, full=True, expected_model='small'):
        _notify(progress, "預置 small 模型完整性驗證完成，可離線使用。")
        return bundled
    root = Path(user_models_directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"faster-{name}"
    staging = root / f".faster-{name}-download"
    with _model_lock(root / f".faster-{name}.lock", progress):
        if model_ready(target, full=True, expected_model=name):
            _notify(progress, f"{name} 模型完整性驗證完成，可離線使用。")
            return target
        if target.is_symlink() or staging.is_symlink():
            raise ValueError("模型資料夾不可是捷徑或符號連結，請改用一般資料夾。")
        for attempt in range(1, RETRIES + 1):
            try:
                _notify(progress, f"準備 {name} 模型（第 {attempt}/{RETRIES} 次）；只下載公開模型，不上傳影音。")
                repository, info = _remote_info(name)
                selected, siblings = _plan_files(info)
                _check_disk(root, staging, selected, siblings)
                _download(repository, info.sha, staging, selected)
                _notify(progress, "下載完成，正在檢查檔案與本機載入，請稍候。")
                _write_marker(name, repository, info.sha, staging, selected, siblings)
                backup = None
                if target.exists():
                    backup = root / f"faster-{name}-backup-{uuid.uuid4().hex[:8]}"
                    target.rename(backup)
                try:
                    staging.rename(target)
                except BaseException:
                    if backup is not None:
                        backup.rename(target)
                    raise
                _notify(progress, f"{name} 模型已就緒；之後使用不需要網路。")
                return target
            except Exception as exc:
                _notify(progress, f"模型尚未就緒：{exc}")
                if isinstance(exc, OSError) and "磁碟空間不足" in str(exc):
                    raise
                if attempt == RETRIES:
                    raise RuntimeError("模型準備失敗，請確認網路與磁碟空間後重試；已下載部分已保留，可續傳。") from exc
                time.sleep(2)
    raise RuntimeError("模型未就緒。")
