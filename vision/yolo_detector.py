from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    xyxy: tuple[float, float, float, float]


class YoloDetector:
    def __init__(self, model_path: str, confidence_threshold: float) -> None:
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        model_path = Path(self.model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy mô hình YOLO: {model_path}. "
                "Hãy vào Cài đặt → Nhận diện và chọn tệp mô hình .pt nhận diện quân cờ."
            )
        from ultralytics import YOLO

        self._model = YOLO(str(model_path))

    def detect(self, board_image: np.ndarray) -> list[Detection]:
        self.load()
        assert self._model is not None
        results = self._model.predict(board_image, conf=self.confidence_threshold, verbose=False)
        detections: list[Detection] = []
        names = results[0].names

        for box in results[0].boxes:
            cls_id = int(box.cls[0].item())
            confidence = float(box.conf[0].item())
            xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
            detections.append(Detection(label=str(names[cls_id]), confidence=confidence, xyxy=xyxy))
        return detections
