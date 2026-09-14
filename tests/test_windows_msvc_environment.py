import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WindowsEnvironmentTests(unittest.TestCase):
    def test_spaced_tool_path_is_quoted_inside_batch(self):
        batch = (ROOT / 'packaging/windows/msvc_environment.cmd').read_text(encoding='utf-8')
        workflow = (ROOT / '.github/workflows/bundle-validation.yml').read_text(encoding='utf-8')
        self.assertIn('call "%~1" -arch=x64 -host_arch=x64 >nul', batch)
        self.assertIn('if errorlevel 1 exit /b 1', batch)
        self.assertNotIn('\nset\n', batch)
        self.assertIn('cmd.exe /d /c packaging\\windows\\msvc_environment.cmd $devCmd', workflow)
        self.assertNotIn('cmd.exe /d /s /c', workflow)
