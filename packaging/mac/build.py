"""Build native Intel Mac bundle. No user environment modification."""
from pathlib import Path
import argparse
import os
import sys
import subprocess
import platform

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=Path, required=True)
parser.add_argument('--tools', type=Path, required=True)
parser.add_argument('--dist', type=Path, required=True)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--arch', choices=['x86_64', 'arm64'], default=platform.machine())
args = parser.parse_args()
assert sys.platform == 'darwin', 'Build on macOS'
assert args.arch == platform.machine(), 'Use the target architecture native Python and dependencies'
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'Whisper_Mac_一鍵安裝版' / '_internal'))
from download_model import model_ready
assert model_ready(args.model, full=True), 'Complete validated model required'
for name in ['ffmpeg', 'ffprobe']:
    assert (args.tools / name).is_file(), name
env = dict(os.environ, SHANGZIMU_MODEL_DIR=str(args.model.resolve()), SHANGZIMU_TOOLS_DIR=str(args.tools.resolve()), SHANGZIMU_ARCH=args.arch)
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
    '--distpath', str(args.dist), '--workpath', str(args.work),
    str(Path(__file__).with_name('app.spec'))], env=env, check=True)
app = args.dist / '上字幕.app'
# Finder metadata from input resources is not executable content. Remove only
# these metadata attributes on the generated artifact; never strip quarantine.
for attribute in ['com.apple.FinderInfo', 'com.apple.ResourceFork']:
    subprocess.run(['/usr/bin/xattr', '-dr', attribute, str(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
