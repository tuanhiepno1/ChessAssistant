from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

from core.config_manager import ConfigManager
from engine.engine_manager import EngineManager


class FakePonderEngine:
    def __init__(self, progress_count: int = 1, progress_depth: int = 18) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.hit = False
        self.progress_count = progress_count
        self.progress_depth = progress_depth

    def ponder(
        self,
        board: chess.Board,
        multipv: int,
        max_time_ms: int,
        started: threading.Event,
        on_progress=None,
    ) -> list[dict[str, object]]:
        started.set()
        self.started.set()
        if on_progress is not None:
            on_progress(self.progress_count, self.progress_depth)
        self.stopped.wait(2.0)
        return [
            {
                "pv_uci": [move.uci()],
                "score_cp": 20,
                "score_text": "+0.20",
                "depth": 18,
                "seldepth": 22,
                "nodes": 1000,
                "tbhits": 0,
                "hashfull": 1,
            }
            for move in list(board.legal_moves)[: self.progress_count]
        ]

    def ponder_hit(self) -> None:
        self.hit = True

    def stop(self) -> None:
        self.stopped.set()


class StubbornPonderEngine(FakePonderEngine):
    def __init__(self) -> None:
        super().__init__()
        self.aborted = False

    def stop(self) -> None:
        return

    def abort(self) -> None:
        self.aborted = True
        self.stopped.set()


class PonderSessionTests(unittest.TestCase):
    @staticmethod
    def _target_and_miss() -> tuple[str, str]:
        hit = chess.Board()
        hit.push_san("e4")
        hit.push_san("e5")
        miss = chess.Board()
        miss.push_san("e4")
        miss.push_san("c5")
        return hit.fen(), miss.fen()

    def test_hit_returns_ponder_result_and_sends_ponderhit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("RAPID")
            manager = EngineManager(config)
            engine = FakePonderEngine()
            manager._engine = engine  # type: ignore[assignment]
            target, _ = self._target_and_miss()
            origin = chess.Board().fen()

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.start_ponder(
                    target,
                    multipv=4,
                    max_time_ms=10000,
                    origin_fen=origin,
                )
                self.assertTrue(engine.started.wait(1.0))
                self.assertEqual(manager.ponder_phase_for_origin(origin), "running")
                self.assertEqual(
                    manager.ponder_progress_for_origin(origin),
                    ("running", 1, 4, 18),
                )
                result, outcome = manager.resolve_ponder(target, settle_ms=0)

            self.assertEqual(outcome, "hit-partial")
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.source, "ponder")
            self.assertTrue(engine.hit)
            self.assertEqual(manager.ponder_phase_for_origin(origin), "none")

    def test_four_live_lines_mark_ponder_ready_before_search_stops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            manager = EngineManager(config)
            engine = FakePonderEngine(progress_count=4)
            manager._engine = engine  # type: ignore[assignment]
            target, _ = self._target_and_miss()
            origin = chess.Board().fen()

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.start_ponder(
                    target,
                    multipv=4,
                    max_time_ms=10000,
                    origin_fen=origin,
                )
                self.assertTrue(engine.started.wait(1.0))
                self.assertEqual(
                    manager.ponder_progress_for_origin(origin),
                    ("ready", 4, 4, 18),
                )
                self.assertEqual(manager.ponder_phase_for_origin(origin), "ready")
                manager.stop_ponder()

    def test_four_shallow_lines_do_not_mark_ponder_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            manager = EngineManager(config)
            engine = FakePonderEngine(progress_count=4, progress_depth=7)
            manager._engine = engine  # type: ignore[assignment]
            target, _ = self._target_and_miss()
            origin = chess.Board().fen()

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.start_ponder(
                    target,
                    multipv=4,
                    max_time_ms=10000,
                    origin_fen=origin,
                )
                self.assertTrue(engine.started.wait(1.0))
                self.assertEqual(
                    manager.ponder_progress_for_origin(origin),
                    ("running", 4, 4, 7),
                )
                manager.stop_ponder()

    def test_miss_discards_ponder_result_without_ponderhit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("RAPID")
            manager = EngineManager(config)
            engine = FakePonderEngine()
            manager._engine = engine  # type: ignore[assignment]
            target, miss = self._target_and_miss()

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.start_ponder(target, multipv=4, max_time_ms=10000)
                self.assertTrue(engine.started.wait(1.0))
                result, outcome = manager.resolve_ponder(miss, settle_ms=0)

            self.assertEqual(outcome, "miss")
            self.assertIsNone(result)
            self.assertFalse(engine.hit)

    def test_miss_aborts_stubborn_ponder_after_short_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / "settings.json")
            config.apply_time_control_preset("RAPID")
            config.set("analysis.ponder_stop_timeout_ms", 50)
            manager = EngineManager(config)
            engine = StubbornPonderEngine()
            manager._engine = engine  # type: ignore[assignment]
            target, miss = self._target_and_miss()

            with patch.object(manager, "_ensure_engine", return_value=engine):
                manager.start_ponder(target, multipv=1, max_time_ms=10000)
                self.assertTrue(engine.started.wait(1.0))
                started = time.perf_counter()
                result, outcome = manager.resolve_ponder(miss, settle_ms=0)
                elapsed = time.perf_counter() - started

            self.assertEqual(outcome, "miss")
            self.assertIsNone(result)
            self.assertTrue(engine.aborted)
            self.assertLess(elapsed, 0.75)
            self.assertIsNone(manager._configured_options)


if __name__ == "__main__":
    unittest.main()
