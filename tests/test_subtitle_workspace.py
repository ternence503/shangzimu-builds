import ast
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

INTERNAL = Path(__file__).resolve().parents[1] / 'Whisper_Mac_一鍵安裝版' / '_internal'
sys.path.insert(0, str(INTERNAL))
from subtitle_workspace import (parse_srt, serialize_srt, serialize_document,
                                read_document, save_new_file)


class WorkspaceTests(unittest.TestCase):
    def test_multiline_utf8_srt_roundtrip(self):
        text = '\ufeff1\r\n00:00:01,200 --> 00:00:05,400\r\n王小明介紹\r\nFinal Cut Pro\r\n'
        cues = parse_srt(text)
        self.assertEqual(cues[0]['text'], '王小明介紹\nFinal Cut Pro')
        self.assertEqual(parse_srt(serialize_srt(cues)), cues)

    def test_invalid_documents_are_rejected(self):
        for text in ['', '1\n00:00:65,000 --> 00:00:66,000\n字幕',
                     '1\n00:00:05,000 --> 00:00:04,000\n字幕']:
            with self.assertRaises(ValueError):
                parse_srt(text)

    def test_project_retains_word_timing_and_existing_file(self):
        cues = [{'start': 0, 'end': 2, 'text': '測試',
                 'words': [{'word': '測試', 'start': .1, 'end': 1.9}]}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '測試.json'
            save_new_file(path, serialize_document(cues))
            self.assertEqual(read_document(path), cues)

    def test_revision_project_keeps_manual_lines_settings_and_original(self):
        original = [{'start': 0, 'end': 3, 'text': '今天介紹產品經理'}]
        revision = [{'start': 0, 'end': 3, 'text': '今天介紹\n產品經理'}]
        settings = {'max_chars': 10, 'max_lines': 2}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '修訂.json'
            save_new_file(path, serialize_document(revision, kind='layout', settings=settings, original_segments=original))
            cues, metadata = read_document(path, with_metadata=True)
            self.assertEqual(cues, revision)
            self.assertEqual(metadata['original_segments'], original)
            self.assertEqual(metadata['settings'], settings)
            with self.assertRaises(FileExistsError):
                save_new_file(path, 'replacement')
            self.assertEqual(read_document(path), cues)

    def test_output_writer_keeps_originals_on_retranscription(self):
        # Load real output methods without importing a model, opening Tk, or networking.
        tree = ast.parse((INTERNAL / 'whisper_gui_mac.py').read_text(encoding='utf-8'))
        functions = {'_format_timestamp', '_format_srt', '_format_vtt',
                     '_dedupe_repeated_segments', '_collapse_repeated_phrase',
                     '_clamp_segment_durations'}
        constants = {'_REPEAT_STRIP_PATTERN', '_SEP_PATTERN', 'MAX_SUBTITLE_DURATION'}
        body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in functions:
                body.append(node)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets):
                body.append(node)
            if isinstance(node, ast.ClassDef) and node.name == 'WhisperApp':
                method = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == '_write_outputs')
                body.append(ast.ClassDef(name='Writer', bases=[], keywords=[], body=[method], decorator_list=[]))
        namespace = {'os': os, 'tempfile': tempfile, 're': re,
                     'save_new_file': save_new_file, 'serialize_document': serialize_document}
        exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), '<output-writer>', 'exec'), namespace)
        writer = namespace['Writer']()
        result = {'language': 'zh', 'segments': [{'start': 0, 'end': 20, 'text': '講座原稿',
                  'words': [{'word': '講座原稿', 'start': 0, 'end': 19}]}]}
        with tempfile.TemporaryDirectory() as folder:
            audio = str(Path(folder) / '講座.wav')
            first, _ = writer._write_outputs(audio, result)
            save_new_file(Path(folder) / '人工校正.srt', 'existing revision')
            second, _ = writer._write_outputs(audio, result)
            self.assertNotEqual(first['srt'], second['srt'])
            self.assertTrue(Path(first['srt']).exists())
            self.assertTrue(Path(second['srt']).exists())
            self.assertEqual(read_document(first['字幕專案'])[0]['end'], 20)
            self.assertEqual(parse_srt(Path(first['srt']).read_text(encoding='utf-8'))[0]['end'], 20)
            self.assertEqual((Path(folder) / '人工校正.srt').read_text(), 'existing revision')


if __name__ == '__main__':
    unittest.main()
