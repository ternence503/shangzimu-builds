import importlib.util
from pathlib import Path
import tempfile
import unittest
import sys

spec = importlib.util.spec_from_file_location('normalization', Path(__file__).resolve().parents[1] / 'packaging/mac/normalize_vocal_worker.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@unittest.skipUnless(sys.platform == 'darwin', 'Mach-O packaging and POSIX loader symlinks are macOS-only')
class NormalizationTests(unittest.TestCase):
    def fixture(self, root, payload=b'same'):
        duplicate = root / '_internal/torch/lib/libiomp5.dylib'
        duplicate.parent.mkdir(parents=True)
        duplicate.write_bytes(payload)
        loaded = root / '_internal/functorch/.dylibs/libiomp5.dylib'
        loaded.parent.mkdir(parents=True)
        loaded.write_bytes(b'same')
        (root / '_internal/libiomp5.dylib').symlink_to('functorch/.dylibs/libiomp5.dylib')
        return duplicate, loaded

    def test_preserves_both_paths_with_one_exact_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate, loaded = self.fixture(root)
            module.normalize(root)
            self.assertTrue(duplicate.is_symlink())
            self.assertEqual(duplicate.resolve(), loaded.resolve())
            self.assertEqual(duplicate.read_bytes(), b'same')
            module.normalize(root)

    def test_different_images_are_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate, loaded = self.fixture(root, b'different')
            with self.assertRaises(ValueError):
                module.normalize(root)
            self.assertEqual(duplicate.read_bytes(), b'different')
            self.assertFalse(duplicate.is_symlink())
