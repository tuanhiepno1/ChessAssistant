from __future__ import annotations

import subprocess
import time
import unittest
from unittest.mock import Mock, PropertyMock, patch

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
    def test_windows_engine_process_runs_below_normal_priority(self) -> None:
        engine = UciEngine("stockfish.exe")
        process = Mock()
        process.poll.return_value = None
        process.stdin = Mock()
        process.stdout = []

        with (
            patch("engine.stockfish.Path.exists", return_value=True),
            patch("engine.stockfish.subprocess.Popen", return_value=process) as popen,
            patch.object(engine, "_pump_stdout"),
            patch.object(engine, "_read_until"),
            patch("engine.stockfish.sys.platform", "win32"),
        ):
            engine.start()

        flags = popen.call_args.kwargs["creationflags"]
        self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)
        self.assertTrue(flags & subprocess.BELOW_NORMAL_PRIORITY_CLASS)

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

    def test_ponder_uses_go_ponder_and_collects_latest_lines(self) -> None:
        engine = UciEngine("unused")
        commands: list[str] = []
        progress: list[tuple[int, int]] = []
        engine._stdout_queue.put(
            "info depth 18 multipv 1 score cp 25 pv e2e4 e7e5"
        )
        engine._stdout_queue.put(
            "info depth 18 multipv 2 score cp 18 pv d2d4 d7d5"
        )
        engine._stdout_queue.put("bestmove e2e4 ponder e7e5")

        with (
            patch.object(engine, "start"),
            patch.object(engine, "_send", side_effect=commands.append),
        ):
            lines = engine.ponder(
                chess.Board(),
                multipv=2,
                max_time_ms=1000,
                on_progress=lambda count, depth: progress.append((count, depth)),
            )

        self.assertEqual(commands[-1], "go ponder")
        self.assertEqual(lines[0]["pv_uci"][0], "e2e4")
        self.assertEqual(len(lines), 2)
        self.assertEqual(progress, [(1, 18), (2, 18)])

    def test_ponder_hit_sends_uci_command(self) -> None:
        engine = UciEngine("unused")

        with (
            patch.object(UciEngine, "is_running", new_callable=PropertyMock, return_value=True),
            patch.object(engine, "_send") as send,
        ):
            engine.ponder_hit()

        send.assert_called_once_with("ponderhit")

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
