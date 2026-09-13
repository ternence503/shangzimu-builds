import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'packaging' / 'entry.py'

class BundleEntryTests(unittest.TestCase):
    def test_frozen_resources_and_user_data_are_separate(self):
        spec = importlib.util.spec_from_file_location('bundle_entry', ENTRY)
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        with tempfile.TemporaryDirectory(prefix='上字幕 空白路徑') as temporary:
            resource = Path(temporary) / 'app'
            data = Path(temporary) / 'progress'
            with patch.object(sys, '_MEIPASS', str(resource), create=True), patch.dict(os.environ, {'WHISPER_PREVIEW_DATA_DIR':str(data)}, clear=True), patch.object(entry.Path, 'home', side_effect=RuntimeError('No home directory')):
                base = entry.configure()
                self.assertEqual(base, resource / 'resources')
                self.assertEqual(os.environ['WHISPER_FASTER_MODEL_DIR'], str(base / 'models' / 'faster-small'))
                self.assertEqual(os.environ['WHISPER_APP_DATA_DIR'], str(data))
                self.assertTrue(data.is_dir())
                self.assertEqual(os.environ['HF_HUB_OFFLINE'], '1')
                self.assertEqual(os.environ['HF_HUB_DISABLE_TELEMETRY'], '1')
                self.assertTrue(os.environ['PATH'].startswith(str(base / 'bin')))

    def test_freeze_support_runs_before_application_main(self):
        tree = ast.parse(ENTRY.read_text(encoding='utf-8'))
        guard = tree.body[-1]
        calls = [node.value for node in guard.body if isinstance(node, ast.Expr)]
        self.assertEqual(calls[0].func.attr, 'freeze_support')
        self.assertEqual(calls[1].func.id, 'main')

    def test_runtime_never_installs_or_downloads(self):
        text = ENTRY.read_text(encoding='utf-8')
        self.assertNotIn('snapshot_download', text)
        self.assertNotIn('pip install', text)
        self.assertNotIn('brew install', text)

    def test_frozen_repair_points_to_installer_not_script(self):
        source = ROOT / 'Whisper_Mac_一鍵安裝版' / '_internal' / 'whisper_gui_mac.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WhisperApp')
        method = next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == '_model_repair_message')
        namespace = {'os':os}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        with patch.dict(os.environ, {'SHANGZIMU_RESOURCES':'bundled'}, clear=True):
            message = namespace['_model_repair_message'](None, '模型損壞。')
            self.assertIn('完整安裝包', message)
            self.assertNotIn('啟動 Whisper', message)
            self.assertNotIn('連網', message)

if __name__ == '__main__':
    unittest.main()
