from __future__ import annotations

import subprocess
import sys
import queue
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import chess


@dataclass(frozen=True)
class EngineLine:
    move_uci: str
    move_san: str
    score: str
    depth: int | None
    seldepth: int | None
    nodes: int | None
    tbhits: int | None
    hashfull: int | None
    pv: list[str]
    score_cp: int | None = None


@dataclass(frozen=True)
class AnalysisResult:
    fen: str
    best_move_uci: str
    best_move_san: str
    evaluation: str
    depth: int | None
    seldepth: int | None
    nodes: int | None
    tbhits: int | None
    hashfull: int | None
    thinking_time_ms: int
    lines: list[EngineLine]
    source: str = "engine"


class UciEngine:
    def __init__(self, path: str) -> None:
        self.path = path
        self._engine: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stdin_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._engine is not None and self._engine.poll() is None

    def start(self) -> None:
        if self.is_running:
            return
        if not self.path:
            raise FileNotFoundError("Chưa cài đặt đường dẫn Stockfish.")
        engine_path = Path(self.path)
        if not engine_path.exists():
            raise FileNotFoundError(f"Không tìm thấy Stockfish: {engine_path}")
        popen_args: dict[str, Any] = {}
        if sys.platform == "win32":
            # Keep all engine threads available for strength, but let the
            # browser and Qt UI win scheduling contention during ponder.
            popen_args["creationflags"] = (
                subprocess.CREATE_NO_WINDOW
                | subprocess.BELOW_NORMAL_PRIORITY_CLASS
            )
        self._engine = subprocess.Popen(
            [str(engine_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            **popen_args,
        )
        self._stdout_queue = queue.Queue()
        self._stdout_thread = threading.Thread(
            target=self._pump_stdout,
            args=(self._engine,),
            daemon=True,
            name="stockfish-stdout",
        )
        self._stdout_thread.start()
        self._send("uci")
        self._read_until("uciok", timeout_seconds=5.0)

    def configure(self, options: dict[str, Any]) -> None:
        self.start()
        for key, value in options.items():
            if value is None:
                continue
            if key in {"UCI_Chess960", "UCI_Variant"}:
                continue
            self._send(f"setoption name {key} value {self._format_option_value(value)}")
        self._send("isready")
        self._read_until("readyok", timeout_seconds=10.0)

    def new_game(self) -> None:
        self.start()
        self._send("ucinewgame")
        self._send("isready")
        self._read_until("readyok", timeout_seconds=10.0)

    def analyze(
        self,
        board: chess.Board,
        time_ms: int,
        multipv: int,
        root_moves: list[chess.Move] | None = None,
    ) -> list[dict[str, Any]]:
        self.start()
        self._send(f"position fen {board.fen()}")
        search_moves = ""
        if root_moves:
            search_moves = " searchmoves " + " ".join(move.uci() for move in root_moves)
        self._send(f"go movetime {max(time_ms, 1)}{search_moves}")

        latest: dict[int, dict[str, Any]] = {}
        # A realtime caller will poll again. A short grace period is enough to
        # receive bestmove and prevents one wedged engine from freezing updates
        # for 15+ seconds.
        deadline = time.monotonic() + max(0.5, time_ms / 1000.0 + 0.3)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.abort()
                raise TimeoutError(
                    f"Stockfish không trả bestmove sau {time_ms} ms; tiến trình đã được dừng."
                )
            line = self._read_line(timeout_seconds=remaining)
            if line.startswith("bestmove"):
                break
            if not line.startswith("info "):
                continue
            parsed = self._parse_info(line)
            if parsed is None:
                continue
            latest[int(parsed.get("multipv", 1))] = parsed
        return [latest[key] for key in sorted(latest)[: max(multipv, 1)]]

    def ponder(
        self,
        board: chess.Board,
        multipv: int,
        max_time_ms: int,
        started: threading.Event | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Search a predicted position until hit/stop or the safety cap."""
        self.start()
        self._send(f"position fen {board.fen()}")
        self._send("go ponder")
        if started is not None:
            started.set()

        latest: dict[int, dict[str, Any]] = {}
        reported_progress = (0, 0)
        deadline = time.monotonic() + max(0.25, max_time_ms / 1000.0)
        drain_deadline: float | None = None
        while True:
            now = time.monotonic()
            if drain_deadline is None and now >= deadline:
                self.stop()
                drain_deadline = now + 2.0
            if drain_deadline is not None and now >= drain_deadline:
                self.abort()
                raise TimeoutError("Stockfish không kết thúc ponder sau lệnh stop.")
            try:
                line = self._stdout_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError("Stockfish đã dừng đột ngột khi ponder.")
            if line.startswith("bestmove"):
                break
            if not line.startswith("info "):
                continue
            parsed = self._parse_info(line)
            if parsed is not None:
                latest[int(parsed.get("multipv", 1))] = parsed
                depths = [int(item.get("depth", 0) or 0) for item in latest.values()]
                progress = (
                    min(len(latest), max(multipv, 1)),
                    min(depths) if depths else 0,
                )
                if on_progress is not None and progress != reported_progress:
                    reported_progress = progress
                    on_progress(*progress)
        return [latest[key] for key in sorted(latest)[: max(multipv, 1)]]

    def ponder_hit(self) -> None:
        if not self.is_running:
            return
        with suppress(Exception):
            self._send("ponderhit")

    def quit(self) -> None:
        if self._engine is None:
            return
        process = self._engine
        self._engine = None
        try:
            if process.poll() is None:
                if process.stdin is not None:
                    process.stdin.write("quit\n")
                    process.stdin.flush()
                process.wait(timeout=1)
        except Exception:
            with suppress(Exception):
                process.kill()
        finally:
            with suppress(Exception):
                if process.stdin is not None:
                    process.stdin.close()
            with suppress(Exception):
                if process.stdout is not None:
                    process.stdout.close()
            self._stdout_thread = None

    def abort(self) -> None:
        process = self._engine
        self._engine = None
        if process is None:
            return
        with suppress(Exception):
            process.kill()
        with suppress(Exception):
            process.wait(timeout=1)
        with suppress(Exception):
            if process.stdin is not None:
                process.stdin.close()
        with suppress(Exception):
            if process.stdout is not None:
                process.stdout.close()
        self._stdout_thread = None

    def stop(self) -> None:
        """Ask an active search to return its best move immediately."""
        if not self.is_running:
            return
        with suppress(Exception):
            self._send("stop")

    def _send(self, command: str) -> None:
        with self._stdin_lock:
            if self._engine is None or self._engine.stdin is None:
                raise RuntimeError("Stockfish chưa sẵn sàng.")
            self._engine.stdin.write(command + "\n")
            self._engine.stdin.flush()

    def _read_line(self, timeout_seconds: float = 5.0) -> str:
        if self._engine is None:
            raise RuntimeError("Stockfish chưa sẵn sàng.")
        try:
            line = self._stdout_queue.get(timeout=max(timeout_seconds, 0.01))
        except queue.Empty as exc:
            self.abort()
            raise TimeoutError("Stockfish không phản hồi đúng thời hạn; tiến trình đã được dừng.") from exc
        if line is None:
            raise RuntimeError("Stockfish đã dừng đột ngột.")
        return line

    def _read_until(self, marker: str, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.abort()
                raise TimeoutError(f"Stockfish không trả về tín hiệu {marker} đúng thời hạn.")
            if self._read_line(timeout_seconds=remaining) == marker:
                return

    def _pump_stdout(self, process: subprocess.Popen[str]) -> None:
        stdout = process.stdout
        if stdout is None:
            self._stdout_queue.put(None)
            return
        try:
            for line in stdout:
                self._stdout_queue.put(line.strip())
        finally:
            self._stdout_queue.put(None)

    @staticmethod
    def _format_option_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _parse_info(line: str) -> dict[str, Any] | None:
        tokens = line.split()
        if "pv" not in tokens:
            return None
        parsed: dict[str, Any] = {
            "multipv": 1,
            "depth": None,
            "seldepth": None,
            "nodes": None,
            "tbhits": None,
            "hashfull": None,
            "score_cp": None,
            "score_text": "không có",
        }
        idx = 1
        while idx < len(tokens):
            token = tokens[idx]
            if token == "depth" and idx + 1 < len(tokens):
                parsed["depth"] = int(tokens[idx + 1])
                idx += 2
            elif token == "seldepth" and idx + 1 < len(tokens):
                parsed["seldepth"] = int(tokens[idx + 1])
                idx += 2
            elif token == "nodes" and idx + 1 < len(tokens):
                parsed["nodes"] = int(tokens[idx + 1])
                idx += 2
            elif token == "tbhits" and idx + 1 < len(tokens):
                parsed["tbhits"] = int(tokens[idx + 1])
                idx += 2
            elif token == "hashfull" and idx + 1 < len(tokens):
                parsed["hashfull"] = int(tokens[idx + 1])
                idx += 2
            elif token == "multipv" and idx + 1 < len(tokens):
                parsed["multipv"] = int(tokens[idx + 1])
                idx += 2
            elif token == "score" and idx + 2 < len(tokens):
                score_type = tokens[idx + 1]
                score_value = int(tokens[idx + 2])
                if score_type == "cp":
                    parsed["score_cp"] = score_value
                    parsed["score_text"] = f"{score_value / 100:+.2f}"
                elif score_type == "mate":
                    parsed["score_cp"] = 100000 if score_value > 0 else -100000
                    parsed["score_text"] = f"Chiếu hết sau {abs(score_value)} nước"
                idx += 3
            elif token == "pv":
                parsed["pv_uci"] = tokens[idx + 1 :]
                return parsed
            else:
                idx += 1
        return None


class StockfishEngine(UciEngine):
    pass
