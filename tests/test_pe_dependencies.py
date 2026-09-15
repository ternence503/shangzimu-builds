import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('pe_audit', Path(__file__).resolve().parents[1] / 'packaging/windows/check_dependencies.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class PEAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'bundle'
        self.root.mkdir()
        self.images = {}
        self.image('app.exe', ['KERNEL32.dll'])

    def image(self, name, imports=(), machine=0x8664):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        self.images[path] = {'machine':machine, 'imports':list(imports)}

    def test_os_core_passes_but_vc_redist_requires_bundle(self):
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'passed')
        self.images[self.root / 'app.exe']['imports'].append('VCRUNTIME140.dll')
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')
        self.image('_internal/vcruntime140.dll', ['api-ms-win-crt-runtime-l1-1-0.dll'])
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'passed')

    def test_unrelated_directory_is_not_global_fallback(self):
        self.images[self.root / 'app.exe']['imports'].append('custom.dll')
        self.image('_internal/av.libs/custom.dll')
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')
        self.assertEqual(audit.audit_graph(self.root, self.images, ['_internal/av.libs'])['status'], 'passed')

    def test_documented_win32_components_are_not_vc_runtime(self):
        for name in ('AVICAP32.dll', 'imagehlp.dll', 'pdh.dll', 'COMCTL32.dll'):
            self.assertTrue(audit.system_import(name))
        for name in ('MSVCP140.dll', 'VCOMP140.dll', 'CONCRT140.dll'):
            self.assertFalse(audit.system_import(name))

    def test_ambiguous_candidate_and_wrong_architecture_fail(self):
        self.images[self.root / 'app.exe']['imports'].append('custom.dll')
        self.image('custom.dll'); self.image('_internal/custom.dll')
        (self.root / 'custom.dll').write_bytes(b'first')
        (self.root / '_internal/custom.dll').write_bytes(b'second')
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')
        self.images[self.root / 'app.exe']['imports'] = []
        self.images[self.root / 'custom.dll']['machine'] = 0x14c
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')

    def test_byte_identical_duplicate_candidate_is_recorded_and_allowed(self):
        self.images[self.root / 'app.exe']['imports'].append('custom.dll')
        self.image('custom.dll'); self.image('_internal/custom.dll')
        (self.root / 'custom.dll').write_bytes(b'identical audited binary')
        (self.root / '_internal/custom.dll').write_bytes(b'identical audited binary')

        report = audit.audit_graph(self.root, self.images)

        self.assertEqual(report['status'], 'passed')
        resolution = next(item for item in report['resolutions']
                          if item['dependency'] == 'custom.dll')
        self.assertEqual(len(resolution['equivalent_candidates']), 2)
        self.assertEqual(len(resolution['sha256']), 64)

    def test_invalid_directory_and_import_rejected(self):
        for path in ('../escape', '/absolute', 'missing'):
            with self.assertRaises(ValueError):
                audit.audit_graph(self.root, self.images, [path])
        self.images[self.root / 'app.exe']['imports'].append('../private.dll')
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')

    def test_nested_pyinstaller_runtime_is_isolated(self):
        self.image('_internal/python312.dll')
        self.image('_internal/vcruntime140.dll')
        worker_root = '_internal/resources/workers/vocals'
        self.image(f'{worker_root}/VocalWorker.exe', ['python312.dll'])
        self.image(f'{worker_root}/_internal/python312.dll', ['VCRUNTIME140.dll'])
        self.image(f'{worker_root}/_internal/vcruntime140.dll')

        report = audit.audit_graph(self.root, self.images)

        self.assertEqual(report['status'], 'passed')
        self.assertIn(worker_root, report['runtime_roots'])
        worker_resolution = next(item for item in report['resolutions']
                                 if item['image'].endswith('VocalWorker.exe'))
        self.assertEqual(worker_resolution['resolved'],
                         f'{worker_root}/_internal/python312.dll')

    def test_nested_runtime_cannot_borrow_parent_dependency(self):
        self.image('_internal/custom.dll')
        worker_root = '_internal/resources/workers/vocals'
        self.image(f'{worker_root}/VocalWorker.exe', ['custom.dll'])
        (self.root / worker_root / '_internal').mkdir(parents=True)

        report = audit.audit_graph(self.root, self.images)

        self.assertEqual(report['status'], 'needs-review')
        self.assertEqual(report['errors'][0]['reason'],
                         'non-OS dependency not bundled in declared loader directories')

    def test_declared_loader_directory_is_scoped_to_nested_runtime(self):
        worker_root = '_internal/resources/workers/vocals'
        self.image(f'{worker_root}/VocalWorker.exe')
        self.image(f'{worker_root}/_internal/numpy/core/_multiarray.pyd', ['openblas.dll'])
        self.image(f'{worker_root}/_internal/numpy.libs/openblas.dll')
        relative = f'{worker_root}/_internal/numpy.libs'

        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')
        self.assertEqual(audit.audit_graph(self.root, self.images, [relative])['status'], 'passed')

        self.images[self.root / 'app.exe']['imports'].append('openblas.dll')
        report = audit.audit_graph(self.root, self.images, [relative])
        self.assertEqual(report['status'], 'needs-review')
        self.assertTrue(any(item.get('image') == 'app.exe' for item in report['errors']))

if __name__ == '__main__':
    unittest.main()
