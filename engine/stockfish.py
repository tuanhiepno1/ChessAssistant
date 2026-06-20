from __future__ import annotations

import subprocess
import sys
import queue
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
            popen_args["creationflags"] = subprocess.CREATE_NO_WINDOW
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
        deadline = time.monotonic() + max(2.0, time_ms / 1000.0 + 3.0)
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

    def _send(self, command: str) -> None:
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
