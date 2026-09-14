import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / 'Whisper_Mac_一鍵安裝版' / '_internal' / 'whisper_gui_mac.py'


class PrivacyTests(unittest.TestCase):
    def test_declining_cloud_consent_starts_no_worker_and_touches_no_output(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                      and n.name == 'start_tts_generation')
        cls = ast.ClassDef(name='App', bases=[], keywords=[], decorator_list=[], body=[method])
        ns = {'messagebox': Mock(), 'threading': Mock(), 'os': Mock()}
        ns['messagebox'].askyesno.return_value = False
        body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls]
        exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), '<actual-consent>', 'exec'), ns)
        app = ns['App']()
        app._get_tts_effective_text = Mock(return_value='不得外傳的內部內容')
        app._ensure_tts_dependency = Mock(return_value=True)
        app.tts_worker_thread = None
        app._get_tts_output_path = Mock()
        app.start_tts_generation()
        ns['messagebox'].askyesno.assert_called_once()
        app._get_tts_output_path.assert_not_called()
        ns['threading'].Thread.assert_not_called()
        ns['os'].path.exists.assert_not_called()

    def test_frozen_lyrics_uses_dedicated_worker_not_gui_as_python(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                      and n.name == '_lyrics_worker')
        text = ast.unparse(method)
        self.assertNotIn('sys.executable', text)
        self.assertIn('VocalWorker', text)
        self.assertIn('proc.terminate()', text)
        self.assertIn('proc.wait(timeout=5)', text)


if __name__ == '__main__':
    unittest.main()
