from __future__ import annotations

from pathlib import Path

import chess
import chess.syzygy


class SyzygyManager:
    def __init__(self, enabled: bool = False, path: str = "", max_pieces: int = 5) -> None:
        self.enabled = enabled
        self.path = path
        self.max_pieces = max_pieces

    def probe_wdl(self, board: chess.Board) -> int | None:
        if not self.enabled or not self.path or not Path(self.path).exists():
            return None
        with chess.syzygy.open_tablebase(self.path) as tablebase:
            return tablebase.probe_wdl(board)

    def best_move(self, board: chess.Board) -> tuple[chess.Move | None, str]:
        if not self.enabled or not self.path or not Path(self.path).exists():
            return None, ""
        if len(board.piece_map()) > self.max_pieces:
            return None, ""

        best_move: chess.Move | None = None
        best_key: tuple[int, int] | None = None
        with chess.syzygy.open_tablebase(self.path) as tablebase:
            for move in board.legal_moves:
                board.push(move)
                try:
                    wdl_after = tablebase.probe_wdl(board)
                    dtz_after = tablebase.probe_dtz(board)
                except chess.syzygy.MissingTableError:
                    board.pop()
                    continue
                board.pop()

                wdl_for_us = -wdl_after
                if wdl_for_us > 0:
                    dtz_key = -abs(dtz_after)
                elif wdl_for_us < 0:
                    dtz_key = abs(dtz_after)
                else:
                    dtz_key = 0
                key = (wdl_for_us, dtz_key)
                if best_key is None or key > best_key:
                    best_key = key
                    best_move = move

        if best_move is None or best_key is None:
            return None, ""
        score = self._format_wdl(best_key[0])
        return best_move, score

    @staticmethod
    def _format_wdl(wdl: int) -> str:
        if wdl > 0:
            return "tàn cuộc thắng"
        if wdl < 0:
            return "tàn cuộc thua"
        return "tàn cuộc hòa"
