from __future__ import annotations

import chess
import chess.polyglot


class OpeningManager:
    def __init__(self, enabled: bool = False, path: str = "", prefer_book: bool = True) -> None:
        self.enabled = enabled
        self.path = path
        self.prefer_book = prefer_book

    def find_moves(self, board: chess.Board, limit: int = 8) -> list[chess.Move]:
        if not self.enabled or not self.path:
            return []
        try:
            with chess.polyglot.open_reader(self.path) as reader:
                entries = sorted(reader.find_all(board), key=lambda item: item.weight, reverse=True)
                return [entry.move for entry in entries[: max(1, limit)]]
        except (FileNotFoundError, IndexError, ValueError):
            return []

    def find_move(self, board: chess.Board) -> chess.Move | None:
        moves = self.find_moves(board, limit=1)
        return moves[0] if moves else None
