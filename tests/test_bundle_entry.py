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

    def test_network_probe_has_real_baseline_and_denied_results(self):
        spec = importlib.util.spec_from_file_location('bundle_entry_network', ENTRY)
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        import json
        import socket
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / 'baseline.json'
            denied = Path(folder) / 'denied.json'
            with patch.object(socket, 'create_connection', return_value=MagicMock()) as connect:
                entry.network_probe(baseline)
                connect.assert_called_once_with(('example.com', 443), timeout=5)
            with patch.object(socket, 'create_connection', side_effect=TimeoutError):
                entry.network_probe(denied)
            self.assertTrue(json.loads(baseline.read_text(encoding='utf-8'))['connected'])
            result = json.loads(denied.read_text(encoding='utf-8'))
            self.assertFalse(result['connected'])
            self.assertFalse(result['python_socket_patch_applied'])
            with self.assertRaises(FileExistsError):
                with patch.object(socket, 'create_connection', side_effect=TimeoutError):
                    entry.network_probe(denied)

    def test_normal_startup_disables_native_onnx_telemetry(self):
        tree = ast.parse(ENTRY.read_text(encoding='utf-8'))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        ordered = [ast.unparse(n) for n in main.body]
        telemetry = next(i for i, text in enumerate(ordered) if text == 'onnxruntime.disable_telemetry_events()')
        gui = next(i for i, text in enumerate(ordered) if text == 'gui.main()')
        self.assertLess(telemetry, gui)

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
