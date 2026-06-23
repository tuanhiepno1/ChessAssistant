from __future__ import annotations

import time
import unittest
from unittest.mock import PropertyMock, patch

import chess

from engine.stockfish import UciEngine


class FakeProcess:
    stdin = None
    stdout = None

    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


class StockfishTimeoutTests(unittest.TestCase):
    def test_stop_interrupts_active_search(self) -> None:
        engine = UciEngine("unused")

        with (
            patch.object(UciEngine, "is_running", new_callable=PropertyMock, return_value=True),
            patch.object(engine, "_send") as send,
        ):
            engine.stop()

        send.assert_called_once_with("stop")

    def test_analysis_uses_go_movetime_command(self) -> None:
        engine = UciEngine("unused")
        commands: list[str] = []

        with (
            patch.object(engine, "start"),
            patch.object(engine, "_send", side_effect=commands.append),
            patch.object(engine, "_read_line", return_value="bestmove e2e4"),
        ):
            engine.analyze(chess.Board(), time_ms=321, multipv=1)

        self.assertEqual(commands[-1], "go movetime 321")

    def test_read_timeout_aborts_engine_instead_of_blocking_forever(self) -> None:
        engine = UciEngine("unused")
        process = FakeProcess()
        engine._engine = process  # type: ignore[assignment]

        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            engine._read_line(timeout_seconds=0.02)

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(process.killed)
        self.assertIsNone(engine._engine)


if __name__ == "__main__":
    unittest.main()
