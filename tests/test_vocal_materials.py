import importlib.util
import json
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    'vocal_materials', Path(__file__).resolve().parents[1] / 'packaging/vocal_materials.py')
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


class VocalMaterialsTests(unittest.TestCase):
    def test_known_native_owner_mapping_is_explicit(self):
        cases = {
            '_internal/torch/lib/libtorch_cpu.dylib': 'torch',
            '_internal/torchaudio/lib/libtorchaudio.so': 'torchaudio',
            '_internal/numpy/.dylibs/libopenblas64_.0.dylib': 'numpy',
            '_internal/python3.12/lib-dynload/_ssl.cpython-312-darwin.so': 'cpython-runtime',
            '_internal/markupsafe/_speedups.cpython-312-darwin.so': 'markupsafe',
            '_internal/yaml/_yaml.cp312-win_amd64.pyd': 'pyyaml',
            'VocalWorker': 'pyinstaller',
        }
        for path, owner in cases.items():
            self.assertEqual(materials.reviewed_owner(path, 'Darwin', False), owner)
        self.assertIsNone(materials.reviewed_owner('_internal/unknown-native.so', 'Darwin', False))

    def test_macos_openmp_requires_source_built_mapping(self):
        path = '_internal/functorch/.dylibs/libiomp5.dylib'
        self.assertEqual(materials.reviewed_owner(path, 'Darwin', True), 'llvm-openmp')
        self.assertEqual(materials.reviewed_owner(path, 'Darwin', False), 'torch')
        self.assertEqual(materials.reviewed_owner('_internal/libomp.dylib', 'Darwin', True), 'llvm-openmp')

    def test_native_sox_names_are_denied(self):
        for path in ('_internal/libsox.dll', '_internal/torchaudio/lib/_torchaudio_sox.pyd',
                     '_internal/torchaudio/lib/libtorchaudio_sox.so'):
            self.assertIsNotNone(materials.SOX_NATIVE_RE.search(path))
        self.assertIsNone(materials.SOX_NATIVE_RE.search('_internal/torchaudio/backend/sox.py'))

    def test_native_set_digest_is_stable_and_hash_bound(self):
        records = [{'path': 'VocalWorker', 'sha256': '1' * 64},
                   {'path': '_internal/lib.dylib', 'sha256': '2' * 64}]
        first = materials.native_set_digest(records)
        self.assertEqual(first, materials.native_set_digest(json.loads(json.dumps(records))))
        records[1]['sha256'] = '3' * 64
        self.assertNotEqual(first, materials.native_set_digest(records))


if __name__ == '__main__':
    unittest.main()
