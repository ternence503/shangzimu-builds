"""Stage only explicitly approved CI installer/evidence files for private storage."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

UPSTREAM_SHA = 'cc226d71864a4e36c70deb6be572f1ad1ff7111b'
REPOSITORY = 'ternence503/shangzimu-builds'
PLATFORMS = {'mac-x86_64': '.pkg', 'mac-arm64': '.pkg', 'windows-x64': '.exe'}
EVIDENCE_KEYS = {
    'status', 'returncode', 'model_loaded', 'vad_silence_decoded', 'tk_gui_created',
    'speech_transcribed_and_srt_exported', 'python_socket_calls_blocked',
    'onnx_telemetry_disabled', 'os_network_denied', 'adhoc_signature_verified',
    'relocated', 'in_place_execution', 'network_denial_proven', 'network_isolation',
    'exit_code', 'restricted_path', 'isolated_appdata',
}
REPORT_ROLES = {'probe.json': 'relocated', 'windows-relocation.json': 'relocated',
                'frozen-self-test.json': 'frozen', 'installed-probe.json': 'installed'}

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

def stage(platform, installer, resources, lock, reports, output, environment=None):
    env = os.environ if environment is None else environment
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != REPOSITORY
            or env.get('SHANGZIMU_PRIVATE_REPOSITORY', '').lower() != 'true'):
        raise ValueError('Private approved CI repository required')
    private_sha = env.get('GITHUB_SHA', '')
    if not re.fullmatch('[0-9a-f]{40}', private_sha):
        raise ValueError('Exact private source commit required')
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
    # Bound seven-day artifact storage for the approved three-platform batch.
    if sum(p.stat().st_size for p in (installer, inventory, lock)) + 1024 * 1024 > 1024 ** 3:
        raise ValueError('Each private artifact must remain below 1 GiB')
    sanitized = []
    roles = set()
    for report in reports:
        report = Path(report)
        role = REPORT_ROLES.get(report.name)
        if not role or role in roles:
            raise ValueError('Known unique report roles required')
        roles.add(role)
        data = json.loads(report.read_text(encoding='utf-8-sig'))
        if data.get('status') != 'passed' or not data.get('speech_transcribed_and_srt_exported'):
            raise ValueError('Passed speech/SRT evidence required')
        summary = {'role': role}
        if platform.startswith('mac-'):
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
    required_roles = {'relocated', 'installed'} if platform.startswith('mac-') else {'frozen', 'relocated', 'installed'}
    if roles != required_roles:
        raise ValueError('Complete installed and relocated report set required')
    output.mkdir(parents=True, exist_ok=False)
    name = f'上字幕-1.4.1-{platform}-內部驗證未正式簽署{PLATFORMS[platform]}'
    shutil.copyfile(installer, output / name)
    shutil.copyfile(inventory, output / 'components.json')
    shutil.copyfile(lock, output / 'actual-build-dependency-lock.txt')
    (output / 'acceptance-evidence.json').write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2), encoding='utf-8')
    files = {p.name: {'sha256': sha256(p), 'size': p.stat().st_size} for p in output.iterdir()}
    manifest = {
        'schema': 1, 'status': 'internal-validation-only-not-for-redistribution',
        'platform': platform, 'private_repository': REPOSITORY, 'private_commit': private_sha,
        'verified_upstream_repository': 'ternence503/whisper-gui',
        'verified_upstream_commit': UPSTREAM_SHA, 'verified_upstream_run': 34793061049,
        'private_run_id': env.get('GITHUB_RUN_ID'), 'files': files,
        'limitations': ['Not Developer ID/notarized or Authenticode signed.',
                        'Not fresh end-user OS search/reboot acceptance.',
                        'Inventory versions match the actual freeze lock; native component/source clearance remains incomplete.'],
    }
    (output / 'source-and-checksums.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=PLATFORMS, required=True)
    for arg in ('installer', 'resources', 'lock', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    parser.add_argument('--report', type=Path, action='append', required=True)
    args = parser.parse_args()
    stage(args.platform, args.installer, args.resources, args.lock, args.report, args.output)
