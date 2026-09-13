import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location("component_inventory", Path(__file__).resolve().parents[1] / "packaging" / "component_inventory.py")
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)

class InventoryTests(unittest.TestCase):
    def fixture(self, directory):
        resources = Path(directory) / "resources"
        (resources / "bin").mkdir(parents=True)
        import sys
        for name in ("ffmpeg", "ffprobe"):
            (resources / "bin" / (name + (".exe" if sys.platform == "win32" else ""))).write_bytes(b"fake binary")
        package = Path(directory) / "installed"
        (package / "example-1.0.dist-info" / "licenses").mkdir(parents=True)
        (package / "example-1.0.dist-info" / "licenses" / "LICENSE.txt").write_bytes(b"Original license\r\n")
        dist = SimpleNamespace(metadata={"Name": "example", "License": "MIT", "Home-page": "https://secret:token@example.invalid"},
            version="1.0", files=["example-1.0.dist-info/licenses/LICENSE.txt"], locate_file=lambda name: package / name)
        return resources, dist

    def fake_tool(self, command, **kwargs):
        self.assertTrue(kwargs["check"])
        return SimpleNamespace(stdout="ffmpeg test --prefix=/Users/private/build\n", stderr="")

    def test_inventory_original_notices_no_origin_or_install_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            resources, dist = self.fixture(directory)
            result = ci.inventory(resources, distributions=[dist], run=self.fake_tool, av_versions={"libavcodec": (1, 2, 3)})
            self.assertEqual(result["status"], "inventory-only/not-redistribution-cleared")
            notice = result["python_packages"][0]["notices"][0]
            self.assertEqual((resources / notice["saved_relative_path"]).read_bytes(), b"Original license\r\n")
            text = (resources / "components.json").read_text(encoding='utf-8')
            self.assertNotIn(directory, text)
            self.assertNotIn("secret:token", text)
            self.assertNotIn("/Users/private", text)
            with self.assertRaises(FileExistsError): ci.inventory(resources, distributions=[dist], run=self.fake_tool)

    def test_unsafe_metadata_and_license_paths_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            resources, dist = self.fixture(directory)
            dist.metadata["Name"] = "../escape"
            with self.assertRaises(ValueError): ci.inventory(resources, distributions=[dist], run=self.fake_tool)
            dist.metadata["Name"] = "example"
            dist.files = ["example.dist-info/../../LICENSE"]
            with self.assertRaises(ValueError): ci.inventory(resources, distributions=[dist], run=self.fake_tool)
            self.assertFalse((resources / "components.json").exists())

    def test_real_numpy_and_vendored_license_paths_are_allowed(self):
        for path in ('numpy.dist-info/licenses/numpy/_core/src/COPYING',
                     'setuptools/_vendor/example.dist-info/LICENSE'):
            self.assertEqual(str(ci.relative_file(path)), path)
        for unsafe in ('example.dist-info/../LICENSE', 'example.dist-info/.hidden/LICENSE'):
            with self.assertRaises(ValueError):
                ci.relative_file(unsafe)

    def test_symlink_output_parent_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            resources, dist = self.fixture(directory)
            elsewhere = Path(directory) / "elsewhere"
            elsewhere.mkdir()
            try:
                (resources / "licenses").symlink_to(elsewhere, target_is_directory=True)
            except OSError:
                self.skipTest("Platform lacks symlink permission")
            with self.assertRaises(ValueError): ci.inventory(resources, distributions=[dist], run=self.fake_tool)
            self.assertEqual(list(elsewhere.iterdir()), [])

    def test_unknown_and_missing_notices_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            resources, dist = self.fixture(directory)
            dist.metadata.pop("License")
            dist.files = []
            result = ci.inventory(resources, distributions=[dist], run=self.fake_tool, av_versions="unavailable")
            self.assertEqual(result["python_packages"][0]["license_metadata"], "unknown")
            self.assertEqual(result["python_packages"][0]["notice_status"], "missing/pending")

    def test_duplicate_rejected_before_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            resources, dist = self.fixture(directory)
            with self.assertRaises(ValueError): ci.inventory(resources, distributions=[dist, dist], run=self.fake_tool)
            self.assertFalse((resources / "licenses" / "python-packages").exists())

    def test_model_snapshot_drops_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            resources, dist = self.fixture(directory)
            model = resources / "models" / "faster-small"
            model.mkdir(parents=True)
            (model / ".model_ready.json").write_text(json.dumps({"schema": 1, "private_path": "/Users/private", "files": {
                "model.bin": {"size": 1, "sha256": "a" * 64, "secret": "do not collect"}}}))
            result = ci.inventory(resources, distributions=[dist], run=self.fake_tool, av_versions={})
            self.assertNotIn("private_path", result["model"]["manifest_snapshot"])
            self.assertNotIn("secret", result["model"]["manifest_snapshot"]["files"]["model.bin"])

if __name__ == "__main__": unittest.main()
