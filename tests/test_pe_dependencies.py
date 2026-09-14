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
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')
        self.images[self.root / 'app.exe']['imports'] = []
        self.images[self.root / 'custom.dll']['machine'] = 0x14c
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')

    def test_invalid_directory_and_import_rejected(self):
        for path in ('../escape', '/absolute', 'missing'):
            with self.assertRaises(ValueError):
                audit.audit_graph(self.root, self.images, [path])
        self.images[self.root / 'app.exe']['imports'].append('../private.dll')
        self.assertEqual(audit.audit_graph(self.root, self.images)['status'], 'needs-review')

if __name__ == '__main__':
    unittest.main()
