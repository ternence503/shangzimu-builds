from pathlib import Path
import os
import re
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent.parent
source = root / 'Whisper_Mac_一鍵安裝版' / '_internal'
model = Path(os.environ['SHANGZIMU_MODEL_DIR'])
tools = Path(os.environ['SHANGZIMU_TOOLS_DIR'])
datas = [(str(model), 'resources/models/faster-small'),
         (str(source.parent / '範例'), 'resources/examples'),
         (str(source.parent / '新手指南.txt'), 'resources/guide.txt')]
notice = model.parent.parent / 'THIRD-PARTY-NOTICES.txt'
if notice.is_file():
    datas.append((str(notice), 'resources'))
binaries = [(str(tools / name), 'resources/bin') for name in ['ffmpeg', 'ffprobe']]
hiddenimports = []
for package in ['faster_whisper', 'ctranslate2', 'onnxruntime', 'opencc']:
    d, b, h = collect_all(package)
    datas += d; binaries += b; hiddenimports += h
a = Analysis([str(root / 'packaging' / 'entry.py')], pathex=[str(source)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['torch', 'demucs', 'edge_tts'], noarchive=False)
# Broad hooks collect optional standalone C API / audio-plugin libraries that
# are not imported by our CPU ONNX Python binding or file-transcription path.
# Remove only these names. Closure audit and real offline decoding must still
# pass after removal; never exclude an unresolved required dependency.
def optional_unused_library(destination):
    name = Path(destination).name
    return name == 'libmpg123.0.dylib' or bool(re.fullmatch(r'libonnxruntime\.\d+(?:\.\d+)*\.dylib', name))
a.binaries = [record for record in a.binaries if not optional_unused_library(record[0])]
a.datas = [record for record in a.datas if not optional_unused_library(record[0])]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ShangZiMu',
          debug=False, strip=False, upx=False, console=False, target_arch=os.environ['SHANGZIMU_ARCH'])
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ShangZiMu')
app = BUNDLE(coll, name='上字幕.app', bundle_identifier='tw.ternence.shangzimu',
    info_plist={'CFBundleName':'上字幕', 'CFBundleDisplayName':'上字幕',
                'CFBundleShortVersionString':'1.4.1', 'CFBundleVersion':'1',
                'LSApplicationCategoryType':'public.app-category.productivity',
                'NSHighResolutionCapable':True,
                'LSMinimumSystemVersion':'14.0'})
