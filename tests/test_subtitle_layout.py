import copy
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'Whisper_Mac_一鍵安裝版' / '_internal' / 'subtitle_layout.py'
spec = importlib.util.spec_from_file_location('subtitle_layout', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
layout_subtitles = module.layout_subtitles
split_subtitle_at = module.split_subtitle_at


class LayoutTests(unittest.TestCase):
    def assert_lossless(self, original, cues):
        self.assertEqual(''.join(c['text'].replace('\n', '') for c in cues), original)

    def test_wrap_preserves_long_duration_and_input(self):
        source = [{'start': 1, 'end': 21, 'text': '今天我們一起來討論字幕排版。', 'extra': {'x': 1}}]
        before = copy.deepcopy(source)
        cues, _ = layout_subtitles(source, 8, 2)
        self.assertEqual((cues[0]['start'], cues[0]['end']), (1, 21))
        self.assert_lossless(source[0]['text'], cues)
        self.assertEqual(source, before)
        self.assertIsNot(cues[0], source[0])

    def test_timed_split_is_lossless_and_nonoverlapping(self):
        text = '今天講座，介紹產品。大家一起，討論設計。'
        pieces = ['今天講座', '介紹產品', '大家一起', '討論設計']
        words = [{'word': t, 'start': i * 3, 'end': i * 3 + 2} for i, t in enumerate(pieces)]
        cues, _ = layout_subtitles([{'start': 0, 'end': 13, 'text': text, 'words': words}], 5, 2)
        self.assertGreater(len(cues), 1)
        self.assert_lossless(text, cues)
        self.assertEqual(cues[0]['start'], 0)
        self.assertEqual(cues[-1]['end'], 13)
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a['end'], b['start'])
            self.assertIn(a['end'], [w['end'] for w in words])

    def test_missing_or_unreliable_timing_falls_back(self):
        for words in (None, [{'word': '錯誤', 'start': 0, 'end': 1}],
                      [{'word': '一二三四五六七八九十', 'start': 0, 'end': 20}]):
            seg = {'start': 0, 'end': 12, 'text': '一二三四五六七八九十', 'words': words}
            cues, warnings = layout_subtitles([seg], 2, 2)
            self.assertEqual(len(cues), 1)
            self.assertEqual(cues[0]['end'], 12)
            self.assert_lossless(seg['text'], cues)
            self.assertTrue(any('原稿第 1 塊' in w and '逐詞時間' in w for w in warnings))

    def test_protected_names_english_numbers_and_punctuation(self):
        text = '王小明使用Final Cut Pro，走了100公里。'
        cues, warnings = layout_subtitles([{'start': 0, 'end': 20, 'text': text}], 5, 2, ['王小明', 'Final Cut Pro'])
        self.assert_lossless(text, cues)
        for term in ['王小明', 'Final Cut Pro', '100公里']:
            self.assertIn(term, cues[0]['text'])
        self.assertTrue(any('完整詞組' in w for w in warnings))

    def test_invalid_values(self):
        for start, end in [(0, 0), (3, 1), (-1, 2), (0, float('nan')), (True, 2), ('0', 2)]:
            with self.assertRaises(ValueError):
                layout_subtitles([{'start': start, 'end': end, 'text': '字幕'}])
        for chars, lines in [(0, 2), (18, 0), (True, 2), (2.5, 2)]:
            with self.assertRaises(ValueError):
                layout_subtitles([], chars, lines)

    def test_empty_input_and_empty_text(self):
        self.assertEqual(layout_subtitles([]), ([], []))
        for text in ['', '  ', '\n\r\n']:
            with self.assertRaises(ValueError):
                layout_subtitles([{'start': 0, 'end': 1, 'text': text}])

    def test_manual_split_preserves_text_words_and_duration(self):
        cue = {'start': 0, 'end': 12, 'text': '今天，\n討論字幕。',
               'words': [{'word': '今天', 'start': 1, 'end': 3},
                         {'word': '討論', 'start': 4, 'end': 6},
                         {'word': '字幕', 'start': 7, 'end': 10}]}
        before = copy.deepcopy(cue)
        result = split_subtitle_at(cue, 4)
        self.assertEqual(''.join(c['text'] for c in result), cue['text'])
        self.assertEqual((result[0]['start'], result[0]['end'], result[1]['start'], result[1]['end']), (0, 3, 3, 12))
        self.assertEqual(len(result[0]['words']), 1)
        self.assertEqual(cue, before)
        with self.assertRaises(ValueError):
            split_subtitle_at(cue, 1)
        with self.assertRaises(ValueError):
            split_subtitle_at({'start': 0, 'end': 4, 'text': '沒有時間'}, 2)

    def test_automatic_split_retains_words_for_manual_resplit(self):
        words = [{'word': c, 'start': i, 'end': i + .8} for i, c in enumerate('一二三四五六七八')]
        cues, _ = layout_subtitles([{'start': 0, 'end': 9, 'text': '一二三四五六七八', 'words': words}], 2, 2)
        self.assertEqual(sum(len(c['words']) for c in cues), 8)
        result = split_subtitle_at(cues[0], 1)
        self.assertEqual(result[0]['end'], .8)

    def test_pause_preference_and_overlapping_word_fallback(self):
        words = [{'word': c, 'start': s, 'end': e} for c, s, e in
                 [('一', 0, .5), ('二', .5, 1), ('三', 2, 2.5), ('四', 2.5, 3), ('五', 3, 4)]]
        seg = {'start': 0, 'end': 6, 'text': '一二三四五', 'words': words}
        cues, _ = layout_subtitles([seg], 2, 2)
        self.assertEqual(cues[0]['text'], '一二')
        self.assertEqual(cues[0]['end'], 1)
        words[2]['start'] = .8
        cues, warnings = layout_subtitles([seg], 2, 2)
        self.assertEqual(len(cues), 1)
        self.assertTrue(warnings)

    def test_whitespace_losslessness(self):
        text = ' 一二  三四五六  '
        words = [{'word': c, 'start': i, 'end': i + .5} for i, c in enumerate('一二三四五六')]
        cues, _ = layout_subtitles([{'start': 0, 'end': 9, 'text': text, 'words': words}], 3, 2)
        self.assert_lossless(text, cues)
        for cue in cues:
            self.assertGreater(cue['end'], cue['start'])

    def test_existing_multiline_is_reflowed_without_blank_srt_lines(self):
        text = '一二\r\n\n三四\n五六七八'
        words = [{'word': c, 'start': i, 'end': i + .8} for i, c in enumerate('一二三四五六七八')]
        source = [{'start': 0, 'end': 10, 'text': text, 'words': words},
                  {'start': 11, 'end': 14, 'text': '其他字幕'}]
        cues, _ = layout_subtitles(source, 2, 2)
        self.assertEqual(''.join(c['text'].replace('\n', '') for c in cues if c['source_index'] == 1),
                         '一二三四五六七八')
        self.assertEqual([c['source_index'] for c in cues], [1, 1, 2])
        for cue in cues:
            self.assertTrue(all(line.strip() for line in cue['text'].split('\n')))
        self.assertEqual(cues[0]['start'], 0)
        self.assertEqual(cues[1]['end'], 10)
        result = split_subtitle_at(cues[0], 1)
        self.assertEqual(result[0]['end'], .8)


if __name__ == '__main__':
    unittest.main()
