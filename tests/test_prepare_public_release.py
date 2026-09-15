"""Synthetic artifact fixtures only: no real executable or installer is used."""
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('prepare_public_release', Path(__file__).resolve().parents[1] / 'packaging/prepare_public_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PreparePublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloads = self.root / 'downloads'
        self.downloads.mkdir()
        self.output = self.root / 'release'
        self.commit = 'a' * 40
        self.run_id = '123456'
        for platform, suffix in release.PLATFORMS.items():
            directory = self.downloads / platform
            directory.mkdir()
            installer = f'上字幕-{release.VERSION}-{platform}-公開測試未正式簽署{suffix}'
            (directory / installer).write_bytes(('SYNTHETIC NONEXECUTABLE INSTALLER FIXTURE ' + platform).encode())
            (directory / 'components.json').write_text('{"fixture": true}')
            (directory / 'acceptance-evidence.json').write_text('[]')
            (directory / 'actual-build-dependency-lock.txt').write_text('synthetic==1.0\n')
            (directory / 'reviewed-materials-manifest.json').write_text(json.dumps({
                'schema': 1, 'status': 'reviewed-for-public-test',
                'inventory_sha256': release.sha256(directory / 'components.json'), 'files': []}))
            vocal_license = b'Synthetic reviewed VocalWorker license fixture'
            vocal_manifest = {
                'schema': 1, 'status': 'reviewed-for-public-test',
                'scope': 'final-frozen-vocal-worker',
                'native_files': [{'path': 'VocalWorker', 'sha256': '1' * 64,
                                  'status': 'reviewed-for-public-test',
                                  'owner': 'PyInstaller-bootloader',
                                  'source_url': 'https://github.com/pyinstaller/pyinstaller/tree/v6.22.0',
                                  'license_paths': ['licenses/LICENSE']}],
                'materials': [{'path': 'licenses/LICENSE',
                               'sha256': __import__('hashlib').sha256(vocal_license).hexdigest()}],
            }
            (directory / 'vocal-materials-manifest.json').write_text(json.dumps(vocal_manifest))
            with zipfile.ZipFile(directory / 'source-and-license-materials.zip', 'w') as archive:
                archive.writestr('LICENSE.fixture', 'Synthetic fixture, not a distribution license')
                archive.writestr('vocal-worker/vocal-materials-manifest.json',
                                 (directory / 'vocal-materials-manifest.json').read_bytes())
                archive.writestr('vocal-worker/licenses/LICENSE', vocal_license)
            manifest = {'schema': 1, 'status': 'unsigned-public-test-not-final',
                'repository': release.REPOSITORY, 'commit': self.commit, 'run_id': self.run_id,
                'platform': platform, 'material_scopes': sorted(release.MATERIAL_SCOPES),
                'files': {p.name: {'sha256': release.sha256(p), 'size': p.stat().st_size}
                    for p in directory.iterdir()}}
            self.write_manifest(platform, manifest)

    def read_manifest(self, platform='mac-x86_64'):
        return json.loads((self.downloads / platform / 'source-and-checksums.json').read_text())

    def write_manifest(self, platform, data):
        (self.downloads / platform / 'source-and-checksums.json').write_text(json.dumps(data))

    def prepare(self):
        return release.prepare(self.downloads, self.output, self.commit, self.run_id)

    def test_three_platform_assets_and_checksums(self):
        names = self.prepare()
        self.assertEqual(len(names), 8)
        self.assertEqual(sum(n.endswith('.pkg') for n in names), 2)
        self.assertEqual(sum(n.endswith('.exe') for n in names), 1)
        self.assertTrue(all(n.isascii() for n in names))
        self.assertIn('shangzimu-1.5.0-mac-arm64-full-test-unnotarized.pkg', names)
        self.assertIn('shangzimu-1.5.0-mac-x86_64-full-test-unnotarized.pkg', names)
        self.assertIn('shangzimu-1.5.0-windows-x64-full-test-unsigned.exe', names)
        for line in (self.output / 'SHA256SUMS.txt').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(release.sha256(self.output / name), digest)
        with zipfile.ZipFile(self.output / 'shangzimu-1.5.0-test-verification.zip') as archive:
            self.assertEqual(len(archive.namelist()), 19)

    def mixed_fixture(self):
        self.repo = self.root / 'source'
        self.repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()
        self.git = git
        git('init', '-q')
        git('config', 'user.name', 'Synthetic QA')
        git('config', 'user.email', 'qa@example.invalid')
        workflow = self.repo / '.github/workflows/bundle-validation.yml'
        workflow.parent.mkdir(parents=True)
        workflow.write_text(release.OLD_CONCURRENCY + '\n' + release.OLD_MSVC + '\n')
        git('add', '.')
        git('commit', '-qm', 'Synthetic old source')
        old = git('rev-parse', 'HEAD')
        workflow.write_text(release.NEW_CONCURRENCY + '\n' + release.NEW_MSVC + '\n')
        batch = self.repo / 'packaging/windows/msvc_environment.cmd'
        batch.parent.mkdir(parents=True)
        batch.write_text(release.SAFE_MSVC_BATCH)
        git('add', '.')
        git('commit', '-qm', 'Synthetic reviewed quoting fix')
        self.commit = git('rev-parse', 'HEAD')
        mapping = {p: {'commit': self.commit if p == 'windows-x64' else old,
                       'run_id': self.run_id if p == 'windows-x64' else '123455'} for p in release.PLATFORMS}
        for platform, expected in mapping.items():
            manifest = self.read_manifest(platform)
            manifest.update(expected)
            self.write_manifest(platform, manifest)
        return mapping

    def test_mixed_known_fix_and_provenance_archive(self):
        mapping = self.mixed_fixture()
        names = release.prepare(self.downloads, self.output, self.commit, self.run_id, mapping, self.repo)
        self.assertEqual(len(names), 8)
        with zipfile.ZipFile(self.output / 'shangzimu-1.5.0-test-verification.zip') as archive:
            provenance = json.loads(archive.read('release-provenance.json'))
            self.assertEqual(provenance['platforms'], mapping)
            self.assertEqual(provenance['release_target_commit'], self.commit)
            self.assertIn('.github/workflows/bundle-validation.yml', provenance['verified_source_differences']['mac-arm64'])

    def test_mixed_mapping_requires_complete_exact_fields_and_repository(self):
        mapping = self.mixed_fixture()
        cases = [{}, dict(mapping, unknown=mapping['windows-x64']),
                 dict(mapping, **{'mac-arm64': {'commit': 'main', 'run_id':'123455'}}),
                 dict(mapping, **{'mac-arm64': {'commit': mapping['mac-arm64']['commit'], 'run_id':'wrong'}})]
        for invalid in cases:
            with self.assertRaises(ValueError):
                release.prepare(self.downloads, self.output, self.commit, self.run_id, invalid, self.repo)
        with self.assertRaises(ValueError):
            release.prepare(self.downloads, self.output, self.commit, self.run_id, mapping)
        wrong_run = {p: dict(v) for p, v in mapping.items()}
        wrong_run['mac-arm64']['run_id'] = '999'
        with self.assertRaises(ValueError):
            release.prepare(self.downloads, self.output, self.commit, self.run_id, wrong_run, self.repo)

    def test_mixed_product_or_recipe_changes_rejected(self):
        mapping = self.mixed_fixture()
        for name in ['gui.py', 'packaging/entry.py', 'packaging/build_minimal_ffmpeg.py']:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Synthetic changed source')
            self.git('add', '.')
            self.git('commit', '-qm', 'Synthetic forbidden product change')
            target = self.git('rev-parse', 'HEAD')
            with self.assertRaises(ValueError):
                release.prepare(self.downloads, self.output, target, self.run_id, mapping, self.repo)
        self.assertFalse(self.output.exists())

    def test_mixed_arbitrary_workflow_or_unsafe_batch_rejected(self):
        mapping = self.mixed_fixture()
        workflow = self.repo / '.github/workflows/bundle-validation.yml'
        workflow.write_text(workflow.read_text() + 'arbitrary-new-build-step\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic forbidden workflow change')
        with self.assertRaises(ValueError):
            release.prepare(self.downloads, self.output, self.git('rev-parse', 'HEAD'), self.run_id, mapping, self.repo)
        workflow.write_text(release.NEW_CONCURRENCY + '\n' + release.NEW_MSVC + '\n')
        batch = self.repo / 'packaging/windows/msvc_environment.cmd'
        batch.write_text('set\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic forbidden environment dump')
        with self.assertRaises(ValueError):
            release.prepare(self.downloads, self.output, self.git('rev-parse', 'HEAD'), self.run_id, mapping, self.repo)

    def test_tampered_file_rejected_before_output(self):
        (self.downloads / 'mac-x86_64' / 'components.json').write_text('tampered')
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.output.exists())

    def test_wrong_commit_run_repository_or_status_rejected(self):
        original = self.read_manifest()
        for field, value in [('commit', 'b' * 40), ('run_id', '999'),
                             ('repository', 'other/repository'), ('status', 'final')]:
            manifest = dict(original, **{field: value})
            self.write_manifest('mac-x86_64', manifest)
            with self.assertRaises(ValueError): self.prepare()
            self.assertFalse(self.output.exists())

    def test_missing_platform_rejected(self):
        (self.downloads / 'mac-arm64' / 'source-and-checksums.json').unlink()
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.output.exists())

    def test_missing_vocal_scope_or_payload_rejected(self):
        manifest = self.read_manifest()
        manifest['material_scopes'] = ['main-runtime']
        self.write_manifest('mac-x86_64', manifest)
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.output.exists())

    def test_unsafe_artifact_names_rejected(self):
        original = self.read_manifest()
        information = next(iter(original['files'].values()))
        for name in ['../escape.pkg', '/escape.pkg', 'C:escape.pkg', 'folder\\escape.pkg']:
            manifest = dict(original, files=dict(original['files'], **{name: information}))
            self.write_manifest('mac-x86_64', manifest)
            with self.assertRaises(ValueError): self.prepare()
            self.assertFalse(self.output.exists())

    def test_installer_collision_rejected_before_any_copy(self):
        x86 = self.read_manifest('mac-x86_64')
        shared_name = next(n for n in x86['files'] if n.endswith('.pkg'))
        arm = self.read_manifest('mac-arm64')
        old_name = next(n for n in arm['files'] if n.endswith('.pkg'))
        directory = self.downloads / 'mac-arm64'
        (directory / old_name).rename(directory / shared_name)
        arm['files'][shared_name] = arm['files'].pop(old_name)
        self.write_manifest('mac-arm64', arm)
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
