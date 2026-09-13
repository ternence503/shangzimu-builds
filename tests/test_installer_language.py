import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer_language', ROOT / 'packaging/windows/prepare_language.py')
language = importlib.util.module_from_spec(spec)
spec.loader.exec_module(language)

class InstallerLanguageTests(unittest.TestCase):
    def test_installer_checks_actual_target_before_copying(self):
        source = (ROOT / 'packaging/windows/installer.iss').read_text(encoding='utf-8-sig')
        prepare = source.split('function PrepareToInstall', 1)[1]
        self.assertIn("ExpandConstant('{app}')", prepare)
        self.assertIn('CompareText(AddBackslash(ActualDir), AddBackslash(ExpectedDir))', prepare)
        self.assertIn("ActualDir + '\\unins000.exe'", prepare)
        self.assertIn('SuppressibleMsgBox', source)

    def test_verified_language_and_notices_are_saved_without_overwrite(self):
        fixture = '繁體中文測試語系'.encode('utf-8')
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'licenses'
            with patch.object(language, 'LANGUAGE_SHA256', hashlib.sha256(fixture).hexdigest()), \
                 patch.object(language.urllib.request, 'urlopen', side_effect=[io.BytesIO(fixture), io.BytesIO(b'license notice')]):
                language.prepare(output)
            self.assertEqual((output / 'ChineseTraditional.isl').read_bytes(), fixture)
            self.assertEqual(json.loads((output / 'sources.json').read_text(encoding='utf-8'))['revision'], language.REVISION)
            with self.assertRaises(FileExistsError):
                language.prepare(output)

    def test_tampered_language_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'licenses'
            with patch.object(language.urllib.request, 'urlopen', return_value=io.BytesIO(b'tampered')):
                with self.assertRaises(ValueError):
                    language.prepare(output)
            self.assertFalse((output / 'ChineseTraditional.isl').exists())
            self.assertFalse((output / 'sources.json').exists())

if __name__ == '__main__':
    unittest.main()
