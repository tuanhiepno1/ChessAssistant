from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

import chess

from books.opening_manager import OpeningManager
from core.config_manager import ConfigManager
from engine.stockfish import AnalysisResult, EngineLine, StockfishEngine
from tablebase.syzygy_manager import SyzygyManager


@dataclass(frozen=True)
class EngineConfig:
    path: str
    threads: int
    hash_mb: int
    ponder: bool
    multipv: int
    skill_level: int
    contempt: int
    uci_options: dict[str, Any]


class EngineManager:
    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self._engine: StockfishEngine | None = None
        self._opening_manager = OpeningManager()
        self._configured_options: tuple[tuple[str, str], ...] | None = None
        self._cache: dict[tuple[Any, ...], AnalysisResult] = {}
        self._lock = threading.Lock()

    def load_config(self) -> EngineConfig:
        return EngineConfig(
            path=str(self.config.get("engine.stockfish_path", "")),
            threads=int(self.config.get("engine.threads", 16)),
            hash_mb=int(self.config.get("engine.hash_mb", 8192)),
            ponder=bool(self.config.get("engine.ponder", True)),
            multipv=int(self.config.get("engine.multipv", 3)),
            skill_level=int(self.config.get("engine.skill_level", 20)),
            contempt=int(self.config.get("engine.contempt", 0)),
            uci_options=dict(self.config.get("engine.uci_options", {})),
        )

    def _ensure_engine(self, engine_config: EngineConfig) -> StockfishEngine:
        if self._engine is None or self._engine.path != engine_config.path:
            self._close_engine()
            self._engine = StockfishEngine(engine_config.path)

        options: dict[str, Any] = {
            "Threads": engine_config.threads,
            "Hash": engine_config.hash_mb,
            "Ponder": engine_config.ponder,
            "MultiPV": engine_config.multipv,
            "Skill Level": engine_config.skill_level,
            "Contempt": engine_config.contempt,
        }
        syzygy_path = str(self.config.get("tablebase.syzygy_path", ""))
        if bool(self.config.get("tablebase.enabled", False)) and syzygy_path:
            options["SyzygyPath"] = syzygy_path
            options["SyzygyProbeDepth"] = 1
        options.update(engine_config.uci_options)
        option_signature = tuple(sorted((key, str(value)) for key, value in options.items()))
        if option_signature != self._configured_options:
            self._engine.configure(options)
            self._configured_options = option_signature
        return self._engine

    def analyze_fen(
        self,
        fen: str,
        force: bool = False,
        realtime: bool = False,
        multipv_override: int | None = None,
    ) -> AnalysisResult:
        with self._lock:
            board = chess.Board(fen)
            engine_config = self.load_config()
            if multipv_override is not None:
                engine_config = replace(engine_config, multipv=max(1, int(multipv_override)))
            elif realtime:
                engine_config = replace(engine_config, multipv=1)
            time_ms = int(self.config.get("analysis.time_ms", 1000))
            cache_key = self._cache_key(board, time_ms, engine_config, realtime=realtime)

            if not force and bool(self.config.get("analysis.cache_enabled", True)) and cache_key in self._cache:
                cached = self._cache[cache_key]
                return AnalysisResult(
                    fen=cached.fen,
                    best_move_uci=cached.best_move_uci,
                    best_move_san=cached.best_move_san,
                    evaluation=cached.evaluation,
                    depth=cached.depth,
                    seldepth=cached.seldepth,
                    nodes=cached.nodes,
                    tbhits=cached.tbhits,
                    hashfull=cached.hashfull,
                    thinking_time_ms=cached.thinking_time_ms,
                    lines=cached.lines,
                    source="cache",
                )

            tablebase_result = self._try_tablebase(board)
            if tablebase_result is not None:
                return tablebase_result

            # A single book entry cannot satisfy a request for several choices.
            # In that mode, let the engine rank all candidates consistently.
            book_result = None if engine_config.multipv > 1 else self._try_opening_book(board)
            if book_result is not None:
                if book_result.source == "engine_book_check":
                    self._cache[cache_key] = book_result
                return book_result

            # The realtime tracker is itself the retry loop. Restarting a timed
            # out engine here delays observation of the opponent's next move.
            attempts = 1 if realtime else 2
            for attempt in range(attempts):
                started = time.perf_counter()
                try:
                    if bool(self.config.get("analysis.adaptive_time_enabled", False)):
                        info_lines, elapsed_ms = self._adaptive_analyze(board, engine_config, realtime=realtime)
                    else:
                        if realtime:
                            time_ms = min(
                                time_ms,
                                self._clamp_int("analysis.adaptive_realtime_max_time_ms", 4200, 500, 60_000),
                            )
                        engine = self._ensure_engine(engine_config)
                        info_lines = engine.analyze(board, time_ms=time_ms, multipv=engine_config.multipv)
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                    result = self._build_result(board, info_lines, elapsed_ms)
                    self._cache[cache_key] = result
                    return result
                except Exception:
                    self._close_engine()
                    if attempt + 1 < attempts:
                        continue
                    raise

            raise RuntimeError("Stockfish không trả về kết quả phân tích.")

    def _adaptive_analyze(
        self,
        board: chess.Board,
        engine_config: EngineConfig,
        realtime: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        min_ms = self._clamp_int("analysis.adaptive_min_time_ms", 700, 100, 60_000)
        max_ms = self._clamp_int("analysis.adaptive_max_time_ms", 6000, min_ms, 120_000)
        if realtime:
            realtime_max = self._clamp_int("analysis.adaptive_realtime_max_time_ms", 4200, min_ms, max_ms)
            max_ms = min(max_ms, realtime_max)
        probe_ms = self._clamp_int("analysis.adaptive_probe_time_ms", 300, 100, max_ms)
        if realtime:
            probe_ms = min(probe_ms, 350)
        legal_moves = board.legal_moves.count()
        if legal_moves <= 1:
            started = time.perf_counter()
            engine = self._ensure_engine(engine_config)
            lines = engine.analyze(board, time_ms=min_ms, multipv=1)
            return lines, int((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        probe_multipv = 1 if realtime else min(max(engine_config.multipv, 3), legal_moves)
        probe_config = replace(engine_config, multipv=probe_multipv)
        engine = self._ensure_engine(probe_config)
        probe_lines = engine.analyze(board, time_ms=probe_ms, multipv=probe_multipv)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        target_ms = self._adaptive_target_ms(board, probe_lines, min_ms, max_ms)
        if target_ms <= elapsed_ms + 150:
            return probe_lines[: max(engine_config.multipv, 1)], elapsed_ms

        remaining_ms = max(target_ms - elapsed_ms, 150)
        engine = self._ensure_engine(engine_config)
        final_lines = engine.analyze(board, time_ms=remaining_ms, multipv=engine_config.multipv)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return final_lines or probe_lines[: max(engine_config.multipv, 1)], elapsed_ms

    def _adaptive_target_ms(
        self,
        board: chess.Board,
        probe_lines: list[dict[str, Any]],
        min_ms: int,
        max_ms: int,
    ) -> int:
        difficulty = 0
        legal_count = board.legal_moves.count()
        capture_count = self._capture_count(board)
        piece_count = len(board.piece_map())
        tactical_pressure = board.is_check() or capture_count >= 4

        if piece_count <= 7:
            difficulty -= 2
        if board.fullmove_number <= 10 and not tactical_pressure:
            difficulty -= 1
        if board.is_check():
            difficulty += 3
        if capture_count >= 8:
            difficulty += 3
        elif capture_count >= 4:
            difficulty += 2
        if legal_count >= 45:
            difficulty += 1
        if tactical_pressure and board.queens:
            difficulty += 1

        best_score = self._score_cp(probe_lines, 0)
        second_score = self._score_cp(probe_lines, 1)
        if best_score is not None and abs(best_score) >= 90_000:
            difficulty -= 2
        elif best_score is not None and second_score is not None:
            gap = best_score - second_score
            if gap >= 250:
                difficulty -= 2
            elif gap >= 120:
                difficulty -= 1
            elif gap <= 35:
                difficulty += 3 if tactical_pressure else -1
            elif gap <= 80:
                difficulty += 2 if tactical_pressure else 0

        if difficulty <= 0:
            ratio = 0.0
        elif difficulty == 1:
            ratio = 0.18
        elif difficulty == 2:
            ratio = 0.35
        elif difficulty <= 4:
            ratio = 0.60
        else:
            ratio = 1.0
        return int(min_ms + (max_ms - min_ms) * ratio)

    @staticmethod
    def _capture_count(board: chess.Board) -> int:
        return sum(1 for move in board.legal_moves if board.is_capture(move))

    @staticmethod
    def _score_cp(lines: list[dict[str, Any]], index: int) -> int | None:
        if index >= len(lines):
            return None
        value = lines[index].get("score_cp")
        return int(value) if value is not None else None

    def _clamp_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        value = int(self.config.get(key, default))
        return max(minimum, min(value, maximum))

    def _build_result(
        self,
        board: chess.Board,
        info_lines: list[dict[str, Any]],
        elapsed_ms: int,
    ) -> AnalysisResult:
        lines: list[EngineLine] = []

        for info in info_lines:
            pv_uci = info.get("pv_uci") or []
            pv = [chess.Move.from_uci(move_uci) for move_uci in pv_uci]
            if not pv:
                continue
            move = pv[0]
            lines.append(
                EngineLine(
                    move_uci=move.uci(),
                    move_san=board.san(move),
                    score=str(info.get("score_text", "không có")),
                    depth=info.get("depth"),
                    seldepth=info.get("seldepth"),
                    nodes=info.get("nodes"),
                    tbhits=info.get("tbhits"),
                    hashfull=info.get("hashfull"),
                    pv=[m.uci() for m in pv],
                    score_cp=info.get("score_cp"),
                )
            )

        if not lines:
            raise RuntimeError("Stockfish không trả về biến phân tích nào.")

        best = lines[0]
        return AnalysisResult(
            fen=board.fen(),
            best_move_uci=best.move_uci,
            best_move_san=best.move_san,
            evaluation=best.score,
            depth=best.depth,
            seldepth=best.seldepth,
            nodes=best.nodes,
            tbhits=best.tbhits,
            hashfull=best.hashfull,
            thinking_time_ms=elapsed_ms,
            lines=lines,
        )

    def _try_opening_book(self, board: chess.Board) -> AnalysisResult | None:
        self._opening_manager.configure(
            enabled=bool(self.config.get("book.enabled", False)),
            path=str(self.config.get("book.path", "")),
            prefer_book=bool(self.config.get("book.prefer_book", True)),
        )
        if not self._opening_manager.prefer_book:
            return None
        moves = self._opening_manager.find_moves(board)
        if not moves:
            return None
        move = moves[0]
        if bool(self.config.get("book.verify_with_engine", True)):
            verified = self._verify_book_move(board, move)
            if verified is not None:
                return verified
        line = EngineLine(
            move_uci=move.uci(),
            move_san=board.san(move),
            score="sách khai cuộc",
            depth=None,
            seldepth=None,
            nodes=None,
            tbhits=None,
            hashfull=None,
            pv=[move.uci()],
        )
        return AnalysisResult(
            fen=board.fen(),
            best_move_uci=line.move_uci,
            best_move_san=line.move_san,
            evaluation="sách khai cuộc",
            depth=None,
            seldepth=None,
            nodes=None,
            tbhits=None,
            hashfull=None,
            thinking_time_ms=0,
            lines=[line],
            source="book",
        )

    def _try_tablebase(self, board: chess.Board) -> AnalysisResult | None:
        max_pieces = int(self.config.get("tablebase.max_pieces", 5))
        if len(board.piece_map()) > max_pieces:
            return None
        manager = SyzygyManager(
            enabled=bool(self.config.get("tablebase.enabled", False)),
            path=str(self.config.get("tablebase.syzygy_path", "")),
            max_pieces=max_pieces,
        )
        move, score = manager.best_move(board)
        if move is None:
            return None
        line = EngineLine(
            move_uci=move.uci(),
            move_san=board.san(move),
            score=score,
            depth=None,
            seldepth=None,
            nodes=None,
            tbhits=1,
            hashfull=None,
            pv=[move.uci()],
        )
        return AnalysisResult(
            fen=board.fen(),
            best_move_uci=line.move_uci,
            best_move_san=line.move_san,
            evaluation=score,
            depth=None,
            seldepth=None,
            nodes=None,
            tbhits=1,
            hashfull=None,
            thinking_time_ms=0,
            lines=[line],
            source="tablebase",
        )

    @staticmethod
    def _format_score(score: Any) -> str:
        if score is None:
            return "không có"
        pov = score.white()
        mate = pov.mate()
        if mate is not None:
            return f"Mate {mate}"
        cp = pov.score()
        if cp is None:
            return "không có"
        return f"{cp / 100:+.2f}"

    def clear_cache(self) -> None:
        self._cache.clear()

    def new_game(self) -> None:
        with self._lock:
            self.clear_cache()
            if self._engine is not None:
                try:
                    self._engine.new_game()
                except Exception:
                    self._close_engine()

    def close(self) -> None:
        self._close_engine()
        self._opening_manager.close()

    def close_engine(self) -> None:
        self._close_engine()

    def cancel_analysis(self) -> None:
        """Interrupt the current UCI search without waiting for the manager lock."""
        engine = self._engine
        if engine is not None:
            engine.stop()

    def refresh_opening_book(self) -> None:
        with self._lock:
            self._opening_manager.configure(
                enabled=bool(self.config.get("book.enabled", False)),
                path=str(self.config.get("book.path", "")),
                prefer_book=bool(self.config.get("book.prefer_book", True)),
            )

    def _close_engine(self) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None
        self._configured_options = None

    def _cache_key(
        self,
        board: chess.Board,
        time_ms: int,
        engine_config: EngineConfig,
        realtime: bool = False,
    ) -> tuple[Any, ...]:
        return (
            board.fen(),
            time_ms,
            engine_config.path,
            engine_config.threads,
            engine_config.hash_mb,
            engine_config.ponder,
            engine_config.multipv,
            engine_config.skill_level,
            engine_config.contempt,
            tuple(sorted((key, str(value)) for key, value in engine_config.uci_options.items())),
            bool(self.config.get("book.enabled", False)),
            str(self.config.get("book.path", "")),
            bool(self.config.get("book.prefer_book", True)),
            bool(self.config.get("book.verify_with_engine", True)),
            int(self.config.get("book.max_eval_loss_cp", 10)),
            int(self.config.get("book.verify_time_ms", 500)),
            bool(self.config.get("analysis.adaptive_time_enabled", False)),
            int(self.config.get("analysis.adaptive_min_time_ms", 500)),
            int(self.config.get("analysis.adaptive_max_time_ms", 10000)),
            int(self.config.get("analysis.adaptive_probe_time_ms", 500)),
            int(self.config.get("analysis.adaptive_realtime_max_time_ms", 4200)),
            realtime,
            bool(self.config.get("tablebase.enabled", False)),
            str(self.config.get("tablebase.syzygy_path", "")),
            int(self.config.get("tablebase.max_pieces", 5)),
        )

    def _verify_book_move(self, board: chess.Board, book_move: chess.Move) -> AnalysisResult | None:
        engine_config = self.load_config()
        engine = self._ensure_engine(engine_config)
        verify_time_ms = int(self.config.get("book.verify_time_ms", 500))
        unrestricted = engine.analyze(board, time_ms=verify_time_ms, multipv=1)
        if not unrestricted:
            return None
        engine_best = unrestricted[0]
        engine_pv = engine_best.get("pv_uci") or []
        if engine_pv and engine_pv[0] == book_move.uci():
            return None

        restricted = engine.analyze(
            board,
            time_ms=verify_time_ms,
            multipv=1,
            root_moves=[book_move],
        )
        if not restricted:
            return self._analyze_after_book_rejection(board, engine, engine_config)

        best_score = engine_best.get("score_cp")
        book_score = restricted[0].get("score_cp")
        max_loss = int(self.config.get("book.max_eval_loss_cp", 10))
        if best_score is None or book_score is None or best_score - book_score <= max_loss:
            return None
        return self._analyze_after_book_rejection(board, engine, engine_config)

    def _analyze_after_book_rejection(
        self,
        board: chess.Board,
        engine: StockfishEngine,
        engine_config: EngineConfig,
    ) -> AnalysisResult:
        time_ms = int(self.config.get("analysis.time_ms", 1000))
        started = time.perf_counter()
        if bool(self.config.get("analysis.adaptive_time_enabled", False)):
            info_lines, elapsed_ms = self._adaptive_analyze(board, engine_config)
        else:
            info_lines = engine.analyze(board, time_ms=time_ms, multipv=engine_config.multipv)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
        result = self._build_result(board, info_lines, elapsed_ms)
        return AnalysisResult(
            fen=result.fen,
            best_move_uci=result.best_move_uci,
            best_move_san=result.best_move_san,
            evaluation=result.evaluation,
            depth=result.depth,
            seldepth=result.seldepth,
            nodes=result.nodes,
            tbhits=result.tbhits,
            hashfull=result.hashfull,
            thinking_time_ms=result.thinking_time_ms,
            lines=result.lines,
            source="engine_book_check",
        )
