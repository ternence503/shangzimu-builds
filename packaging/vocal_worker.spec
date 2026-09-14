"""Build in the separate CPU-only PyTorch worker environment."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas, binaries, hiddenimports = collect_all('openunmix')
a = Analysis([str(root / 'vocal_worker.py')], pathex=[str(root)],
    datas=datas, binaries=binaries, hiddenimports=hiddenimports,
    excludes=['demucs', 'tensorflow', 'matplotlib', 'IPython', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='VocalWorker',
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='vocals')
