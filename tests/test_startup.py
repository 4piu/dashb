import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from dashb import startup


class StartupCommandTests(unittest.TestCase):
    def test_source_command_uses_absolute_paths_and_startup_argument(self):
        with (
            patch.object(startup.sys, "frozen", False, create=True),
            patch.object(startup.sys, "executable", r"C:\Python Dir\python.exe"),
            patch.object(startup, "app_root", return_value=Path(r"C:\Dashb Dir")),
        ):
            argv = startup.startup_argv()
            command = startup.startup_command()

        self.assertTrue(Path(argv[0]).is_absolute())
        self.assertTrue(Path(argv[1]).is_absolute())
        self.assertEqual(argv[-1], "--startup")
        self.assertIn('"C:\\Python Dir\\python.exe"', command)
        self.assertIn('"C:\\Dashb Dir\\main.py"', command)

    def test_frozen_command_relaunches_executable(self):
        with (
            patch.object(startup.sys, "frozen", True, create=True),
            patch.object(startup.sys, "executable", r"C:\Apps\Dashb.exe"),
        ):
            argv = startup.startup_argv()

        self.assertEqual(argv, [r"C:\Apps\Dashb.exe", "--startup"])

    def test_enabling_writes_the_current_command_to_the_user_run_key(self):
        fake_winreg = MagicMock()
        key = object()
        fake_winreg.CreateKeyEx.return_value.__enter__.return_value = key

        with (
            patch.object(startup, "winreg", fake_winreg),
            patch.object(startup, "is_supported", return_value=True),
            patch.object(startup, "startup_command", return_value="dashb command"),
        ):
            startup.set_enabled(True)

        fake_winreg.SetValueEx.assert_called_once_with(
            key,
            startup.RUN_VALUE_NAME,
            0,
            fake_winreg.REG_SZ,
            "dashb command",
        )

    def test_disabling_removes_the_user_run_value(self):
        fake_winreg = MagicMock()
        key = object()
        fake_winreg.OpenKey.return_value.__enter__.return_value = key

        with (
            patch.object(startup, "winreg", fake_winreg),
            patch.object(startup, "is_supported", return_value=True),
        ):
            startup.set_enabled(False)

        fake_winreg.DeleteValue.assert_called_once_with(key, startup.RUN_VALUE_NAME)


if __name__ == "__main__":
    unittest.main()
