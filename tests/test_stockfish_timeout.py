from __future__ import annotations

import time
import unittest

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
