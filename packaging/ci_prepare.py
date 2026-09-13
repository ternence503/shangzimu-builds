"""Prepare public build dependencies; no private audio or credentials."""
from pathlib import Path
import argparse
import shutil
import sys
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('resources', type=Path)
parser.add_argument('--tools', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = root / 'Whisper_Mac_一鍵安裝版'
sys.path.insert(0, str(source / '_internal'))
from download_model import download_model
resources = args.resources.resolve()
assert not resources.exists(), 'Use a fresh resources directory'
resources.mkdir(parents=True)
download_model('small', resources / 'models')
shutil.copytree(source / '範例', resources / 'examples')
shutil.copyfile(source / '新手指南.txt', resources / 'guide.txt')
(resources / 'bin').mkdir()
for name in ['ffmpeg', 'ffprobe']:
    filename = name + ('.exe' if sys.platform == 'win32' else '')
    shutil.copy(args.tools / filename, resources / 'bin' / filename)
if sys.platform == 'win32':
    subprocess.run([sys.executable, str(root / 'packaging' / 'windows' / 'prepare_language.py'),
                    str(resources / 'licenses' / 'inno-setup')], check=True)
# Internal test marker, deliberately NOT a redistribution-license clearance.
(resources / 'THIRD-PARTY-NOTICES.txt').write_text(
    'INTERNAL BUILD VALIDATION ONLY — NOT FOR REDISTRIBUTION.\n'
    'Licenses, exact tool sources, notices and source-offer requirements remain to be reviewed.\n'
    'Public dependencies: SYSTRAN faster-whisper-small, CTranslate2, faster-whisper, '
    'Python/Tcl/Tk, OpenCC, ONNX Runtime, FFmpeg and their dependencies.\n', encoding='utf-8')
