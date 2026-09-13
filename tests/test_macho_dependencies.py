import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('macho_audit', Path(__file__).resolve().parents[1] / 'packaging/mac/check_dependencies.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class MachOClosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name) / 'App.app'
        self.images = {}
        self.exe = self.image('Contents/MacOS/Main', 'EXECUTE')

    def image(self, path, kind='DYLIB', links=(), rpaths=()):
        target = self.app / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        self.images[target] = {'kind':kind, 'links':list(links), 'rpaths':list(rpaths)}
        return target

    def result(self):
        return audit.audit_graph(self.app, self.images)

    def test_inherited_owner_rpath(self):
        self.image('Contents/Frameworks/pkg/ext.so', 'BUNDLE', ['@rpath/libA.dylib'], ['@loader_path/..'])
        self.image('Contents/Frameworks/libA.dylib', links=['@rpath/libB.dylib'], rpaths=['@loader_path/../..'])
        self.image('Contents/Frameworks/libB.dylib')
        self.assertEqual(self.result()['status'], 'passed')

    def test_unrelated_rpath_not_global_fallback(self):
        self.image('Contents/Frameworks/pkg/ext.so', 'BUNDLE', ['@rpath/libB.dylib'])
        self.image('Contents/Frameworks/unrelated.so', 'BUNDLE', rpaths=['@loader_path'])
        self.image('Contents/Frameworks/libB.dylib')
        self.assertEqual(self.result()['status'], 'needs-review')

    def test_first_external_candidate_not_rescued(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir(); (outside / 'libA.dylib').touch()
        self.image('Contents/Frameworks/ext.so', 'BUNDLE', ['@rpath/libA.dylib'], [str(outside), '@loader_path'])
        self.image('Contents/Frameworks/libA.dylib')
        self.assertTrue(self.result()['absolute_or_external_errors'])

    def test_symlink_escape_dependency(self):
        external = Path(self.temp.name) / 'libA.dylib'; external.touch()
        self.image('Contents/Frameworks/ext.so', 'BUNDLE', ['@loader_path/libA.dylib'])
        (self.app / 'Contents/Frameworks/libA.dylib').symlink_to(external)
        self.assertTrue(self.result()['absolute_or_external_errors'])

    def test_cycle_terminates_and_missing_fails(self):
        self.images[self.exe]['links'] = ['@loader_path/../Frameworks/A.dylib']
        self.image('Contents/Frameworks/A.dylib', links=['@loader_path/B.dylib'])
        self.image('Contents/Frameworks/B.dylib', links=['@loader_path/A.dylib'])
        self.assertEqual(self.result()['status'], 'passed')
        self.images[self.exe]['links'].append('@rpath/missing.dylib')
        self.assertEqual(self.result()['status'], 'needs-review')

    def test_distinct_executable_contexts(self):
        shared = self.image('Contents/Frameworks/A.dylib', links=['@executable_path/B.dylib'])
        self.images[self.exe]['links'] = ['@loader_path/../Frameworks/A.dylib']
        self.image('Contents/MacOS/B.dylib')
        self.image('Contents/Tools/Tool', 'EXECUTE', ['@loader_path/../Frameworks/A.dylib'])
        self.assertEqual(self.result()['status'], 'needs-review')
        self.image('Contents/Tools/B.dylib')
        self.assertEqual(self.result()['status'], 'passed')

    def test_orphan_not_silently_accepted(self):
        self.image('Contents/Frameworks/orphan.dylib')
        self.assertEqual(self.result()['status'], 'needs-review')

    def test_python_extension_can_be_mh_dylib(self):
        self.image('Contents/Frameworks/tokenizers/tokenizers.abi3.so', 'DYLIB',
                   ['@rpath/libA.dylib'], ['@loader_path/..'])
        self.image('Contents/Frameworks/libA.dylib')
        self.assertEqual(self.result()['status'], 'passed')

    def test_explicit_dynamic_root_validated_and_audited(self):
        self.image('Contents/Frameworks/runtime.dylib', links=['@loader_path/child.dylib'])
        self.image('Contents/Frameworks/child.dylib')
        relative = 'Contents/Frameworks/runtime.dylib'
        self.assertEqual(audit.audit_graph(self.app, self.images, [relative])['status'], 'passed')
        for invalid in ('../outside', '/absolute', 'Contents/missing'):
            with self.assertRaises(ValueError):
                audit.audit_graph(self.app, self.images, [invalid])
        self.images[self.app / relative]['links'].append('@rpath/missing')
        self.assertEqual(audit.audit_graph(self.app, self.images, [relative])['status'], 'needs-review')

    def test_load_command_parser_excludes_own_id(self):
        output = 'cmd LC_ID_DYLIB\nname @rpath/self.dylib (offset 24)\ncmd LC_RPATH\npath @loader_path (offset 12)\ncmd LC_LOAD_WEAK_DYLIB\nname @rpath/required.dylib (offset 24)'
        with patch.object(audit, 'command', side_effect=['MH_MAGIC_64 X86_64 DYLIB', output]):
            metadata = audit.read_image(Path('image'))
        self.assertEqual(metadata['links'], ['@rpath/required.dylib'])
        self.assertEqual(metadata['rpaths'], ['@loader_path'])

if __name__ == '__main__':
    unittest.main()
