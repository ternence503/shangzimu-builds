import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('private_delivery', Path(__file__).resolve().parents[1] / 'packaging/private_delivery.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)

class PrivateDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resources = self.root / 'resources'
        self.resources.mkdir()
        (self.resources / 'components.json').write_text(json.dumps({'python_packages': [{'name': 'faster-whisper', 'version': '1.2.1'}, {'name': 'pip', 'version': '24.0'}]}))
        self.lock = self.root / 'lock.txt'
        self.lock.write_text('faster_whisper==1.2.1\n')
        self.installer = self.root / 'internal.pkg'
        self.installer.write_bytes(b'synthetic installer fixture, not an executable')
        self.output = self.root / 'delivery'
        self.env = {'GITHUB_ACTIONS':'true', 'GITHUB_REPOSITORY':delivery.REPOSITORY,
                    'SHANGZIMU_PRIVATE_REPOSITORY':'false', 'GITHUB_EVENT_NAME':'workflow_dispatch', 'GITHUB_SHA':'a' * 40, 'GITHUB_RUN_ID':'123'}
        (self.resources / 'licenses').mkdir()
        (self.resources / 'licenses/LICENSE').write_text('Synthetic license test fixture')
        (self.resources / 'THIRD-PARTY-NOTICES.txt').write_text('Synthetic reviewed notices test fixture')
        self.materials = self.resources / 'reviewed-materials-manifest.json'
        self.materials.write_text(json.dumps({'schema':1, 'status':'reviewed-for-public-test',
            'inventory_sha256':delivery.sha256(self.resources / 'components.json'),
            'files':[{'path':n, 'sha256':delivery.sha256(self.resources / n)} for n in
                     ['THIRD-PARTY-NOTICES.txt', 'licenses/LICENSE']]}))
        self.vocal_materials = self.root / 'vocal-materials'
        for relative, text in {
            'licenses/UMX-HQ-MIT-LICENSE.txt': 'Synthetic UMX-HQ MIT license',
            'licenses/python-packages/torch-2.2.2/LICENSE': 'Synthetic Torch license',
            'licenses/python-packages/torchaudio-2.2.2/LICENSE': 'Synthetic TorchAudio license',
            'licenses/python-packages/numpy-1.26.4/LICENSE.txt': 'Synthetic NumPy license',
        }.items():
            path = self.vocal_materials / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        material_files = [path for path in sorted(self.vocal_materials.rglob('*')) if path.is_file()]
        native_files = [{
            'path': 'VocalWorker', 'sha256': '1' * 64,
            'status': 'reviewed-for-public-test', 'owner': 'PyInstaller-bootloader',
            'source_url': 'https://github.com/pyinstaller/pyinstaller/tree/v6.22.0',
            'license_paths': ['licenses/python-packages/torch-2.2.2/LICENSE'],
        }]
        canonical = json.dumps(
            [{'path': item['path'], 'sha256': item['sha256']} for item in native_files],
            ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        ).encode('utf-8')
        (self.vocal_materials / 'vocal-materials-manifest.json').write_text(json.dumps({
            'schema': 1, 'status': 'reviewed-for-public-test',
            'scope': 'final-frozen-vocal-worker',
            'worker_native_sha256': __import__('hashlib').sha256(canonical).hexdigest(),
            'model': {'checkpoint': 'vocals-b62c91ce.pth',
                      'checkpoint_sha256': 'b62c91cedbc7a066f1778ead5b5cecb377aa3a46a31af1cce7c5c8769339d083',
                      'license_id': 'mit-license'},
            'native_files': native_files,
            'materials': [{'path': path.relative_to(self.vocal_materials).as_posix(),
                           'sha256': delivery.sha256(path)} for path in material_files],
        }))
        self.reports = [self.root / name for name in ('probe.json', 'installed-probe.json')]
        for report in self.reports:
            self.write_report(report, {'status':'passed', 'returncode':0,
                'speech_transcribed_and_srt_exported':True, 'os_network_denied':True,
                'adhoc_signature_verified':True, 'in_place_execution':report.name == 'installed-probe.json',
                'resources':'/private/user/path', 'stderr':'secret raw text', 'synthetic_speech_text':'not retained'})
        full = self.root / 'full-acceptance.json'
        self.write_report(full, {'status': 'passed', 'all_tabs_enabled': True,
            'lyrics_outputs': {'.txt': 10, '.lrc': 11, '.srt': 12},
            'subtitle_project_roundtrip_and_srt': True,
            'cloud_refusal_without_output': True, 'headless_dialogs': 0,
            'models': {'small': 'private transcript'}, 'resources': '/private/user/path'})
        self.reports.append(full)

    def write_report(self, path, data):
        path.write_text(json.dumps(data), encoding='utf-8')

    def stage(self, platform='mac-x86_64'):
        return delivery.stage(platform, self.installer, self.resources, self.lock,
                              self.reports, self.output, self.vocal_materials, self.env)

    def test_exact_installer_hash_and_sanitized_roles(self):
        manifest = self.stage()
        installer_name = next(name for name in manifest['files'] if name.endswith('.pkg'))
        self.assertEqual(manifest['files'][installer_name]['sha256'], delivery.sha256(self.installer))
        saved = (self.output / 'acceptance-evidence.json').read_text()
        self.assertNotIn('/private/user', saved)
        self.assertNotIn('secret raw text', saved)
        self.assertNotIn('not retained', saved)
        self.assertEqual({r['role'] for r in json.loads(saved)}, {'relocated', 'installed', 'full'})
        full = next(r for r in json.loads(saved) if r['role'] == 'full')
        self.assertTrue(full['lyrics_txt_lrc_srt'])
        self.assertNotIn('private transcript', saved)
        self.assertEqual(set(p.name for p in self.output.iterdir()),
                         {installer_name, 'components.json', 'actual-build-dependency-lock.txt',
                          'acceptance-evidence.json', 'source-and-checksums.json',
                          'reviewed-materials-manifest.json', 'vocal-materials-manifest.json',
                          'source-and-license-materials.zip'})
        with __import__('zipfile').ZipFile(self.output / 'source-and-license-materials.zip') as archive:
            self.assertIn('vocal-worker/vocal-materials-manifest.json', archive.namelist())
            self.assertIn('vocal-worker/licenses/UMX-HQ-MIT-LICENSE.txt', archive.namelist())

    def test_unreviewed_or_changed_materials_prevent_installer_upload(self):
        original = self.materials.read_text()
        data = json.loads(original)
        data['status'] = 'pending'
        self.materials.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.stage()
        self.materials.write_text(original)
        (self.resources / 'licenses/LICENSE').write_text('changed')
        with self.assertRaises(ValueError): self.stage()
        self.assertFalse(self.output.exists())

    def test_unreviewed_or_incomplete_vocal_materials_prevent_installer_upload(self):
        manifest = self.vocal_materials / 'vocal-materials-manifest.json'
        original = manifest.read_text()
        data = json.loads(original)
        data['status'] = 'collected-not-reviewed/not-redistribution-cleared'
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.stage()
        manifest.write_text(original)
        data = json.loads(original)
        data['native_files'][0].pop('source_url')
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.stage()
        manifest.write_text(original)
        data = json.loads(original)
        data['native_files'][0]['path'] = '_internal/libsox.dll'
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.stage()
        self.assertFalse(self.output.exists())

    def test_unsafe_and_missing_original_materials_rejected(self):
        data = json.loads(self.materials.read_text())
        for relative in ['../LICENSE', '/etc/passwd', 'licenses\\LICENSE', 'C:LICENSE']:
            data['files'][1]['path'] = relative
            self.materials.write_text(json.dumps(data))
            with self.assertRaises(ValueError): self.stage()
        self.assertFalse(self.output.exists())

    def test_public_workflow_does_not_skip_jobs_or_upload_unreviewed_installers(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/bundle-validation.yml').read_text()
        self.assertEqual(workflow.count('github.event.repository.private == false'), 2)
        self.assertNotIn('github.event.repository.private == true', workflow)
        self.assertEqual(workflow.count('if: always()'), 2)
        self.assertEqual(workflow.count('name: materials-review-'), 2)
        self.assertEqual(workflow.count('name: public-test-'), 2)
        self.assertIn('Require actual speech recognition evidence', workflow)
        self.assertIn('EnableFirewallProfilesForDisposableCI', workflow)
        self.assertEqual(workflow.count('--vocal-materials'), 2)
        self.assertEqual(workflow.count('--report "$RUNNER_TEMP/full-acceptance.json"'), 1)
        self.assertEqual(workflow.count('--report "$env:RUNNER_TEMP\\full-acceptance.json"'), 1)

    def test_private_repo_and_commit_guards(self):
        for key, wrong in [('GITHUB_REPOSITORY','ternence503/whisper-gui'), ('SHANGZIMU_PRIVATE_REPOSITORY','true'), ('GITHUB_EVENT_NAME','push'), ('GITHUB_SHA','main')]:
            original = self.env[key]
            self.env[key] = wrong
            with self.assertRaises(ValueError): self.stage()
            self.env[key] = original
        self.assertFalse(self.output.exists())

    def test_missing_installed_and_failed_offline_are_rejected(self):
        original = self.reports
        self.reports = original[:1]
        with self.assertRaises(ValueError): self.stage()
        self.reports = original
        data = json.loads(original[0].read_text())
        data['os_network_denied'] = False
        self.write_report(original[0], data)
        with self.assertRaises(ValueError): self.stage()

    def test_version_mismatch_or_url_lock_rejected(self):
        for text in ['faster-whisper==1.2.0\n', 'faster-whisper @ https://example.com/token\n']:
            self.lock.write_text(text)
            with self.assertRaises(ValueError): self.stage()

    def test_existing_output_and_wrong_installer_rejected(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError): self.stage()
        with self.assertRaises(ValueError): self.stage('windows-x64')

    def test_windows_native_firewall_controls_and_roles(self):
        self.installer = self.root / 'internal.exe'
        self.installer.write_bytes(b'synthetic Windows installer fixture')
        full = self.reports[-1]
        self.reports = [self.root / name for name in ('frozen-self-test.json', 'windows-relocation.json', 'installed-probe.json')]
        simple = {'status':'passed', 'speech_transcribed_and_srt_exported':True}
        for report in self.reports: self.write_report(report, simple)
        relocated = dict(simple, network_denial_proven=True, exit_code=0, restricted_path=True, isolated_appdata=True,
            network_baseline={'connected':True, 'python_socket_patch_applied':False, 'endpoint':'not retained'},
            network_with_block={'connected':False, 'python_socket_patch_applied':False})
        self.write_report(self.reports[1], relocated)
        self.reports.append(full)
        relocated['network_denial_proven'] = False
        self.write_report(self.reports[1], relocated)
        with self.assertRaises(ValueError): self.stage('windows-x64')
        relocated['network_denial_proven'] = True
        self.write_report(self.reports[1], relocated)
        self.stage('windows-x64')
        saved = json.loads((self.output / 'acceptance-evidence.json').read_text())
        result = next(r for r in saved if r['role'] == 'relocated')
        self.assertTrue(result['baseline_connected'])
        self.assertFalse(result['blocked_connected'])
        self.assertFalse(result['python_socket_patch_applied'])
        self.assertEqual(result['exit_code'], 0)
        self.assertNotIn('endpoint', json.dumps(saved))

if __name__ == '__main__':
    unittest.main()
