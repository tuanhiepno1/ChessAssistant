from __future__ import annotations

from dataclasses import dataclass

import chess
import cv2
import numpy as np

from chess_tools.fen_builder import SquarePiece


START_LABELS = {
    chess.A1: "white_rook",
    chess.B1: "white_knight",
    chess.C1: "white_bishop",
    chess.D1: "white_queen",
    chess.E1: "white_king",
    chess.F1: "white_bishop",
    chess.G1: "white_knight",
    chess.H1: "white_rook",
    chess.A8: "black_rook",
    chess.B8: "black_knight",
    chess.C8: "black_bishop",
    chess.D8: "black_queen",
    chess.E8: "black_king",
    chess.F8: "black_bishop",
    chess.G8: "black_knight",
    chess.H8: "black_rook",
    **{square: "white_pawn" for square in chess.SquareSet(chess.BB_RANK_2)},
    **{square: "black_pawn" for square in chess.SquareSet(chess.BB_RANK_7)},
}


@dataclass(frozen=True)
class TemplateRecognition:
    pieces: list[SquarePiece]
    initialized: bool
    confidence: float
    status: str


class TemplatePieceRecognizer:
    def __init__(self) -> None:
        self._templates: dict[str, list[np.ndarray]] = {}
        self._empty_templates: list[np.ndarray] = []
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    def reset(self) -> None:
        self._templates = {}
        self._empty_templates = []
        self._initialized = False

    def recognize(self, board_image: np.ndarray, perspective: str) -> TemplateRecognition:
        samples = self._samples(board_image, perspective)
        if not self._initialized:
            self._initialize(samples)
            return TemplateRecognition(
                pieces=[SquarePiece(square_index=square, label=label) for square, label in START_LABELS.items()],
                initialized=True,
                confidence=1.0,
                status="Đã tạo mẫu nhận diện từ thế xuất phát.",
            )

        pieces: list[SquarePiece] = []
        scores: list[float] = []
        for square, sample in samples.items():
            empty_score = self._best_score(sample, self._empty_templates)
            label, piece_score = self._best_piece(sample)
            if label is None:
                continue
            if piece_score > max(0.34, empty_score + 0.07):
                pieces.append(SquarePiece(square_index=square, label=label))
                scores.append(piece_score)

        confidence = float(np.mean(scores)) if scores else 0.0
        return TemplateRecognition(
            pieces=pieces,
            initialized=True,
            confidence=confidence,
            status=f"Mẫu nhận diện được {len(pieces)} quân, độ tin cậy {confidence:.2f}.",
        )

    def _initialize(self, samples: dict[int, np.ndarray]) -> None:
        self._templates = {}
        self._empty_templates = []
        for square, sample in samples.items():
            label = START_LABELS.get(square)
            if label is None:
                self._empty_templates.append(sample)
            else:
                self._templates.setdefault(label, []).append(sample)
        self._initialized = True

    def _best_piece(self, sample: np.ndarray) -> tuple[str | None, float]:
        best_label: str | None = None
        best_score = -1.0
        for label, templates in self._templates.items():
            score = self._best_score(sample, templates)
            if score > best_score:
                best_label = label
                best_score = score
        return best_label, best_score

    @staticmethod
    def _best_score(sample: np.ndarray, templates: list[np.ndarray]) -> float:
        if not templates:
            return -1.0
        return max(TemplatePieceRecognizer._score(sample, template) for template in templates)

    @staticmethod
    def _score(sample: np.ndarray, template: np.ndarray) -> float:
        result = cv2.matchTemplate(sample, template, cv2.TM_CCOEFF_NORMED)
        value = float(result[0][0])
        if np.isnan(value):
            return -1.0
        return value

    @staticmethod
    def _samples(board_image: np.ndarray, perspective: str) -> dict[int, np.ndarray]:
        side = min(board_image.shape[:2])
        square_size = side / 8.0
        samples: dict[int, np.ndarray] = {}
        for row in range(8):
            for col in range(8):
                x1 = int(round(col * square_size + square_size * 0.06))
                y1 = int(round(row * square_size + square_size * 0.06))
                x2 = int(round((col + 1) * square_size - square_size * 0.06))
                y2 = int(round((row + 1) * square_size - square_size * 0.06))
                patch = board_image[y1:y2, x1:x2]
                sample = TemplatePieceRecognizer._preprocess(patch)
                if perspective == "black":
                    square = chess.square(7 - col, row)
                else:
                    square = chess.square(col, 7 - row)
                samples[square] = sample
        return samples

    @staticmethod
    def _preprocess(patch: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
        gray = cv2.resize(gray, (48, 48), interpolation=cv2.INTER_AREA)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blurred, 35, 95)
        return edges.astype(np.uint8)
