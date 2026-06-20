from __future__ import annotations

from chess_tools.fen_builder import SquarePiece
from vision.yolo_detector import Detection


class PieceMapper:
    def map_to_squares(
        self,
        detections: list[Detection],
        board_size: int,
        perspective: str = "white",
    ) -> list[SquarePiece]:
        square_size = board_size / 8.0
        mapped: list[SquarePiece] = []

        for detection in detections:
            x1, y1, x2, y2 = detection.xyxy
            center_x = (x1 + x2) / 2.0
            center_y = (y1 + y2) / 2.0
            file_idx = min(7, max(0, int(center_x / square_size)))
            rank_idx = min(7, max(0, int(center_y / square_size)))

            if perspective == "black":
                square = rank_idx * 8 + (7 - file_idx)
            else:
                square = (7 - rank_idx) * 8 + file_idx

            mapped.append(SquarePiece(square_index=square, label=detection.label))
        return mapped

