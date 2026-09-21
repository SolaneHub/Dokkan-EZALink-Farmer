import os
import unittest
from core.system_tools import get_resource_path, get_config_path, ToolLocator


class TestSystemTools(unittest.TestCase):

    def test_get_resource_path(self):
        # In development mode, get_resource_path should resolve from project root
        res_path = get_resource_path("templates")
        self.assertTrue(os.path.isdir(res_path), f"Resource path '{res_path}' should be an existing directory")

        locales_path = get_resource_path("locales")
        self.assertTrue(os.path.isdir(locales_path), f"Locales path '{locales_path}' should be an existing directory")

    def test_get_config_path(self):
        cfg_path = get_config_path("config/settings.yaml")
        self.assertTrue(os.path.isfile(cfg_path), f"Config path '{cfg_path}' should resolve to an existing file")

    def test_diagnose_system_structure(self):
        diag = ToolLocator.diagnose_system()
        self.assertIn("os", diag)
        self.assertIn("platform", diag)
        self.assertIn("python_version", diag)
        self.assertIn("scrcpy", diag)
        self.assertIn("adb", diag)
        self.assertIn("found", diag["adb"])
        self.assertIn("found", diag["scrcpy"])
        self.assertIn("install_help", diag)


if __name__ == "__main__":
    unittest.main()
