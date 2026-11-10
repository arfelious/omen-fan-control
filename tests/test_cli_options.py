"""Tests for the ``options`` CLI command validation."""

import os
import sys
import types
import unittest
from unittest import mock

try:
    import fcntl  # noqa: F401  (Unix-only; stubbed below on other platforms)
except ImportError:  # pragma: no cover
    sys.modules.setdefault("fcntl", types.ModuleType("fcntl"))

if not hasattr(os, "geteuid"):  # pragma: no cover
    # Non-Unix test shim (Linux CI is unaffected): _constants.py probes the
    # effective uid at import time to pick default paths.
    os.geteuid = lambda: 0

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
)

from click.testing import CliRunner

from omen_fan_control.cli import options


class FakeController:
    """Minimal stand-in for FanController (no hardware or root needed)."""

    def __init__(self):
        self.config = {}
        self.saved = False

    def check_install_type(self):
        return None

    def save_config(self):
        self.saved = True


class OptionsValidationTests(unittest.TestCase):
    def invoke(self, *argv):
        controller = FakeController()
        with mock.patch(
            "omen_fan_control.cli.get_controller", return_value=controller
        ):
            result = CliRunner().invoke(options, list(argv))
        return controller, result

    def test_zero_wait_time_fails(self):
        _, result = self.invoke("--wait-time", "0")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("must be positive", result.output)

    def test_zero_watchdog_fails(self):
        _, result = self.invoke("--watchdog", "0")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("must be positive", result.output)

    def test_zero_ma_window_fails(self):
        _, result = self.invoke("--ma-window", "0")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("must be positive", result.output)

    def test_valid_wait_time_succeeds(self):
        controller, result = self.invoke("--wait-time", "10")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(controller.config["calibration_wait"], 10)
        self.assertTrue(controller.saved)


if __name__ == "__main__":
    unittest.main()
