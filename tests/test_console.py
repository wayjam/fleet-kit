import os
import unittest
from io import StringIO
from unittest.mock import patch

from console import color_enabled, status, styled


class ConsoleTests(unittest.TestCase):
    def test_colors_auto_enable_only_for_tty(self):
        stream = StringIO()
        stream.isatty = lambda: True
        with patch.dict(os.environ, {"TERM": "xterm", "FLEET_COLOR": "auto"}, clear=True):
            self.assertTrue(color_enabled(stream))
            self.assertIn("\033[", styled("stage", "bold", stream=stream))

        stream.isatty = lambda: False
        with patch.dict(os.environ, {"TERM": "xterm", "FLEET_COLOR": "auto"}, clear=True):
            self.assertFalse(color_enabled(stream))
            self.assertEqual("stage", styled("stage", "bold", stream=stream))

    def test_no_color_disables_ansi_and_always_forces_it(self):
        stream = StringIO()
        with patch.dict(os.environ, {"FLEET_COLOR": "always"}, clear=True):
            self.assertIn("\033[", styled("stage", "bold", stream=stream))
        with patch.dict(os.environ, {"FLEET_COLOR": "always", "NO_COLOR": "1"}, clear=True):
            self.assertEqual("stage", styled("stage", "bold", stream=stream))

    def test_status_keeps_clear_text_without_color(self):
        stream = StringIO()
        with patch.dict(os.environ, {"FLEET_COLOR": "never"}, clear=True):
            self.assertEqual("✓ DONE deploy", status("✓ DONE", "deploy", level="success", stream=stream))


if __name__ == "__main__":
    unittest.main()
