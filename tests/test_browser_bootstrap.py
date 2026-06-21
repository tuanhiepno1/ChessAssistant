from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app.browser_bootstrap import _find_browser


class BrowserDiscoveryTests(unittest.TestCase):
    def test_edge_is_used_when_coccoc_and_chrome_are_missing(self) -> None:
        environment = {
            "LOCALAPPDATA": r"C:\Local",
            "PROGRAMFILES": r"C:\Program Files",
            "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
        }

        def only_edge_exists(path: Path) -> bool:
            return str(path).replace("\\", "/").endswith(
                "Microsoft/Edge/Application/msedge.exe"
            )

        with patch.dict(os.environ, environment, clear=False), patch.object(
            Path, "is_file", only_edge_exists
        ):
            browser = _find_browser()

        self.assertIsNotNone(browser)
        assert browser is not None
        self.assertEqual(browser[0], "Microsoft Edge")
        self.assertEqual(browser[2], "ChessAssistantEdge")


if __name__ == "__main__":
    unittest.main()
