from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import chess

from core.config_manager import ConfigManager
from engine.engine_manager import EngineManager


class AdaptiveTimeTests(unittest.TestCase):
    @staticmethod
    def _engine_line(move: str = "e2e4") -> dict[str, object]:
        return {
            "pv_uci": [move],
            "score_cp": 20,
            "score_text": "+0.20",
        }

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

    def test_realtime_fixed_search_uses_single_pv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("engine.multipv", 4)
            config.set("analysis.adaptive_time_enabled", False)
            manager = EngineManager(config)
            engine = Mock()
            engine.analyze.return_value = [self._engine_line()]

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.analyze_fen(chess.STARTING_FEN, realtime=True)

            self.assertEqual(engine.analyze.call_args.kwargs["multipv"], 1)

    def test_realtime_override_requests_three_pvs_for_chesscom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("analysis.adaptive_time_enabled", False)
            manager = EngineManager(config)
            engine = Mock()
            engine.analyze.return_value = [self._engine_line()]

            with (
                patch.object(manager, "_ensure_engine", return_value=engine),
                patch.object(manager, "_try_opening_book") as opening_book,
            ):
                manager.analyze_fen(
                    chess.STARTING_FEN,
                    realtime=True,
                    multipv_override=3,
                )

            self.assertEqual(engine.analyze.call_args.kwargs["multipv"], 3)
            opening_book.assert_not_called()

    def test_realtime_adaptive_probe_uses_single_pv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("engine.multipv", 4)
            config.set("analysis.adaptive_time_enabled", True)
            manager = EngineManager(config)
            engine = Mock()
            engine.analyze.return_value = [self._engine_line()]

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.analyze_fen(chess.STARTING_FEN, realtime=True)

            self.assertTrue(engine.analyze.called)
            self.assertTrue(
                all(call.kwargs["multipv"] == 1 for call in engine.analyze.call_args_list)
            )

    def test_non_realtime_fixed_search_preserves_configured_multipv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.set("engine.multipv", 4)
            config.set("analysis.adaptive_time_enabled", False)
            manager = EngineManager(config)
            engine = Mock()
            engine.analyze.return_value = [self._engine_line()]

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.analyze_fen(chess.STARTING_FEN, realtime=False)

            self.assertEqual(engine.analyze.call_args.kwargs["multipv"], 4)

    def test_fast_ponder_miss_search_honors_time_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            manager = EngineManager(config)
            engine = Mock()
            engine.analyze.return_value = [self._engine_line()]

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.analyze_fen(
                    chess.STARTING_FEN,
                    force=True,
                    realtime=True,
                    multipv_override=4,
                    time_ms_override=650,
                    adaptive_override=False,
                )

            self.assertEqual(engine.analyze.call_args.kwargs["time_ms"], 650)
            self.assertEqual(engine.analyze.call_args.kwargs["multipv"], 4)

    def test_bullet_skips_tablebase_and_does_not_retry_failed_realtime_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("BULLET")
            config.set("tablebase.enabled", True)
            manager = EngineManager(config)
            engine = Mock()
            engine.analyze.side_effect = RuntimeError("engine stopped")

            with (
                patch.object(manager, "_ensure_engine", return_value=engine),
                patch.object(manager, "_try_tablebase") as tablebase,
                patch.object(manager, "_try_opening_book", return_value=None),
                patch.object(manager, "_close_engine"),
            ):
                with self.assertRaises(RuntimeError):
                    manager.analyze_fen(chess.STARTING_FEN, force=True, realtime=False)

            tablebase.assert_not_called()
            self.assertEqual(engine.analyze.call_count, 1)


if __name__ == "__main__":
    unittest.main()
