"""Relocate the frozen app and deny the development runtime/model paths."""
from pathlib import Path
import argparse
import tempfile
import shutil
import subprocess
import os
import json

parser = argparse.ArgumentParser()
parser.add_argument('app', type=Path)
parser.add_argument('speech', type=Path)
parser.add_argument('report', type=Path)
args = parser.parse_args()
subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(args.app)], check=True, capture_output=True)
with tempfile.TemporaryDirectory(prefix='shangzimu-relocation-', dir='/private/tmp') as directory:
    base = Path(directory)
    app = base / '獨立位置' / '上字幕.app'
    shutil.copytree(args.app, app, symlinks=True, copy_function=shutil.copy)
    for attribute in ['com.apple.FinderInfo', 'com.apple.ResourceFork']:
        subprocess.run(['/usr/bin/xattr', '-dr', attribute, str(app)], capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], check=True, capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True, capture_output=True)
    speech = base / 'speech.aiff'
    shutil.copy2(args.speech, speech)
    report = base / 'report.json'
    env = dict(os.environ, PATH='/usr/bin:/bin', PYTHONPATH='', PYTHONHOME='',
        WHISPER_PREVIEW_DATA_DIR=str(base / 'data'), SHANGZIMU_TEST_AUDIO=str(speech))
    profile = '(version 1)(allow default)(deny network*)(deny file-read* (subpath "/usr/local") (subpath "/opt/homebrew") (subpath "/Users"))'
    command = ['/usr/bin/sandbox-exec', '-p', profile,
        str(app / 'Contents' / 'MacOS' / 'ShangZiMu'), '--self-test', str(report)]
    result = subprocess.run(command, env=env, cwd=base, capture_output=True, text=True, timeout=90)
    data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {'status':'failed'}
    data.update(returncode=result.returncode, stderr=result.stderr,
        development_paths_denied=True, relocated=True,
        adhoc_signature_verified=True,
        os_network_denied=True,
        limitation='Same installed macOS, not a fresh operating-system VM')
    args.report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    assert result.returncode == 0 and data['status'] == 'passed', data
