import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Whisper_Mac_一鍵安裝版' / '_internal'))
import full_model_manager as manager

class FullModelTests(unittest.TestCase):
    def fixture(self, path, vocabulary):
        path.mkdir(parents=True)
        files = {}
        for name in (*manager.REQUIRED, vocabulary):
            data = name.encode()
            (path / name).write_bytes(data)
            files[name] = {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
        (path / manager.MARKER).write_text(json.dumps({'schema':1, 'model':path.name.removeprefix('faster-'), 'files':files}))

    def test_both_vocabularies_and_corruption(self):
        for vocabulary in manager.VOCABULARIES:
            with tempfile.TemporaryDirectory() as base:
                path = Path(base) / 'model'
                self.fixture(path, vocabulary)
                self.assertTrue(manager.model_ready(path))
                (path / 'model.bin').write_bytes(b'x' * len(b'model.bin'))
                self.assertFalse(manager.model_ready(path))

    def test_preloaded_models_never_download(self):
        for name in manager.MODELS:
            with tempfile.TemporaryDirectory() as base:
                path = Path(base) / f'faster-{name}'
                self.fixture(path, 'vocabulary.json')
                with patch.object(manager, '_remote_info', side_effect=AssertionError('no network')):
                    self.assertEqual(manager.resolve_model(name, path if name == 'small' else None, base), path)

    def test_unknown_model_rejected_before_files_or_network(self):
        with patch.object(manager, '_remote_info') as remote:
            with self.assertRaises(ValueError):
                manager.resolve_model('../bad', None, '/not-created')
            remote.assert_not_called()

    def test_model_identity_must_match_selection(self):
        with tempfile.TemporaryDirectory() as base:
            path = Path(base) / 'faster-base'
            self.fixture(path, 'vocabulary.json')
            self.assertTrue(manager.model_ready(path, expected_model='base'))
            self.assertFalse(manager.model_ready(path, expected_model='medium'))

    def test_failed_download_preserves_partial(self):
        with tempfile.TemporaryDirectory() as base:
            staging = Path(base) / '.faster-base-download'
            staging.mkdir()
            partial = staging / 'partial'
            partial.write_bytes(b'keep')
            with patch.object(manager, 'RETRIES', 1), patch.object(manager, '_remote_info', side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError): manager.resolve_model('base', None, base)
            self.assertEqual(partial.read_bytes(), b'keep')
            self.assertFalse((Path(base) / 'faster-base').exists())
