from __future__ import annotations

from dataclasses import dataclass

import chess
import cv2
import numpy as np


@dataclass(frozen=True)
class TrackerUpdate:
    fen: str
    player_to_move: bool
    changed_squares: int
    applied_move: str | None
    status: str


class VisualBoardTracker:
    def __init__(self) -> None:
        self.board = chess.Board()
        self._previous_samples: dict[int, np.ndarray] = {}
        self._initialized = False

    def reset(self) -> None:
        self.board = chess.Board()
        self._previous_samples = {}
        self._initialized = False

    def process(
        self,
        board_image: np.ndarray,
        perspective: str,
        player_color: chess.Color,
    ) -> TrackerUpdate:
        samples = self._sample_squares(board_image, perspective)
        if not self._initialized:
            self._previous_samples = samples
            self._initialized = True
            return TrackerUpdate(
                fen=self.board.fen(),
                player_to_move=self.board.turn == player_color,
                changed_squares=0,
                applied_move=None,
                status="Đã khởi tạo từ thế cờ ban đầu.",
            )

        diffs = {
            square: float(np.mean(cv2.absdiff(samples[square], self._previous_samples[square])))
            for square in chess.SQUARES
        }
        changed = {square for square, diff in diffs.items() if diff >= 9.0}
        if len(changed) < 2:
            self._previous_samples = samples
            return TrackerUpdate(
                fen=self.board.fen(),
                player_to_move=self.board.turn == player_color,
                changed_squares=len(changed),
                applied_move=None,
                status="Chưa thấy nước đi mới.",
            )

        move = self._best_legal_move(changed, diffs)
        self._previous_samples = samples
        if move is None:
            return TrackerUpdate(
                fen=self.board.fen(),
                player_to_move=self.board.turn == player_color,
                changed_squares=len(changed),
                applied_move=None,
                status="Có thay đổi trên bàn cờ nhưng chưa khớp với nước hợp lệ.",
            )

        self.board.push(move)
        return TrackerUpdate(
            fen=self.board.fen(),
            player_to_move=self.board.turn == player_color,
            changed_squares=len(changed),
            applied_move=move.uci(),
            status=f"Đã nhận diện nước đi: {move.uci()}",
        )

    def _best_legal_move(self, changed: set[int], diffs: dict[int, float]) -> chess.Move | None:
        scored: list[tuple[float, chess.Move]] = []
        for move in self.board.legal_moves:
            expected = {move.from_square, move.to_square}
            if self.board.is_castling(move):
                if chess.square_file(move.to_square) > chess.square_file(move.from_square):
                    expected.update({chess.H1 if self.board.turn else chess.H8, chess.F1 if self.board.turn else chess.F8})
                else:
                    expected.update({chess.A1 if self.board.turn else chess.A8, chess.D1 if self.board.turn else chess.D8})
            overlap = expected & changed
            if len(overlap) < 2:
                continue
            score = sum(diffs[square] for square in expected)
            score += 2.0 * len(overlap)
            scored.append((score, move))

        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _sample_squares(board_image: np.ndarray, perspective: str) -> dict[int, np.ndarray]:
        side = min(board_image.shape[:2])
        square_size = side / 8.0
        samples: dict[int, np.ndarray] = {}
        for row in range(8):
            for col in range(8):
                x1 = int(round(col * square_size + square_size * 0.14))
                y1 = int(round(row * square_size + square_size * 0.14))
                x2 = int(round((col + 1) * square_size - square_size * 0.14))
                y2 = int(round((row + 1) * square_size - square_size * 0.14))
                patch = board_image[y1:y2, x1:x2]
                sample = cv2.resize(patch, (24, 24), interpolation=cv2.INTER_AREA)
                if perspective == "black":
                    square = chess.square(7 - col, row)
                else:
                    square = chess.square(col, 7 - row)
                samples[square] = sample
        return samples
