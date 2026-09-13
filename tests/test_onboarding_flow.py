"""Run actual GUI methods without importing models, opening Tk, or networking."""
import ast
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
INTERNAL = ROOT / 'Whisper_Mac_一鍵安裝版' / '_internal'
sys.path.insert(0, str(INTERNAL))
from subtitle_workspace import (serialize_document, serialize_srt, save_new_file,
                                next_revision_path, write_recovery, read_document)


def load_app_methods():
    tree = ast.parse((INTERNAL / 'whisper_gui_mac.py').read_text(encoding='utf-8'))
    names = {'_save_layout', 'save_layout_project', 'export_layout_srt',
             '_confirm_project_saved', 'on_close', '_remember_layout', 'undo_layout',
             '_autosave_layout', '_restore_recovery', '_layout_settings',
             '_set_layout_source', '_get_faster_model', '_get_model', '_model_repair_message'}
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WhisperApp')
    body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
            ast.ClassDef(name='App', bases=[], keywords=[], decorator_list=[],
                         body=[n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names])]
    ns = dict(copy=copy, json=json, os=os, Path=Path, serialize_document=serialize_document,
              serialize_srt=serialize_srt, save_new_file=save_new_file,
              next_revision_path=next_revision_path, write_recovery=write_recovery,
              read_document=read_document, messagebox=Mock(), filedialog=Mock(),
              tk=types.SimpleNamespace(NORMAL='normal', END='end', DISABLED='disabled'),
              _FasterWhisperModel=Mock(), FASTER_COMPUTE_TYPE='int8', whisper=Mock())
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), '<actual-gui>', 'exec'), ns)
    return ns['App'], ns


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.App, self.ns = load_app_methods()
        self.app = self.App()
        a = self.app
        a.layout_result = [{'start': 0, 'end': 2, 'text': '測試\n字幕'}]
        a.layout_source = [{'start': 0, 'end': 2, 'text': '測試字幕'}]
        a.layout_source_path = '講座.json'
        a.layout_dirty = True
        a.layout_status_var = Mock()
        a.layout_chars_var = Mock(get=Mock(return_value='18'))
        a.layout_lines_var = Mock(get=Mock(return_value='2'))
        a.layout_preset_var = Mock(get=Mock(return_value='橫式講座／長片'))
        a.layout_terms_var = Mock(get=Mock(return_value='Final Cut Pro'))
        a.layout_clauses_var = Mock(get=Mock(return_value=True))
        a.layout_warnings = []
        a.layout_auto_warnings = []
        a.layout_history = []
        a._recheck_layout_warnings = Mock()
        a._refresh_layout_tree = Mock()
        a.root = Mock()
        a.worker_thread = a.lyrics_worker_thread = a.tts_worker_thread = None
        a.recovery_failed = False
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        a.recovery_path = Path(self.temp.name) / 'recovery' / 'subtitle.json'

    def test_srt_export_does_not_mark_project_saved(self):
        path = Path(self.temp.name) / '字幕.srt'
        self.ns['filedialog'].asksaveasfilename.return_value = str(path)
        self.app.export_layout_srt()
        self.assertTrue(path.exists())
        self.assertTrue(self.app.layout_dirty)

    def test_save_project_returns_success_and_keeps_manual_lines(self):
        path = Path(self.temp.name) / '字幕.json'
        self.ns['filedialog'].asksaveasfilename.return_value = str(path)
        self.assertTrue(self.app.save_layout_project())
        self.assertFalse(self.app.layout_dirty)
        self.assertEqual(read_document(path)[0]['text'], '測試\n字幕')

    def test_cancelled_save_blocks_close_and_source_replacement(self):
        self.ns['messagebox'].askyesnocancel.return_value = True
        self.ns['filedialog'].asksaveasfilename.return_value = ''
        old = copy.deepcopy(self.app.layout_source)
        self.app.on_close()
        self.app._set_layout_source([{'start': 0, 'end': 1, 'text': '新稿'}], '新稿.srt')
        self.app.root.destroy.assert_not_called()
        self.assertEqual(self.app.layout_source, old)
        self.assertTrue(self.app.layout_dirty)

    def test_failed_save_blocks_close(self):
        self.ns['messagebox'].askyesnocancel.return_value = True
        self.ns['filedialog'].asksaveasfilename.return_value = str(Path(self.temp.name) / '字幕.json')
        self.ns['save_new_file'] = Mock(side_effect=OSError('permission denied'))
        self.app.on_close()
        self.app.root.destroy.assert_not_called()
        self.assertTrue(self.app.layout_dirty)

    def test_active_worker_blocks_close_before_any_save_prompt(self):
        self.app.worker_thread = Mock(is_alive=Mock(return_value=True))
        self.app.on_close()
        self.app.root.destroy.assert_not_called()
        self.ns['messagebox'].askyesnocancel.assert_not_called()

    def test_open_edit_dialog_blocks_main_window_close(self):
        self.app.layout_editing = True
        self.app.on_close()
        self.app.root.destroy.assert_not_called()
        self.ns['messagebox'].askyesnocancel.assert_not_called()

    def test_bad_revision_path_returns_failure_with_friendly_error(self):
        self.ns['next_revision_path'] = Mock(side_effect=ValueError('too many versions'))
        self.assertFalse(self.app.save_layout_project())
        self.ns['messagebox'].showerror.assert_called_once()
        self.ns['filedialog'].asksaveasfilename.assert_not_called()
        self.assertTrue(self.app.layout_dirty)

    def test_modal_cancel_keeps_changed_text_until_confirmed(self):
        tree = ast.parse((INTERNAL / 'whisper_gui_mac.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                      and n.name == 'edit_layout_cue')
        cancel = next(n for n in method.body if isinstance(n, ast.FunctionDef)
                      and n.name == 'cancel_edit')
        editor, dialog, messagebox = Mock(), Mock(), Mock()
        editor.get.return_value = '修改後'
        messagebox.askyesno.return_value = False
        ns = {'editor': editor, 'dialog': dialog, 'messagebox': messagebox,
              'cue': {'text': '原稿'}}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cancel], type_ignores=[])),
                     '<actual-modal-cancel>', 'exec'), ns)
        ns['cancel_edit']()
        dialog.destroy.assert_not_called()
        messagebox.askyesno.return_value = True
        ns['cancel_edit']()
        dialog.destroy.assert_called_once()
        source = ast.unparse(method)
        self.assertIn("dialog.protocol('WM_DELETE_WINDOW', cancel_edit)", source)
        self.assertIn('dialog.grab_set()', source)

    def test_split_capability_rejects_no_timing_and_one_unsplittable_word(self):
        from subtitle_layout import has_split_timing
        self.assertFalse(has_split_timing({'start': 0, 'end': 2, 'text': '完整一句'}))
        self.assertFalse(has_split_timing({'start': 0, 'end': 2, 'text': '完整一句',
            'words': [{'word': '完整一句', 'start': 0, 'end': 2}]}))
        self.assertTrue(has_split_timing({'start': 0, 'end': 2, 'text': '完整一句',
            'words': [{'word': '完整', 'start': 0, 'end': 1},
                      {'word': '一句', 'start': 1, 'end': 2}]}))

    def test_undo_restores_text_and_updates_local_recovery(self):
        before = copy.deepcopy(self.app.layout_result)
        self.app._remember_layout()
        self.app.layout_result[0]['text'] = '修改後'
        self.app.undo_layout()
        self.assertEqual(self.app.layout_result, before)
        self.assertTrue(self.app.layout_dirty)
        self.assertEqual(read_document(self.app.recovery_path), before)

    def test_restore_recovery_retains_original_and_manual_edits(self):
        self.app._autosave_layout()
        expected = copy.deepcopy(self.app.layout_result)
        self.app.layout_dirty = False
        self.app.layout_result = []
        self.app.notebook = Mock()
        self.app.layout_original_preview = Mock()
        self.ns['messagebox'].askyesno.return_value = True
        self.app._restore_recovery()
        self.assertEqual(self.app.layout_result, expected)
        self.assertTrue(self.app.layout_dirty)
        self.app.notebook.select.assert_called_with(3)

    def test_revision_names_preserve_prior_file(self):
        path = Path(self.temp.name) / '字幕.json'
        save_new_file(path, 'original')
        revision = next_revision_path(path)
        self.assertNotEqual(path, revision)
        save_new_file(revision, 'revision')
        self.assertEqual(path.read_text(), 'original')

    def test_model_constructor_is_explicitly_local_only(self):
        # Static regression: do not call a named remote model without the offline flag.
        tree = ast.parse((INTERNAL / 'whisper_gui_mac.py').read_text(encoding='utf-8'))
        constructors = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name) and n.func.id == '_FasterWhisperModel']
        self.assertTrue(constructors)
        for call in constructors:
            flags = {k.arg: k.value for k in call.keywords}
            self.assertIn('local_files_only', flags)
            self.assertTrue(isinstance(flags['local_files_only'], ast.Constant)
                            and flags['local_files_only'].value is True)

    def test_local_model_load_uses_validated_directory_and_cache(self):
        self.app.faster_model_cache = {}
        self.app._update_status = Mock()
        directory = str(Path(self.temp.name) / 'faster-small')
        with patch.dict(os.environ, {'WHISPER_FASTER_MODEL_DIR': directory}), \
             patch('download_model.model_ready', return_value=True):
            first = self.app._get_faster_model('small')
            self.assertIs(self.app._get_faster_model('small'), first)
        constructor = self.ns['_FasterWhisperModel']
        constructor.assert_called_once()
        self.assertEqual(constructor.call_args.args[0], directory)
        self.assertIs(constructor.call_args.kwargs['local_files_only'], True)

    def test_missing_local_model_does_not_trigger_download(self):
        self.app.faster_model_cache = {}
        with patch.dict(os.environ, {'WHISPER_FASTER_MODEL_DIR': ''}):
            with self.assertRaises(RuntimeError):
                self.app._get_faster_model('small')
        self.ns['_FasterWhisperModel'].assert_not_called()
        with self.assertRaises(RuntimeError):
            self.app._get_model('small')
        self.ns['whisper'].load_model.assert_not_called()

    def test_installers_use_isolated_environment_and_common_local_model(self):
        mac = (INTERNAL / 'setup_and_run_mac.sh').read_text(encoding='utf-8')
        win = (ROOT / 'Whisper_Windows_一鍵安裝版' / '_internal' / 'setup_and_run.ps1').read_text(encoding='utf-8-sig')
        for script in (mac, win):
            self.assertIn('SubtitlePreview', script)
            self.assertIn('WHISPER_FASTER_MODEL_DIR', script)
            self.assertIn('faster-small', script)
            self.assertIn('download_model.py', script)
            self.assertIn('HF_HUB_OFFLINE', script)
            self.assertIn('venv-backup-', script)
            self.assertIn('last-launch.log', script)
        self.assertIn('Whisper 字幕試用版.lnk', win)
        self.assertNotIn('01-install-and-run.bat', win)
        self.assertNotIn('WindowStyle = 7', win)


if __name__ == '__main__':
    unittest.main()
