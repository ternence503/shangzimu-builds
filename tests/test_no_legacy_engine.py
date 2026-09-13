"""Prevent the Intel Mac LLVM build dependency from returning to the preview."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class NoLegacyEngineTests(unittest.TestCase):
    def test_both_platforms_have_no_legacy_dependency_or_import(self):
        for platform, gui, requirements, setup in [
            ('Mac', 'whisper_gui_mac.py', 'requirements-mac.txt', 'setup_and_run_mac.sh'),
            ('Windows', 'whisper_gui_win.py', 'requirements-win.txt', 'setup_and_run.ps1')]:
            internal = ROOT / f'Whisper_{platform}_一鍵安裝版' / '_internal'
            dependencies = (internal / requirements).read_text()
            for unwanted in ('openai-whisper', 'numba', 'llvmlite', 'torch'):
                self.assertNotIn(unwanted, dependencies)
            source = (internal / gui).read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(a.name == 'whisper' for a in node.names))
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, 'whisper')
            installer = (internal / setup).read_text(encoding='utf-8-sig')
            self.assertNotIn('import whisper', installer)
            self.assertIn('--only-binary=:all:', installer)

    def test_platform_gui_parity_and_powershell_bom(self):
        mac = ROOT / 'Whisper_Mac_一鍵安裝版' / '_internal'
        win = ROOT / 'Whisper_Windows_一鍵安裝版' / '_internal'
        self.assertEqual((mac / 'whisper_gui_mac.py').read_bytes(), (win / 'whisper_gui_win.py').read_bytes())
        self.assertTrue((win / 'setup_and_run.ps1').read_bytes().startswith(b'\xef\xbb\xbf'))

if __name__ == '__main__':
    unittest.main()
