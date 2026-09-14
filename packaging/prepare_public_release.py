"""Verify downloaded CI artifacts and prepare unique GitHub Release assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

PLATFORMS = {'mac-x86_64': '.pkg', 'mac-arm64': '.pkg', 'windows-x64': '.exe'}
REPOSITORY = 'ternence503/shangzimu-builds'


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(downloads, output, commit, run_id):
    if not re.fullmatch(r'[a-f0-9]{40}', commit) or not re.fullmatch(r'\d+', run_id):
        raise ValueError('Exact verified CI commit and run required')
    if output.exists():
        raise ValueError('Fresh release staging directory required')
    selected = {}
    for manifest_path in downloads.glob('*/source-and-checksums.json'):
        if manifest_path.is_symlink():
            raise ValueError('Linked manifest rejected')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        platform = manifest.get('platform')
        if platform not in PLATFORMS or platform in selected:
            raise ValueError('Known unique platform artifacts required')
        if (manifest.get('status') != 'unsigned-public-test-not-final'
                or manifest.get('repository') != REPOSITORY
                or manifest.get('commit') != commit or str(manifest.get('run_id')) != run_id):
            raise ValueError('Artifact provenance mismatch')
        directory = manifest_path.parent
        if directory.is_symlink():
            raise ValueError('Linked artifact directory rejected')
        files = manifest['files']
        for name, information in files.items():
            if not name or Path(name).name != name or '\\' in name or ':' in name:
                raise ValueError('Safe artifact basenames required')
            path = directory / name
            if (path.is_symlink() or not path.is_file() or path.stat().st_size != information['size']
                    or sha256(path) != information['sha256']):
                raise ValueError('Artifact checksum mismatch')
        installers = [name for name in files if name.endswith(PLATFORMS[platform])]
        required = {'source-and-license-materials.zip', 'reviewed-materials-manifest.json',
                    'components.json', 'acceptance-evidence.json', 'actual-build-dependency-lock.txt'}
        if len(installers) != 1 or not required <= files.keys():
            raise ValueError('Complete installer, source and evidence files required')
        expected_name = f'上字幕-1.4.1-{platform}-公開測試未正式簽署{PLATFORMS[platform]}'
        if installers[0] != expected_name:
            raise ValueError('Exact platform-specific installer basename required')
        review = json.loads((directory / 'reviewed-materials-manifest.json').read_text(encoding='utf-8'))
        if review.get('status') != 'reviewed-for-public-test' or review.get('inventory_sha256') != sha256(directory / 'components.json'):
            raise ValueError('Material review inventory mismatch')
        selected[platform] = (directory, installers[0])
    if set(selected) != set(PLATFORMS):
        raise ValueError('All three native platform installers required')
    output.mkdir(parents=True)
    with zipfile.ZipFile(output / 'shangzimu-1.4.1-test-verification.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for platform, (directory, installer) in selected.items():
            shutil.copyfile(directory / installer, output / installer)
            shutil.copyfile(directory / 'source-and-license-materials.zip',
                            output / f'shangzimu-1.4.1-{platform}-sources.zip')
            for name in ('source-and-checksums.json', 'reviewed-materials-manifest.json', 'components.json',
                         'acceptance-evidence.json', 'actual-build-dependency-lock.txt'):
                archive.write(directory / name, platform + '/' + name)
    sums = ''.join(f'{sha256(path)}  {path.name}\n' for path in sorted(output.iterdir()))
    with (output / 'SHA256SUMS.txt').open('x', encoding='utf-8') as stream:
        stream.write(sums)
    return [path.name for path in sorted(output.iterdir())]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.downloads, args.output, args.commit, args.run_id), ensure_ascii=False))
