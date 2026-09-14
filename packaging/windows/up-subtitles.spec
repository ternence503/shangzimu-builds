"""Run only on Windows x64; all input resources must already be prepared."""
import os
import platform
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
    raise RuntimeError("Windows x64 native build required; cross-compilation is not supported")
repo = Path(SPECPATH).resolve().parents[1]
root = repo / "packaging"
gui_dir = repo / "Whisper_Mac_一鍵安裝版" / "_internal"
resources = Path(os.environ["SHANGZIMU_BUILD_RESOURCES"]).resolve()
datas = [(str(resources), "resources")]
datas += [(str(root / 'guide-full.txt'), 'resources')]
separator = Path(os.environ['SHANGZIMU_SEPARATOR_DIR'])
separator_models = Path(os.environ['SHANGZIMU_SEPARATOR_MODELS'])
if not (separator / 'VocalWorker.exe').is_file() or not (separator_models / 'vocals-b62c91ce.pth').is_file():
    raise ValueError('Complete Windows-native separation worker and model required')
datas += [(str(separator_models), 'resources/models/vocals')]
datas += [(str(gui_dir / "version.txt"), ".")]
# GUI resolves example/guide paths relative to __file__; support that layout too.
datas += [(str(resources / "examples"), "範例"), (str(resources / "guide.txt"), "新手指南.txt")]
binaries, hiddenimports = [], []
for package in ("faster_whisper", "ctranslate2", "av", "tokenizers", "opencc", "onnxruntime", "edge_tts"):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("faster-whisper")
a = Analysis([str(root / "entry.py")], pathex=[str(gui_dir)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports + ["whisper_gui_mac", "tkinter"],
             hookspath=[], runtime_hooks=[], excludes=["torch", "whisper", "demucs", "tensorflow"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="上字幕", console=False,
          debug=False, strip=False, upx=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="上字幕")
