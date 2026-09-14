import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
import types
import zipfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('license_materials', Path(__file__).resolve().parents[1] / 'packaging' / 'license_materials.py')
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


class MaterialsTests(unittest.TestCase):
    def test_data_parser_never_executes_recipe(self):
        records = materials.package_sources('raise RuntimeError("must not execute")\nPackage(name="x",source_url="https://example.org/source",sha256="' + 'a' * 64 + '")')
        self.assertEqual(records[0]['name'], 'x')

    def test_parser_rejects_bad_hash(self):
        with self.assertRaises(ValueError):
            materials.package_sources('Package(name="x",source_url="https://example.org/source",sha256="bad")')

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ('../escape', '/absolute', 'licenses/../../escape', 'licenses\\escape'):
                with self.assertRaises(ValueError):
                    materials.safe_target(Path(directory), value)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'licenses').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                materials.safe_target(root, 'licenses/a.txt')

    def test_empty_recipe_is_not_clearance(self):
        with self.assertRaises(ValueError):
            materials.package_sources('pass')

    def test_http_not_allowed(self):
        with self.assertRaises(ValueError):
            materials.fetch('http://example.org/material')

    def test_unreviewed_stock_wheel_proof_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory) / 'proof.json'
            proof.write_text(json.dumps({'status': 'collected-not-reviewed'}))
            with self.assertRaises(ValueError):
                materials.review_local_pyav(proof)

    def test_proof_cannot_escape_repaired_wheel_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory) / 'proof.json'
            proof.write_text(json.dumps({'status': 'source-built-minimal-ffmpeg',
                                        'av_version': materials.AV_VERSION,
                                        'ffmpeg_source_sha256': materials.FFMPEG_SHA,
                                        'wheel_filename': '../fake.whl'}))
            with self.assertRaises(ValueError):
                materials.review_local_pyav(proof)

    def test_source_wheel_native_hash_and_live_configuration_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel_dir = root / 'repaired'
            wheel_dir.mkdir()
            wheel = wheel_dir / 'av-test.whl'
            relative = 'av/.dylibs/libavcodec.dylib'
            with zipfile.ZipFile(wheel, 'w') as zipped:
                zipped.writestr(relative, b'test-native')
            installed = root / 'installed'
            native = installed / relative
            native.parent.mkdir(parents=True)
            native.write_bytes(b'test-native')
            proof = root / 'proof.json'
            proof.write_text(json.dumps({'status': 'source-built-minimal-ffmpeg',
                                        'av_version': materials.AV_VERSION,
                                        'ffmpeg_source_sha256': materials.FFMPEG_SHA,
                                        'wheel_filename': wheel.name,
                                        'wheel_sha256': materials.digest(wheel.read_bytes())}))
            meta = {'avcodec': {'configuration': '--disable-gpl --disable-autodetect'}}
            fake_av = types.SimpleNamespace(_core=types.SimpleNamespace(library_meta=meta))
            distribution = types.SimpleNamespace(locate_file=lambda name: installed)
            with patch.dict('sys.modules', {'av': fake_av}), patch.object(materials.importlib.metadata, 'distribution', return_value=distribution):
                materials.review_local_pyav(proof)
                native.write_bytes(b'tampered-native')
                with self.assertRaises(ValueError):
                    materials.review_local_pyav(proof)
                native.write_bytes(b'test-native')
                meta['avcodec']['configuration'] += ' --enable-libx264'
                with self.assertRaises(ValueError):
                    materials.review_local_pyav(proof)
