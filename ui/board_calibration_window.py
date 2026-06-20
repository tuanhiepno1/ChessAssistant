from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRubberBand,
    QVBoxLayout,
)

import numpy as np

from vision.board_detector import BoardBox


def rgb_array_to_pixmap(image: np.ndarray) -> QPixmap:
    height, width, channels = image.shape
    if channels != 3:
        raise ValueError("Ảnh chụp không đúng định dạng RGB 3 kênh.")
    contiguous = np.ascontiguousarray(image)
    qimage = QImage(
        contiguous.data,
        width,
        height,
        width * channels,
        QImage.Format.Format_RGB888,
    ).copy()
    return QPixmap.fromImage(qimage)


class CalibrationImageLabel(QLabel):
    def __init__(self, pixmap: QPixmap) -> None:
        super().__init__()
        self._source_pixmap = pixmap
        self._selection_origin = QPoint()
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._selected_box: BoardBox | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(QSize(800, 520))
        self.setMouseTracking(True)
        self._refresh_pixmap()

    @property
    def selected_box(self) -> BoardBox | None:
        return self._selected_box

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._refresh_pixmap()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._selection_origin = event.position().toPoint()
        self._rubber_band.setGeometry(QRect(self._selection_origin, QSize()))
        self._rubber_band.show()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._rubber_band.isVisible():
            return
        rect = QRect(self._selection_origin, event.position().toPoint()).normalized()
        side = min(rect.width(), rect.height())
        rect.setSize(QSize(side, side))
        self._rubber_band.setGeometry(rect)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        rect = self._rubber_band.geometry().normalized()
        self._selected_box = self._label_rect_to_board_box(rect)

    def _refresh_pixmap(self) -> None:
        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def _label_rect_to_board_box(self, rect: QRect) -> BoardBox | None:
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull() or rect.width() < 16 or rect.height() < 16:
            return None

        offset_x = (self.width() - pixmap.width()) / 2.0
        offset_y = (self.height() - pixmap.height()) / 2.0
        x = max(rect.x() - offset_x, 0.0)
        y = max(rect.y() - offset_y, 0.0)
        scale_x = self._source_pixmap.width() / pixmap.width()
        scale_y = self._source_pixmap.height() / pixmap.height()
        size = min(rect.width() * scale_x, rect.height() * scale_y)
        source_x = int(round(x * scale_x))
        source_y = int(round(y * scale_y))
        source_size = int(round(size))
        max_size = min(
            self._source_pixmap.width() - source_x,
            self._source_pixmap.height() - source_y,
        )
        source_size = max(1, min(source_size, max_size))
        return BoardBox(x=source_x, y=source_y, size=source_size)


class BoardCalibrationWindow(QDialog):
    def __init__(self, screenshot: np.ndarray, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Chọn vùng bàn cờ")
        self.resize(980, 720)
        layout = QVBoxLayout(self)

        self.image_label = CalibrationImageLabel(rgb_array_to_pixmap(screenshot))
        layout.addWidget(self.image_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Lưu")
        buttons.button(QDialogButtonBox.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_box(self) -> BoardBox | None:
        return self.image_label.selected_box
