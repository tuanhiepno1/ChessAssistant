from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import chess

from core.config_manager import ConfigManager
from engine.engine_manager import EngineManager


class AdaptiveTimeTests(unittest.TestCase):
    def test_quiet_opening_uses_minimum_time_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = EngineManager(ConfigManager(Path(directory) / "settings.json"))
            board = chess.Board()
            probe_lines = [
                {"score_cp": 30},
                {"score_cp": 15},
                {"score_cp": 5},
            ]

            target = manager._adaptive_target_ms(board, probe_lines, min_ms=700, max_ms=4200)

            self.assertEqual(target, 700)

    def test_tactical_position_can_use_realtime_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = EngineManager(ConfigManager(Path(directory) / "settings.json"))
            board = chess.Board("4k3/8/8/8/8/8/4Q3/4K3 b - - 0 1")
            probe_lines = [
                {"score_cp": 10},
                {"score_cp": 0},
                {"score_cp": -5},
            ]

            target = manager._adaptive_target_ms(board, probe_lines, min_ms=700, max_ms=4200)

            self.assertGreaterEqual(target, 2800)
            self.assertLessEqual(target, 4200)


if __name__ == "__main__":
    unittest.main()
