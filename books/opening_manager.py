from __future__ import annotations

import logging
import struct

import chess
import chess.polyglot


logger = logging.getLogger(__name__)


class OpeningManager:
    def __init__(self, enabled: bool = False, path: str = "", prefer_book: bool = True) -> None:
        self.enabled = enabled
        self.path = path
        self.prefer_book = prefer_book
        self._reader: chess.polyglot.MemoryMappedReader | None = None
        self._reader_path = ""
        self._failed_path = ""

    def configure(self, enabled: bool, path: str, prefer_book: bool) -> None:
        path = str(path)
        resource_changed = path != self.path or enabled != self.enabled
        if resource_changed:
            self.close()
            self._failed_path = ""
        self.enabled = enabled
        self.path = path
        self.prefer_book = prefer_book
        if not enabled or not path:
            self.close()

    def find_moves(self, board: chess.Board, limit: int = 8) -> list[chess.Move]:
        if not self.enabled or not self.path:
            return []
        reader = self._ensure_reader()
        if reader is None:
            return []
        try:
            entries = sorted(reader.find_all(board), key=lambda item: item.weight, reverse=True)
            return [entry.move for entry in entries[: max(1, limit)]]
        except (OSError, IndexError, ValueError, struct.error) as exc:
            self._mark_failed(exc)
            return []

    def find_move(self, board: chess.Board) -> chess.Move | None:
        moves = self.find_moves(board, limit=1)
        return moves[0] if moves else None

    def close(self) -> None:
        if self._reader is not None:
            try:
                self._reader.close()
            except (OSError, ValueError):
                pass
        self._reader = None
        self._reader_path = ""

    def _ensure_reader(self) -> chess.polyglot.MemoryMappedReader | None:
        if self._reader is not None and self._reader_path == self.path:
            return self._reader
        if self._failed_path == self.path:
            return None
        try:
            self._reader = chess.polyglot.open_reader(self.path)
            self._reader_path = self.path
            return self._reader
        except (OSError, IndexError, ValueError, struct.error) as exc:
            self._mark_failed(exc)
            return None

    def _mark_failed(self, exc: Exception) -> None:
        self.close()
        if self._failed_path != self.path:
            logger.warning("Không thể sử dụng Opening Book '%s': %s", self.path, exc)
        self._failed_path = self.path
