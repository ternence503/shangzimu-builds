"""Stage reviewed, explicitly selected unsigned public-test installers and evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

UPSTREAM_SHA = 'cc226d71864a4e36c70deb6be572f1ad1ff7111b'
REPOSITORY = 'ternence503/shangzimu-builds'
VERSION = '1.5.0'
PLATFORMS = {'mac-x86_64': '.pkg', 'mac-arm64': '.pkg', 'windows-x64': '.exe'}
MATERIAL_SCOPES = {'main-runtime', 'vocal-worker', 'umx-hq'}
SOX_NATIVE_RE = re.compile(r'(^|[/\\])[^/\\]*sox[^/\\]*(?:\.dll|\.pyd|\.so|\.dylib)$', re.I)
EVIDENCE_KEYS = {
    'status', 'returncode', 'model_loaded', 'vad_silence_decoded', 'tk_gui_created',
    'speech_transcribed_and_srt_exported', 'python_socket_calls_blocked',
    'onnx_telemetry_disabled', 'os_network_denied', 'adhoc_signature_verified',
    'relocated', 'in_place_execution', 'network_denial_proven', 'network_isolation',
    'exit_code', 'restricted_path', 'isolated_appdata', 'all_tabs_enabled',
    'subtitle_project_roundtrip_and_srt', 'cloud_refusal_without_output',
    'headless_dialogs',
}
REPORT_ROLES = {'probe.json': 'relocated', 'windows-relocation.json': 'relocated',
                'frozen-self-test.json': 'frozen', 'installed-probe.json': 'installed',
                'full-acceptance.json': 'full'}

def compare_versions(inventory, lock_text):
    versions = {}
    for line in lock_text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9_.+!-]+)', line.strip())
        if not match:
            raise ValueError('Only registry package==version build locks are allowed')
        key = re.sub(r'[-_.]+', '-', match[1]).lower()
        if key in versions:
            raise ValueError('Duplicate dependency lock entry')
        versions[key] = match[2]
    expected = {re.sub(r'[-_.]+', '-', p['name']).lower(): p['version']
                for p in inventory['python_packages'] if p['name'].lower() != 'pip'}
    if not versions or versions != expected:
        raise ValueError('Actual freeze environment versions do not match inventory')

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def reviewed_materials(resources, inventory):
    """Verify reviewed source/notices payload; inventory alone never authorizes staging."""
    path = resources / 'reviewed-materials-manifest.json'
    if not path.is_file() or path.is_symlink():
        raise ValueError('Reviewed public-test materials manifest required')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data.get('schema') != 1 or data.get('status') != 'reviewed-for-public-test'
            or data.get('inventory_sha256') != sha256(inventory)):
        raise ValueError('Reviewed materials must match this native build inventory')
    entries = data.get('files', [])
    names = set()
    for entry in entries:
        relative = entry.get('path', '')
        part = Path(relative)
        if (not relative or part.is_absolute() or '\\' in relative or ':' in relative
                or '..' in part.parts or relative in names):
            raise ValueError('Unique safe relative material paths required')
        file = resources / part
        if (not file.is_file() or any((resources / Path(*part.parts[:i])).is_symlink()
                                     for i in range(1, len(part.parts) + 1))
                or sha256(file) != entry.get('sha256')):
            raise ValueError('Reviewed material missing, linked or hash mismatched')
        names.add(relative)
    if 'THIRD-PARTY-NOTICES.txt' not in names or not any(n.startswith('licenses/') for n in names):
        raise ValueError('Reviewed notices and original license/source materials required')
    return path


def reviewed_vocal_materials(directory, main_material_names):
    """Require a complete hash-bound review of the final frozen worker.

    The collector may approve only its fixed version/hash/native allowlist;
    changing the status alone is insufficient because every native record is
    independently validated again here.
    """
    directory = Path(directory)
    manifest = directory / 'vocal-materials-manifest.json'
    if (directory.is_symlink() or not directory.is_dir() or manifest.is_symlink()
            or not manifest.is_file()):
        raise ValueError('Reviewed VocalWorker material directory required')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if (data.get('schema') != 1 or data.get('status') != 'reviewed-for-public-test'
            or data.get('scope') != 'final-frozen-vocal-worker'):
        raise ValueError('Final VocalWorker review has not been approved')
    model = data.get('model', {})
    if (model.get('checkpoint') != 'vocals-b62c91ce.pth'
            or model.get('checkpoint_sha256') != 'b62c91cedbc7a066f1778ead5b5cecb377aa3a46a31af1cce7c5c8769339d083'
            or model.get('license_id') != 'mit-license'):
        raise ValueError('Exact reviewed UMX-HQ model provenance required')
    materials, material_names = data.get('materials', []), set()
    for entry in materials:
        relative = entry.get('path', '')
        part = Path(relative)
        if (not relative or part.is_absolute() or '\\' in relative or ':' in relative
                or '..' in part.parts or relative in material_names):
            raise ValueError('Unique safe VocalWorker material paths required')
        path = directory / part
        if (not path.is_file() or path.is_symlink() or sha256(path) != entry.get('sha256')):
            raise ValueError('Reviewed VocalWorker material missing or hash mismatched')
        material_names.add(relative)
    if ('licenses/UMX-HQ-MIT-LICENSE.txt' not in material_names
            or not any(name.startswith('licenses/python-packages/torch-') for name in material_names)
            or not any(name.startswith('licenses/python-packages/torchaudio-') for name in material_names)
            or not any(name.startswith('licenses/python-packages/numpy-') for name in material_names)):
        raise ValueError('Required model, Torch, TorchAudio and NumPy notices missing')
    natives = data.get('native_files', [])
    if not natives or not re.fullmatch(r'[a-f0-9]{64}', str(data.get('worker_native_sha256', ''))):
        raise ValueError('Complete final VocalWorker native inventory required')
    paths = set()
    for entry in natives:
        relative = entry.get('path', '')
        if (not relative or relative in paths or SOX_NATIVE_RE.search(relative)
                or not re.fullmatch(r'[a-f0-9]{64}', str(entry.get('sha256', '')))
                or entry.get('status') != 'reviewed-for-public-test'
                or not entry.get('owner') or not str(entry.get('source_url', '')).startswith('https://')
                or not entry.get('license_paths')):
            raise ValueError('Every native file needs a reviewed owner/source/license mapping; native SoX is forbidden')
        local_licenses = {name for name in entry['license_paths'] if not name.startswith('main-runtime:')}
        main_licenses = {name.removeprefix('main-runtime:') for name in entry['license_paths']
                         if name.startswith('main-runtime:')}
        if not local_licenses <= material_names or not main_licenses <= main_material_names:
            raise ValueError('Native license mapping refers to missing material')
        paths.add(relative)
    canonical = json.dumps(
        [{'path': item['path'], 'sha256': item['sha256']} for item in natives],
        ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')
    if hashlib.sha256(canonical).hexdigest() != data['worker_native_sha256']:
        raise ValueError('Final VocalWorker native inventory digest mismatch')
    return manifest, data

def stage(platform, installer, resources, lock, reports, output, vocal_materials, environment=None):
    env = os.environ if environment is None else environment
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != REPOSITORY
            or env.get('SHANGZIMU_PRIVATE_REPOSITORY', '').lower() != 'false'
            or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise ValueError('Exact approved public manual CI repository required')
    private_sha = env.get('GITHUB_SHA', '')
    if not re.fullmatch('[0-9a-f]{40}', private_sha):
        raise ValueError('Exact public source commit required')
    if platform not in PLATFORMS:
        raise ValueError('Unsupported platform')
    installer, resources, lock, output = map(Path, (installer, resources, lock, output))
    if not installer.is_file() or installer.suffix.lower() != PLATFORMS[platform]:
        raise ValueError('Exact platform installer required')
    inventory = resources / 'components.json'
    if not inventory.is_file() or not lock.is_file() or not reports:
        raise ValueError('Inventory, actual build lock and reports required')
    compare_versions(json.loads(inventory.read_text(encoding='utf-8-sig')),
                     lock.read_text(encoding='utf-8-sig'))
    materials = reviewed_materials(resources, inventory)
    material_files = json.loads(materials.read_text(encoding='utf-8'))['files']
    main_material_names = {entry['path'] for entry in material_files}
    vocal_manifest, vocal_review = reviewed_vocal_materials(vocal_materials, main_material_names)
    vocal_root = Path(vocal_materials)
    vocal_files = vocal_review['materials']
    # Bound both installer and downloadable corresponding-source material payload.
    if (sum(p.stat().st_size for p in (installer, inventory, lock, materials, vocal_manifest))
            + sum((resources / e['path']).stat().st_size for e in material_files)
            + sum((vocal_root / e['path']).stat().st_size for e in vocal_files)
            + 1024 * 1024 > 1024 ** 3):
        raise ValueError('Each public test artifact must remain below 1 GiB')
    sanitized = []
    roles = set()
    for report in reports:
        report = Path(report)
        role = REPORT_ROLES.get(report.name)
        if not role or role in roles:
            raise ValueError('Known unique report roles required')
        roles.add(role)
        data = json.loads(report.read_text(encoding='utf-8-sig'))
        if data.get('status') != 'passed':
            raise ValueError('Passed acceptance evidence required')
        if role == 'full':
            lyric_outputs = data.get('lyrics_outputs')
            if (data.get('all_tabs_enabled') is not True
                    or not isinstance(lyric_outputs, dict)
                    or set(lyric_outputs) != {'.txt', '.lrc', '.srt'}
                    or not all(isinstance(size, int) and size > 0 for size in lyric_outputs.values())
                    or data.get('subtitle_project_roundtrip_and_srt') is not True
                    or data.get('cloud_refusal_without_output') is not True
                    or data.get('headless_dialogs') != 0):
                raise ValueError('Complete four-page, lyrics, subtitle-project and cloud-refusal evidence required')
            summary = {'role': role, 'lyrics_txt_lrc_srt': True}
        elif not data.get('speech_transcribed_and_srt_exported'):
            raise ValueError('Passed speech/SRT evidence required')
        else:
            summary = {'role': role}
        if platform.startswith('mac-') and role != 'full':
            if data.get('returncode') != 0 or data.get('os_network_denied') is not True or data.get('adhoc_signature_verified') is not True:
                raise ValueError('Mac signature and OS-offline exit evidence required')
            if role == 'installed' and data.get('in_place_execution') is not True:
                raise ValueError('Actual installed Mac execution evidence required')
        elif role == 'relocated':
            baseline, blocked = data.get('network_baseline', {}), data.get('network_with_block', {})
            if (data.get('network_denial_proven') is not True or data.get('exit_code') != 0
                    or data.get('restricted_path') is not True or data.get('isolated_appdata') is not True
                    or baseline.get('connected') is not True or blocked.get('connected') is not False
                    or baseline.get('python_socket_patch_applied') is not False
                    or blocked.get('python_socket_patch_applied') is not False):
                raise ValueError('Real unpatched Windows firewall and isolation evidence required')
            summary.update(baseline_connected=True, blocked_connected=False, python_socket_patch_applied=False)
        # No user paths, stderr, arbitrary strings, synthetic audio or transcripts.
        summary.update({k: v for k, v in data.items() if k in EVIDENCE_KEYS
                        and (isinstance(v, (bool, int)) or k == 'status')})
        sanitized.append(summary)
    required_roles = ({'relocated', 'installed', 'full'} if platform.startswith('mac-')
                      else {'frozen', 'relocated', 'installed', 'full'})
    if roles != required_roles:
        raise ValueError('Complete installed and relocated report set required')
    output.mkdir(parents=True, exist_ok=False)
    name = f'上字幕-{VERSION}-{platform}-公開測試未正式簽署{PLATFORMS[platform]}'
    shutil.copyfile(installer, output / name)
    shutil.copyfile(inventory, output / 'components.json')
    shutil.copyfile(lock, output / 'actual-build-dependency-lock.txt')
    shutil.copyfile(materials, output / 'reviewed-materials-manifest.json')
    shutil.copyfile(vocal_manifest, output / 'vocal-materials-manifest.json')
    with zipfile.ZipFile(output / 'source-and-license-materials.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(materials, 'reviewed-materials-manifest.json')
        for entry in material_files:
            archive.write(resources / entry['path'], entry['path'])
        archive.write(vocal_manifest, 'vocal-worker/vocal-materials-manifest.json')
        for entry in vocal_files:
            archive.write(vocal_root / entry['path'], 'vocal-worker/' + entry['path'])
    (output / 'acceptance-evidence.json').write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2), encoding='utf-8')
    files = {p.name: {'sha256': sha256(p), 'size': p.stat().st_size} for p in output.iterdir()}
    manifest = {
        'schema': 1, 'status': 'unsigned-public-test-not-final',
        'platform': platform, 'version': VERSION, 'repository': REPOSITORY, 'commit': private_sha,
        'material_scopes': sorted(MATERIAL_SCOPES),
        'verified_upstream_repository': 'ternence503/whisper-gui',
        'verified_upstream_commit': UPSTREAM_SHA, 'verified_upstream_run': 34793061049,
        'run_id': env.get('GITHUB_RUN_ID'), 'files': files,
        'limitations': ['Not Developer ID/notarized or Authenticode signed.',
                        'Not fresh end-user OS search/reboot acceptance.',
                        'Inventory versions match the actual freeze lock; reviewed materials are hashed, not a blanket legal certification.'],
    }
    (output / 'source-and-checksums.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=PLATFORMS, required=True)
    for arg in ('installer', 'resources', 'lock', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    parser.add_argument('--vocal-materials', type=Path, required=True)
    parser.add_argument('--report', type=Path, action='append', required=True)
    args = parser.parse_args()
    stage(args.platform, args.installer, args.resources, args.lock, args.report,
          args.output, args.vocal_materials)
