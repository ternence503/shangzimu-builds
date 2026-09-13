import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Whisper_Mac_一鍵安裝版' / '_internal'))
from subtitle_layout import layout_subtitles

EXAMPLES = ('今天很特別的是 因為我們為什麼來到這裡呢',
            '有件很重要的事情就是 我們要為我們第二張專輯拍封面')

def timed(text):
    words = []
    for index, c in enumerate(c for c in text if not c.isspace()):
        words.append({'word': c, 'start': index * .2, 'end': index * .2 + .18})
    return {'text': text, 'start': 0., 'end': len(words) * .2 + .1, 'words': words}

class ClauseLayoutTests(unittest.TestCase):
    def test_user_examples_no_orphan_or_broken_words(self):
        for text in EXAMPLES:
            cues, _ = layout_subtitles([{'text': text, 'start': 0, 'end': 10}], 18, 2)
            self.assertEqual(len(cues), 1)
            self.assertEqual(cues[0]['text'].replace('\n', ''), text)
            self.assertNotIn('這\n裡', cues[0]['text'])
            self.assertNotIn('第\n二張', cues[0]['text'])
            self.assertGreaterEqual(min(len(line.strip()) for line in cues[0]['text'].splitlines()), 6)
            self.assertLessEqual(max(len(line) for line in cues[0]['text'].splitlines()), 18)
        self.assertEqual(layout_subtitles([{'text': EXAMPLES[0], 'start': 0, 'end': 10}])[0][0]['text'].splitlines()[0].strip(), '今天很特別的是')

    def test_clauses_split_even_when_two_lines_fit(self):
        for text in EXAMPLES:
            source = timed(text)
            before = copy.deepcopy(source)
            cues, _ = layout_subtitles([source], 18, 2)
            self.assertEqual(len(cues), 2)
            self.assertEqual(''.join(c['text'].replace('\n', '') for c in cues), text)
            self.assertEqual(cues[0]['start'], source['start'])
            self.assertEqual(cues[-1]['end'], source['end'])
            self.assertEqual(cues[0]['end'], cues[1]['start'])
            self.assertIn(cues[0]['end'], [w['end'] for w in source['words']])
            self.assertEqual(sum(len(c['words']) for c in cues), len(source['words']))
            self.assertEqual(source, before)

    def test_toggle_and_invalid_times_never_invent_boundaries(self):
        source = timed(EXAMPLES[0])
        self.assertEqual(len(layout_subtitles([source], split_clauses=False)[0]), 1)
        source['words'][0]['word'] = '不同文字'
        cues, _ = layout_subtitles([source])
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]['end'], source['end'])

    def test_ordinals_and_custom_names_are_atomic(self):
        text = '今天介紹第十二張專輯與王小明的設計作品'
        cues, _ = layout_subtitles([{'text': text, 'start': 0, 'end': 12}], 8, 4, ['王小明'])
        self.assertIn('第十二張', cues[0]['text'])
        self.assertIn('王小明', cues[0]['text'])
        self.assertEqual(cues[0]['text'].replace('\n', ''), text)

if __name__ == '__main__':
    unittest.main()
