"""Synthetic artifact fixtures only: no real executable or installer is used."""
import importlib.util
import json
from pathlib import Path
import tempfile
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
            installer = f'上字幕-1.4.1-{platform}-公開測試未正式簽署{suffix}'
            (directory / installer).write_bytes(('SYNTHETIC NONEXECUTABLE INSTALLER FIXTURE ' + platform).encode())
            (directory / 'components.json').write_text('{"fixture": true}')
            (directory / 'acceptance-evidence.json').write_text('[]')
            (directory / 'actual-build-dependency-lock.txt').write_text('synthetic==1.0\n')
            (directory / 'reviewed-materials-manifest.json').write_text(json.dumps({
                'schema': 1, 'status': 'reviewed-for-public-test',
                'inventory_sha256': release.sha256(directory / 'components.json'), 'files': []}))
            with zipfile.ZipFile(directory / 'source-and-license-materials.zip', 'w') as archive:
                archive.writestr('LICENSE.fixture', 'Synthetic fixture, not a distribution license')
            manifest = {'schema': 1, 'status': 'unsigned-public-test-not-final',
                'repository': release.REPOSITORY, 'commit': self.commit, 'run_id': self.run_id,
                'platform': platform, 'files': {p.name: {'sha256': release.sha256(p), 'size': p.stat().st_size}
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
        for line in (self.output / 'SHA256SUMS.txt').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(release.sha256(self.output / name), digest)
        with zipfile.ZipFile(self.output / 'shangzimu-1.4.1-test-verification.zip') as archive:
            self.assertEqual(len(archive.namelist()), 15)

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
