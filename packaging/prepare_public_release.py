"""Verify downloaded CI artifacts and prepare unique GitHub Release assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

PLATFORMS = {'mac-x86_64': '.pkg', 'mac-arm64': '.pkg', 'windows-x64': '.exe'}
REPOSITORY = 'ternence503/shangzimu-builds'
VERSION = '1.5.0'
MATERIAL_SCOPES = {'main-runtime', 'vocal-worker', 'umx-hq'}
MIXED_SOURCE_DIFFERENCES = frozenset({
    '.github/workflows/bundle-validation.yml',
    'packaging/windows/msvc_environment.cmd',
    'tests/test_windows_msvc_environment.py',
})
SAFE_MSVC_BATCH = '''@echo off
rem Keep spaced Visual Studio paths inside cmd, not nested PowerShell /c quotes.
call "%~1" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 exit /b 1
set PATH
set LIB
set INCLUDE
set VCToolsInstallDir
set WindowsSdkDir
set WindowsSDKVersion
exit /b 0
'''
OLD_CONCURRENCY = '  group: bundled-validation-${{ github.ref }}'
NEW_CONCURRENCY = '  group: bundled-validation-${{ github.sha }}'
OLD_MSVC = '''          $devValues = & cmd.exe /d /s /c ('""' + $devCmd + '" -arch=x64 -host_arch=x64 >nul && set"')'''
NEW_MSVC = r'          $devValues = & cmd.exe /d /c packaging\windows\msvc_environment.cmd $devCmd'


def normalize_workflow(text):
    return text.replace(OLD_CONCURRENCY, NEW_CONCURRENCY).replace(OLD_MSVC, NEW_MSVC)


def platform_expectations(commit, run_id, mapping=None, source_repository=None):
    expected = {platform: {'commit': commit, 'run_id': run_id} for platform in PLATFORMS}
    differences = {platform: [] for platform in PLATFORMS}
    if mapping is None:
        return expected, differences
    if not isinstance(mapping, dict) or set(mapping) != set(PLATFORMS):
        raise ValueError('Exact complete three-platform provenance mapping required')
    if source_repository is None:
        raise ValueError('Local source Git repository required for mixed provenance')
    repository = Path(source_repository).resolve()
    def git(*arguments):
        try:
            return subprocess.check_output(['git', '-C', str(repository), *arguments], stderr=subprocess.PIPE)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError('Source Git verification failed') from exc
    if Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != repository:
        raise ValueError('Exact source Git repository root required')
    for platform, information in mapping.items():
        if not isinstance(information, dict) or set(information) != {'commit', 'run_id'}:
            raise ValueError('Exact platform commit and run fields required')
        sha, run = information['commit'], str(information['run_id'])
        if not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{40}', sha) or not re.fullmatch(r'\d+', run):
            raise ValueError('Exact platform commit and numeric run required')
        for revision in {commit, sha}:
            if git('rev-parse', '--verify', revision + '^{commit}').decode().strip() != revision:
                raise ValueError('Exact source commits must exist locally')
        paths = [name.decode('utf-8') for name in git('diff', '--no-ext-diff', '--no-textconv',
                 '--no-renames', '--name-only', '-z', commit, sha, '--').split(b'\0') if name]
        if not set(paths) <= MIXED_SOURCE_DIFFERENCES:
            raise ValueError('Mixed artifacts differ in application, build recipe or unapproved source')
        if paths:
            target_workflow = git('show', commit + ':.github/workflows/bundle-validation.yml').decode('utf-8')
            artifact_workflow = git('show', sha + ':.github/workflows/bundle-validation.yml').decode('utf-8')
            if normalize_workflow(target_workflow) != normalize_workflow(artifact_workflow):
                raise ValueError('Mixed workflow changes exceed the known quoting/concurrency fix')
            if NEW_MSVC not in target_workflow or NEW_CONCURRENCY not in target_workflow:
                raise ValueError('Release target must contain the reviewed Windows workflow fix')
            target_batch = git('show', commit + ':packaging/windows/msvc_environment.cmd').decode('utf-8').replace('\r\n', '\n')
            if target_batch != SAFE_MSVC_BATCH:
                raise ValueError('Release target MSVC batch is not the reviewed safe content')
            artifact_batch_path = sha + ':packaging/windows/msvc_environment.cmd'
            try:
                artifact_batch = git('show', artifact_batch_path).decode('utf-8').replace('\r\n', '\n')
            except ValueError:
                artifact_batch = None
            if artifact_batch is not None and artifact_batch != SAFE_MSVC_BATCH:
                raise ValueError('Artifact source MSVC batch is not absent or reviewed safe content')
        expected[platform] = {'commit': sha, 'run_id': run}
        differences[platform] = sorted(paths)
    return expected, differences


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_vocal_materials(directory):
    manifest_path = directory / 'vocal-materials-manifest.json'
    review = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (review.get('schema') != 1 or review.get('status') != 'reviewed-for-public-test'
            or review.get('scope') != 'final-frozen-vocal-worker'
            or not review.get('native_files')):
        raise ValueError('Final reviewed VocalWorker manifest required')
    natives = review.get('native_files', [])
    if not natives:
        raise ValueError('Final VocalWorker native inventory required')
    for item in natives:
        path = str(item.get('path', ''))
        if (re.search(r'(^|[/\\])[^/\\]*sox[^/\\]*(?:\.dll|\.pyd|\.so|\.dylib)$', path, re.I)
                or item.get('status') != 'reviewed-for-public-test'
                or not item.get('owner') or not str(item.get('source_url', '')).startswith('https://')
                or not item.get('license_paths')):
            raise ValueError('Every VocalWorker native needs a reviewed mapping and native SoX is forbidden')
    expected = {'vocal-worker/vocal-materials-manifest.json'}
    expected.update('vocal-worker/' + entry['path'] for entry in review.get('materials', []))
    archive_path = directory / 'source-and-license-materials.zip'
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        if not expected <= names:
            raise ValueError('VocalWorker source/license payload missing from archive')
        if hashlib.sha256(archive.read('vocal-worker/vocal-materials-manifest.json')).hexdigest() != sha256(manifest_path):
            raise ValueError('Archived VocalWorker manifest differs from release manifest')
        for entry in review.get('materials', []):
            if hashlib.sha256(archive.read('vocal-worker/' + entry['path'])).hexdigest() != entry['sha256']:
                raise ValueError('Archived VocalWorker material hash mismatch')
    return review


def prepare(downloads, output, commit, run_id, platform_provenance=None, source_repository=None):
    if not re.fullmatch(r'[a-f0-9]{40}', commit) or not re.fullmatch(r'\d+', run_id):
        raise ValueError('Exact verified CI commit and run required')
    if output.exists():
        raise ValueError('Fresh release staging directory required')
    expected, source_differences = platform_expectations(commit, run_id, platform_provenance, source_repository)
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
                or manifest.get('commit') != expected[platform]['commit']
                or str(manifest.get('run_id')) != expected[platform]['run_id']):
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
                    'vocal-materials-manifest.json', 'components.json',
                    'acceptance-evidence.json', 'actual-build-dependency-lock.txt'}
        if len(installers) != 1 or not required <= files.keys():
            raise ValueError('Complete installer, source and evidence files required')
        expected_name = f'上字幕-{VERSION}-{platform}-公開測試未正式簽署{PLATFORMS[platform]}'
        if installers[0] != expected_name:
            raise ValueError('Exact platform-specific installer basename required')
        review = json.loads((directory / 'reviewed-materials-manifest.json').read_text(encoding='utf-8'))
        if review.get('status') != 'reviewed-for-public-test' or review.get('inventory_sha256') != sha256(directory / 'components.json'):
            raise ValueError('Material review inventory mismatch')
        if set(manifest.get('material_scopes', [])) != MATERIAL_SCOPES:
            raise ValueError('Main runtime, VocalWorker and UMX-HQ material scopes required')
        verify_vocal_materials(directory)
        selected[platform] = (directory, installers[0])
    if set(selected) != set(PLATFORMS):
        raise ValueError('All three native platform installers required')
    output.mkdir(parents=True)
    with zipfile.ZipFile(output / f'shangzimu-{VERSION}-test-verification.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('release-provenance.json', json.dumps({
            'schema': 1, 'release_target_commit': commit, 'default_run_id': run_id,
            'platforms': expected, 'mixed_provenance_requested': platform_provenance is not None,
            'source_difference_allowlist': sorted(MIXED_SOURCE_DIFFERENCES),
            'verified_source_differences': source_differences,
            'limitations': 'Native job success must be checked independently against GitHub; this helper does not certify CI job results.'
        }, ensure_ascii=False, indent=2))
        for platform, (directory, installer) in selected.items():
            # GitHub strips non-ASCII asset characters; publish stable names
            # while retaining the original CI basename in provenance records.
            signing = 'unnotarized' if platform.startswith('mac-') else 'unsigned'
            published_installer = f'shangzimu-{VERSION}-{platform}-full-test-{signing}{PLATFORMS[platform]}'
            shutil.copyfile(directory / installer, output / published_installer)
            shutil.copyfile(directory / 'source-and-license-materials.zip',
                            output / f'shangzimu-{VERSION}-{platform}-sources.zip')
            for name in ('source-and-checksums.json', 'reviewed-materials-manifest.json',
                         'vocal-materials-manifest.json', 'components.json',
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
    parser.add_argument('--platform-provenance', type=Path,
                        help='JSON file mapping every platform to exact commit and run_id')
    parser.add_argument('--source-repository', type=Path)
    args = parser.parse_args()
    mapping = json.loads(args.platform_provenance.read_text(encoding='utf-8')) if args.platform_provenance else None
    print(json.dumps(prepare(args.downloads, args.output, args.commit, args.run_id,
                             mapping, args.source_repository), ensure_ascii=False))
