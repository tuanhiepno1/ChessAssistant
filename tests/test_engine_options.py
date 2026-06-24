from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from core.config_manager import ConfigManager
from engine.engine_manager import EngineManager


class EngineOptionTests(unittest.TestCase):
    def test_multipv_switch_does_not_resend_threads_or_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("RAPID")
            manager = EngineManager(config)
            engine = Mock(path="")
            manager._engine = engine  # type: ignore[assignment]

            rapid = manager.load_config()
            manager._ensure_engine(rapid)
            first_options = engine.configure.call_args.args[0]
            self.assertEqual(first_options["Threads"], 8)
            self.assertEqual(first_options["Hash"], 2048)
            self.assertEqual(first_options["MultiPV"], 3)

            engine.configure.reset_mock()
            manager._ensure_engine(replace(rapid, multipv=1))

            engine.configure.assert_called_once_with({"MultiPV": 1})

    def test_unchanged_options_are_not_sent_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            manager = EngineManager(config)
            engine = Mock(path="")
            manager._engine = engine  # type: ignore[assignment]
            engine_config = manager.load_config()

            manager._ensure_engine(engine_config)
            engine.configure.reset_mock()
            manager._ensure_engine(engine_config)

            engine.configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
