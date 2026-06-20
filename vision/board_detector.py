from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class BoardBox:
    x: int
    y: int
    size: int

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "size": self.size}

    @classmethod
    def from_config(cls, value: Any) -> "BoardBox | None":
        if not isinstance(value, dict):
            return None
        try:
            x = int(value["x"])
            y = int(value["y"])
            size = int(value["size"])
        except (KeyError, TypeError, ValueError):
            return None
        if size <= 0:
            return None
        return cls(x=x, y=y, size=size)


class BoardDetector:
    def __init__(self, calibrated_box: BoardBox | None = None) -> None:
        self.calibrated_box = calibrated_box

    def detect(self, screenshot: np.ndarray) -> BoardBox | None:
        height, width = screenshot.shape[:2]
        if self.calibrated_box is None:
            return self._detect_chessboard_square(screenshot, width=width, height=height)
        return self._clamp(self.calibrated_box, width=width, height=height)

    def crop(self, screenshot: np.ndarray, box: BoardBox) -> np.ndarray:
        return screenshot[box.y : box.y + box.size, box.x : box.x + box.size]

    @staticmethod
    def _clamp(box: BoardBox, width: int, height: int) -> BoardBox | None:
        if width <= 0 or height <= 0:
            return None
        max_size = min(width, height)
        size = min(max(box.size, 1), max_size)
        x = min(max(box.x, 0), max(width - size, 0))
        y = min(max(box.y, 0), max(height - size, 0))
        return BoardBox(x=x, y=y, size=size)

    @staticmethod
    def _detect_chessboard_square(screenshot: np.ndarray, width: int, height: int) -> BoardBox | None:
        if width <= 0 or height <= 0:
            return None

        max_side = min(width, height)
        scale = 1.0
        working = screenshot
        if max_side > 1200:
            scale = 1200 / max_side
            working = cv2.resize(screenshot, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        candidates = BoardDetector._contour_candidates(working, scale)
        candidates.extend(BoardDetector._grid_scan_candidates(working, scale))
        candidates = [BoardDetector._clamp(candidate, width=width, height=height) for candidate in candidates]
        candidates = [candidate for candidate in candidates if candidate is not None]
        if not candidates:
            return None

        best = max(candidates, key=lambda box: BoardDetector._board_score(screenshot, box))
        if BoardDetector._board_score(screenshot, best) < 0.22:
            return None
        return best

    @staticmethod
    def _contour_candidates(image: np.ndarray, scale: float) -> list[BoardBox]:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 130)
        kernel = np.ones((5, 5), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates: list[BoardBox] = []
        image_area = image.shape[0] * image.shape[1]
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h < image_area * 0.025:
                continue
            ratio = w / max(h, 1)
            if not 0.82 <= ratio <= 1.22:
                continue
            side = min(w, h)
            if side < 180 * scale:
                continue
            source_x = int(round(x / scale))
            source_y = int(round(y / scale))
            source_side = int(round(side / scale))
            candidates.append(BoardBox(source_x, source_y, source_side))
        return candidates

    @staticmethod
    def _grid_scan_candidates(image: np.ndarray, scale: float) -> list[BoardBox]:
        height, width = image.shape[:2]
        max_side = min(width, height)
        min_side = max(180, int(max_side * 0.22))
        step = max(24, int(max_side * 0.035))
        side_step = max(32, int(max_side * 0.045))

        candidates: list[BoardBox] = []
        for side in range(max_side, min_side - 1, -side_step):
            y_step = max(step, side // 6)
            x_step = max(step, side // 6)
            best_for_side: tuple[float, BoardBox] | None = None
            for y in range(0, max(height - side + 1, 1), y_step):
                for x in range(0, max(width - side + 1, 1), x_step):
                    source_box = BoardBox(
                        int(round(x / scale)),
                        int(round(y / scale)),
                        int(round(side / scale)),
                    )
                    source_image = image
                    score = BoardDetector._board_score_scaled(source_image, BoardBox(x, y, side))
                    if best_for_side is None or score > best_for_side[0]:
                        best_for_side = (score, source_box)
            if best_for_side is not None and best_for_side[0] >= 0.32:
                candidates.append(best_for_side[1])
                break
        return candidates

    @staticmethod
    def _board_score(image: np.ndarray, box: BoardBox) -> float:
        crop = image[box.y : box.y + box.size, box.x : box.x + box.size]
        return BoardDetector._board_score_image(crop)

    @staticmethod
    def _board_score_scaled(image: np.ndarray, box: BoardBox) -> float:
        crop = image[box.y : box.y + box.size, box.x : box.x + box.size]
        return BoardDetector._board_score_image(crop)

    @staticmethod
    def _board_score_image(crop: np.ndarray) -> float:
        if crop.size == 0:
            return 0.0
        side = min(crop.shape[:2])
        if side < 96:
            return 0.0
        sample = cv2.resize(crop[:side, :side], (80, 80), interpolation=cv2.INTER_AREA)
        lab = cv2.cvtColor(sample, cv2.COLOR_RGB2LAB).astype(np.float32)
        square = 10
        means = np.zeros((8, 8, 3), dtype=np.float32)
        for row in range(8):
            for col in range(8):
                patch = lab[row * square : (row + 1) * square, col * square : (col + 1) * square]
                center_patch = patch[2:8, 2:8]
                means[row, col] = center_patch.reshape(-1, 3).mean(axis=0)

        same_color_diffs: list[float] = []
        opposite_color_diffs: list[float] = []
        for row in range(8):
            for col in range(8):
                if col < 7:
                    diff = float(np.linalg.norm(means[row, col] - means[row, col + 1]))
                    opposite_color_diffs.append(diff)
                if row < 7:
                    diff = float(np.linalg.norm(means[row, col] - means[row + 1, col]))
                    opposite_color_diffs.append(diff)
                if row < 6:
                    diff = float(np.linalg.norm(means[row, col] - means[row + 2, col]))
                    same_color_diffs.append(diff)
                if col < 6:
                    diff = float(np.linalg.norm(means[row, col] - means[row, col + 2]))
                    same_color_diffs.append(diff)

        opposite = float(np.median(opposite_color_diffs)) if opposite_color_diffs else 0.0
        same = float(np.median(same_color_diffs)) if same_color_diffs else 999.0
        contrast_score = min(opposite / 42.0, 1.0)
        consistency_score = 1.0 - min(same / max(opposite, 1.0), 1.0)
        return max(0.0, contrast_score * 0.65 + consistency_score * 0.35)
