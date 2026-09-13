"""Stage a native pkg; release requires separate signing and acceptance."""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile
import plistlib

parser = argparse.ArgumentParser()
parser.add_argument('app', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
with (args.app / 'Contents' / 'Info.plist').open('rb') as stream:
    assert plistlib.load(stream)['CFBundleIdentifier'] == 'tw.ternence.shangzimu'
with tempfile.TemporaryDirectory(prefix='shangzimu-pkg-') as directory:
    staging = Path(directory)
    target = staging / 'payload' / 'Applications' / '上字幕.app'
    shutil.copytree(args.app, target, symlinks=True, copy_function=shutil.copy)
    for attribute in ['com.apple.FinderInfo', 'com.apple.ResourceFork']:
        subprocess.run(['/usr/bin/xattr', '-dr', attribute, str(target)], capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(target)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(target)], check=True)
    scripts = staging / 'scripts'
    shutil.copytree(Path(__file__).parent / 'installer-scripts', scripts)
    (scripts / 'preinstall').chmod(0o755)
    components = staging / 'components.plist'
    subprocess.run(['/usr/bin/pkgbuild', '--analyze', '--root', str(staging / 'payload'), str(components)], check=True)
    with components.open('rb') as stream:
        records = plistlib.load(stream)
    for record in records:
        record['BundleIsRelocatable'] = False
        record['BundleIsVersionChecked'] = False
        record['BundleHasStrictIdentifier'] = True
    with components.open('wb') as stream:
        plistlib.dump(records, stream)
    subprocess.run(['/usr/bin/pkgbuild', '--root', str(staging / 'payload'),
        '--component-plist', str(components),
        '--scripts', str(scripts), '--identifier', 'tw.ternence.shangzimu.installer',
        '--version', '1.4.1', '--install-location', '/', str(args.output)], check=True)
