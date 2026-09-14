import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BundledGuideTests(unittest.TestCase):
    def test_guide_matches_bundled_installation(self):
        guide = (ROOT / 'packaging/bundled-guide.txt').read_text(encoding='utf-8')
        for instruction in ['.pkg', '.exe', '應用程式', '開始功能表', '不需要另外安裝 Python',
                            '不需要網路', 'JSON', 'SRT', '未正式簽署']:
            self.assertIn(instruction, guide)
        for obsolete in ['▶ 啟動 Whisper', 'setup_and_run', '下載模型後']:
            self.assertNotIn(obsolete, guide)

    def test_both_platforms_receive_prepared_guide(self):
        preparation = (ROOT / 'packaging/ci_prepare.py').read_text(encoding='utf-8')
        mac = (ROOT / 'packaging/mac/app.spec').read_text(encoding='utf-8')
        windows = (ROOT / 'packaging/windows/up-subtitles.spec').read_text(encoding='utf-8')
        self.assertIn("root / 'packaging' / 'bundled-guide.txt'", preparation)
        self.assertIn("(str(root / 'packaging' / 'guide-full.txt'), 'resources')", mac)
        self.assertIn("(str(root / 'guide-full.txt'), 'resources')", windows)
        self.assertIn('"resources"', windows)
