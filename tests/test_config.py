import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import AppSettings, load_app_settings, parse_port, validate_server_settings


class ConfigTest(unittest.TestCase):
    def test_parse_port_validates_range(self):
        self.assertEqual(parse_port("8787"), 8787)
        with self.assertRaises(ValueError):
            parse_port("70000")

    def test_load_app_settings_from_env(self):
        env = {
            "DINGTALK_GATEWAY_HOST": "0.0.0.0",
            "DINGTALK_GATEWAY_PORT": "9000",
            "DINGTALK_GATEWAY_API_TOKEN": "secret",
            "DINGTALK_GATEWAY_ENV": "production",
            "DINGTALK_GATEWAY_WORKSPACES_CONFIG": "/tmp/workspaces.json",
            "DINGTALK_GATEWAY_DEFAULT_WORKSPACE": "default",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = load_app_settings()
        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 9000)
        self.assertEqual(settings.api_token, "secret")
        self.assertEqual(settings.environment, "production")
        self.assertEqual(settings.workspaces_config, Path("/tmp/workspaces.json"))
        self.assertEqual(settings.default_workspace, "default")

    def test_non_loopback_requires_auth(self):
        settings = AppSettings("0.0.0.0", 8787, "", False, "production", Path("config/workspaces.json"), "default")
        with self.assertRaises(RuntimeError):
            validate_server_settings(settings)

    def test_require_auth_requires_token(self):
        settings = AppSettings("127.0.0.1", 8787, "", True, "production", Path("config/workspaces.json"), "default")
        with self.assertRaises(RuntimeError):
            validate_server_settings(settings)


if __name__ == "__main__":
    unittest.main()
