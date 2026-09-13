import importlib.util
import json
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
INTERNAL = ROOT / "Whisper_Mac_一鍵安裝版" / "_internal"
spec = importlib.util.spec_from_file_location("preview_downloader", INTERNAL / "download_model.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class ModelInstallerTests(unittest.TestCase):
    def mock_download(self, **kwargs):
        directory = Path(kwargs["local_dir"])
        directory.mkdir(parents=True, exist_ok=True)
        for name in installer.REQUIRED: (directory / name).write_bytes(b"synthetic model fixture")

    def test_incomplete_existing_file_is_not_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "model.bin").write_bytes(b"partial")
            self.assertFalse(installer.model_ready(directory, full=True))

    def test_download_validates_offline_then_promotes(self):
        calls = []
        def loader(path, **kwargs):
            self.assertTrue(kwargs["local_files_only"])
            self.assertFalse((Path(path) / installer.MARKER).exists())
            calls.append(path)
        mocks = {"huggingface_hub": types.SimpleNamespace(snapshot_download=self.mock_download),
                 "faster_whisper": types.SimpleNamespace(WhisperModel=loader)}
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, mocks):
            target = installer.download_model("small", Path(folder))
            self.assertEqual(len(calls), 1)
            self.assertTrue(installer.model_ready(target, full=True))
            installer.download_model("small", Path(folder))
            self.assertEqual(len(calls), 1)
            (target / "model.bin").write_bytes(b"x" * (target / "model.bin").stat().st_size)
            self.assertFalse(installer.model_ready(target, full=True))

    def test_failure_never_marks_download_complete(self):
        mocks = {"huggingface_hub": types.SimpleNamespace(snapshot_download=self.mock_download),
                 "faster_whisper": types.SimpleNamespace(WhisperModel=lambda *a, **k: (_ for _ in ()).throw(ValueError("invalid")))}
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, mocks), patch.object(installer.time, "sleep"):
            with self.assertRaises(RuntimeError): installer.download_model("small", Path(folder), retries=2)
            self.assertFalse((Path(folder) / "faster-small").exists())
            self.assertFalse((Path(folder) / ".faster-small-download" / installer.MARKER).exists())

    def test_invalid_model_cannot_trigger_network(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError): installer.download_model("medium", Path(folder))

    def test_platform_isolation_and_no_formal_shortcut_deletion(self):
        mac = (INTERNAL / "setup_and_run_mac.sh").read_text()
        win = (ROOT / "Whisper_Windows_一鍵安裝版" / "_internal" / "setup_and_run.ps1").read_text()
        self.assertIn("WhisperGUI-SubtitlePreview", mac)
        self.assertIn("WhisperGui-SubtitlePreview", win)
        self.assertNotIn("Remove-Item", win)
        self.assertNotIn("WindowStyle Hidden", win)
        self.assertIn("Whisper 字幕試用版.lnk", win)
        self.assertEqual((INTERNAL / "download_model.py").read_bytes(),
                         (ROOT / "Whisper_Windows_一鍵安裝版" / "_internal" / "download_model.py").read_bytes())

    def test_powershell_python_calls_use_explicit_named_array(self):
        win = (ROOT / "Whisper_Windows_一鍵安裝版" / "_internal" / "setup_and_run.ps1").read_text()
        calls = [line.strip() for line in win.splitlines() if line.strip().startswith("Invoke-Python ")]
        self.assertEqual(len(calls), 6)
        for call in calls:
            self.assertIn("-Exe ", call)
            self.assertIn("-Arguments @(", call)
        self.assertIn("function Test-PythonImports", win)
        self.assertIn('catch { return $false }', win)
        self.assertIn('$ErrorActionPreference = "Continue"', win)

if __name__ == "__main__": unittest.main()
