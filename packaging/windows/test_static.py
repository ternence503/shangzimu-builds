"""Portable contract tests. Not Windows native or installer execution tests."""
import ast
import hashlib
import json
import importlib.util
import struct
import tempfile
import types
from unittest.mock import patch
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check_inputs", HERE / "check_inputs.py")
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)

class PackagingContract(unittest.TestCase):
    def test_spec_execution_paths(self):
        hooks = types.ModuleType("PyInstaller.utils.hooks")
        hooks.collect_all = lambda package: ([], [], [])
        hooks.copy_metadata = lambda package: []
        captured = {}
        def analysis(scripts, **kwargs):
            captured.update(scripts=scripts, **kwargs)
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
        namespace = dict(SPECPATH=str(HERE), Analysis=analysis,
                         PYZ=lambda *a, **k: None, EXE=lambda *a, **k: None,
                         COLLECT=lambda *a, **k: None)
        with tempfile.TemporaryDirectory() as resources:
            with patch.dict("sys.modules", {"PyInstaller.utils.hooks": hooks}), \
                 patch.dict("os.environ", {"SHANGZIMU_BUILD_RESOURCES": resources}), \
                 patch("platform.system", return_value="Windows"), \
                 patch("platform.machine", return_value="AMD64"):
                exec(compile((HERE / "up-subtitles.spec").read_text(), "spec", "exec"), namespace)
            self.assertEqual(Path(captured["scripts"][0]), HERE.parent / "entry.py")
            self.assertTrue(Path(captured["scripts"][0]).is_file())
            self.assertTrue((Path(captured["pathex"][0]) / "whisper_gui_mac.py").is_file())
            self.assertTrue((Path(captured["pathex"][0]) / "version.txt").is_file())
            self.assertIn((str(Path(resources).resolve()), "resources"), captured["datas"])

    def test_manifest_requires_complete_hash_match(self):
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory)
            model = resources / "models" / "faster-small"
            model.mkdir(parents=True)
            files = {}
            for name in inputs.FILES:
                payload = (name + " fake test data").encode()
                (model / name).write_bytes(payload)
                files[name] = dict(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            # Correct filenames alone are not enough.
            with self.assertRaises(ValueError): inputs.validate(resources, load_model=False)
            (model / ".model_ready.json").write_text(json.dumps(dict(schema=1, files=files)))
            binary = bytearray(128)
            binary[:2] = b"MZ"
            binary[0x3C:0x40] = struct.pack("<I", 64)
            binary[64:70] = b"PE\0\0" + struct.pack("<H", 0x8664)
            (resources / "bin").mkdir()
            for name in ("ffmpeg.exe", "ffprobe.exe"): (resources / "bin" / name).write_bytes(binary)
            (resources / "examples").mkdir()
            (resources / "examples" / "排版示範.json").write_text("{}")
            for name in ("guide.txt", "THIRD-PARTY-NOTICES.txt"): (resources / name).write_text("test")
            self.assertEqual(inputs.validate(resources, load_model=False), files)
            original = (model / "config.json").read_bytes()
            (model / "config.json").write_bytes(b"x" * len(original))
            with self.assertRaises(ValueError): inputs.validate(resources, load_model=False)
            (model / "config.json").write_bytes(original)
            del files["vocabulary.txt"]
            (model / ".model_ready.json").write_text(json.dumps(dict(schema=1, files=files)))
            with self.assertRaises(ValueError): inputs.validate(resources, load_model=False)
    def test_spec_parses_and_correct_entry(self):
        ast.parse((HERE / "up-subtitles.spec").read_text())
        root = HERE.parent
        self.assertTrue((root.parent / "Whisper_Mac_一鍵安裝版" / "_internal" / "whisper_gui_mac.py").is_file())

    def test_pe_x64_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tool.exe"
            payload = bytearray(128)
            payload[:2] = b"MZ"
            payload[0x3C:0x40] = struct.pack("<I", 64)
            payload[64:70] = b"PE\0\0" + struct.pack("<H", 0x8664)
            path.write_bytes(payload)
            inputs.check_pe(path)
            payload[68:70] = struct.pack("<H", 0x14C)
            path.write_bytes(payload)
            with self.assertRaises(ValueError): inputs.check_pe(path)
            path.write_bytes(b"not a windows executable")
            with self.assertRaises(ValueError): inputs.check_pe(path)

    def test_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): inputs.validate(directory, load_model=False)

    def test_no_end_user_dependency_or_data_delete(self):
        text = (HERE / "installer.iss").read_text()
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn("{userprograms}\\上字幕", text)
        self.assertNotIn("[UninstallDelete]", text)
        self.assertNotIn("[InstallDelete]", text)
        self.assertNotIn("pip", text)
        build = (HERE / "Build.ps1").read_text()
        self.assertNotIn("Remove-Item", build)
        self.assertIn("$Result.status -ne 'passed'", build)

if __name__ == "__main__": unittest.main()
