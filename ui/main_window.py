from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import chess
import numpy as np
from PySide6.QtCore import QObject, QPointF, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.browser_bootstrap import CHESSBASE_URL, CHESSCLUB_URL, CHESS_COM_URL, LICHESS_URL, open_chess_url
from chess_tools.fen_builder import FenBuilder
from chess_tools.position_reconciler import PositionReconciler
from core.config_manager import ConfigManager
from engine.engine_manager import EngineManager
from engine.stockfish import AnalysisResult
from ui.board_calibration_window import BoardCalibrationWindow
from ui.settings_window import SettingsWindow
from vision.board_detector import BoardBox, BoardDetector
from vision.dom_board_reader import DomBoardReader, DomReadError, DomUnavailableError
from vision.piece_mapper import PieceMapper
from vision.screen_capture import ScreenCapture
from vision.template_piece_recognizer import TemplatePieceRecognizer
from vision.visual_board_tracker import VisualBoardTracker
from vision.yolo_detector import YoloDetector


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


PIECE_GLYPHS = {
    "P": "\u2659",
    "N": "\u2658",
    "B": "\u2657",
    "R": "\u2656",
    "Q": "\u2655",
    "K": "\u2654",
    "p": "\u265f",
    "n": "\u265e",
    "b": "\u265d",
    "r": "\u265c",
    "q": "\u265b",
    "k": "\u265a",
}


class AnalysisBoardWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._fen = START_FEN
        self._best_move_uci = ""
        self._perspective = "white"
        self._board_image: QImage | None = None
        self.setMinimumSize(280, 280)

    def set_position(self, fen: str, best_move_uci: str = "") -> None:
        self._fen = fen
        self._best_move_uci = best_move_uci
        self._board_image = None
        self.update()

    @property
    def best_move_uci(self) -> str:
        return self._best_move_uci

    def set_captured_position(self, fen: str, board_image: object, best_move_uci: str = "") -> None:
        self._fen = fen
        self._best_move_uci = best_move_uci
        self._board_image = self._image_from_array(board_image)
        self.update()

    def set_perspective(self, perspective: str) -> None:
        self._perspective = perspective
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height()) - 12
        if side <= 0:
            return
        left = (self.width() - side) / 2
        top = (self.height() - side) / 2
        square = side / 8

        light = QColor("#f0d9b5")
        dark = QColor("#b58863")
        highlight = QColor(246, 211, 101, 120)

        if self._board_image is not None and not self._board_image.isNull():
            painter.drawImage(int(left), int(top), self._board_image.scaled(
                int(side),
                int(side),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            for row in range(8):
                for col in range(8):
                    painter.fillRect(
                        int(left + col * square),
                        int(top + row * square),
                        math.ceil(square),
                        math.ceil(square),
                        light if (row + col) % 2 == 0 else dark,
                    )

        board = self._safe_board()
        move_squares = self._move_squares()
        if move_squares is not None:
            for sq in move_squares:
                col, row = self._square_to_cell(sq)
                painter.fillRect(
                    int(left + col * square),
                    int(top + row * square),
                    math.ceil(square),
                    math.ceil(square),
                    highlight,
                )

        if self._board_image is None:
            font = QFont("Segoe UI Symbol")
            font.setPixelSize(max(22, int(square * 0.68)))
            painter.setFont(font)
            for sq, piece in board.piece_map().items():
                col, row = self._square_to_cell(sq)
                rect_x = int(left + col * square)
                rect_y = int(top + row * square)
                painter.setPen(QColor("#111827") if piece.color == chess.BLACK else QColor("#f9fafb"))
                painter.drawText(
                    rect_x,
                    rect_y,
                    int(square),
                    int(square),
                    Qt.AlignmentFlag.AlignCenter,
                    PIECE_GLYPHS[piece.symbol()],
                )

        if move_squares is not None:
            from_sq, to_sq = move_squares
            self._draw_arrow(painter, left, top, square, from_sq, to_sq)

    def _safe_board(self) -> chess.Board:
        try:
            return chess.Board(self._fen)
        except ValueError:
            return chess.Board.empty()

    def _move_squares(self) -> tuple[int, int] | None:
        if len(self._best_move_uci) < 4:
            return None
        try:
            return chess.parse_square(self._best_move_uci[:2]), chess.parse_square(self._best_move_uci[2:4])
        except ValueError:
            return None

    def _square_to_cell(self, square: int) -> tuple[int, int]:
        file_idx = chess.square_file(square)
        rank_idx = chess.square_rank(square)
        if self._perspective == "black":
            return 7 - file_idx, rank_idx
        return file_idx, 7 - rank_idx

    def _square_center(self, left: float, top: float, square: float, board_square: int) -> QPointF:
        col, row = self._square_to_cell(board_square)
        return QPointF(left + (col + 0.5) * square, top + (row + 0.5) * square)

    def _draw_arrow(
        self,
        painter: QPainter,
        left: float,
        top: float,
        square: float,
        from_sq: int,
        to_sq: int,
    ) -> None:
        start = self._square_center(left, top, square, from_sq)
        end = self._square_center(left, top, square, to_sq)
        line = end - start
        length = math.hypot(line.x(), line.y())
        if length <= 0:
            return

        unit_x = line.x() / length
        unit_y = line.y() / length
        arrow_end = QPointF(end.x() - unit_x * square * 0.18, end.y() - unit_y * square * 0.18)
        arrow_start = QPointF(start.x() + unit_x * square * 0.18, start.y() + unit_y * square * 0.18)

        pen = QPen(QColor("#16a34a"), max(5, int(square * 0.12)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(arrow_start, arrow_end)

        head_len = square * 0.28
        angle = math.atan2(line.y(), line.x())
        left_head = QPointF(
            arrow_end.x() - head_len * math.cos(angle - math.pi / 6),
            arrow_end.y() - head_len * math.sin(angle - math.pi / 6),
        )
        right_head = QPointF(
            arrow_end.x() - head_len * math.cos(angle + math.pi / 6),
            arrow_end.y() - head_len * math.sin(angle + math.pi / 6),
        )
        painter.setBrush(QColor("#16a34a"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([arrow_end, left_head, right_head]))

    @staticmethod
    def _image_from_array(image: object) -> QImage | None:
        if not hasattr(image, "shape"):
            return None
        contiguous = np.ascontiguousarray(image)
        height, width, channels = contiguous.shape
        if channels != 3:
            return None
        qimage = QImage(
            contiguous.data,
            width,
            height,
            width * channels,
            QImage.Format.Format_RGB888,
        )
        return qimage.copy()


class RealtimeWorker(QObject):
    board_detected = Signal(object, object)
    finished = Signal(object, str, int, object, object, str)
    failed = Signal(str)

    def __init__(
        self,
        config: ConfigManager,
        engine_manager: EngineManager,
        tracker: VisualBoardTracker,
        template_recognizer: TemplatePieceRecognizer,
        side_to_move: chess.Color,
        last_fen: str,
        preferred_site: str = "auto",
        browser_target_id: str = "",
        generation: int = 0,
        has_current_analysis: bool = False,
        force_analysis: bool = False,
    ) -> None:
        super().__init__()
        self.config = config
        self.engine_manager = engine_manager
        self.tracker = tracker
        self.template_recognizer = template_recognizer
        self.side_to_move = side_to_move
        self.last_fen = last_fen
        self.preferred_site = preferred_site
        self.browser_target_id = browser_target_id
        self.generation = generation
        self.has_current_analysis = has_current_analysis
        self.force_analysis = force_analysis

    @Slot()
    def run(self) -> None:
        try:
            try:
                reader = DomBoardReader(
                    preferred_site=self.preferred_site,
                    target_id=self.browser_target_id,
                )
                state = reader.read()
                stability_delay = 0.12 if "lichess.org" in state.url.lower() else 0.08
                time.sleep(stability_delay)
                confirmed_state = reader.read()
                if self._piece_signature(state.pieces) != self._piece_signature(confirmed_state.pieces):
                    fen = self.last_fen or START_FEN
                    self.finished.emit(
                        None,
                        fen,
                        len(confirmed_state.pieces),
                        None,
                        None,
                        "DOM đang chuyển động; chờ hai lần đọc ổn định để tránh bắt nhầm thế cờ.",
                    )
                    return
                state = confirmed_state
                # DomBoardReader has already combined clock position with the
                # board's actual orientation. Do not reinterpret top/bottom as
                # the user's selected colour here.
                side_to_move = state.turn if state.turn is not None else self.side_to_move
                if state.exact_fen:
                    fen = state.exact_fen
                    reconciled_accepted = True
                    reconciled_status = (
                        f"DOM {state.site}: FEN chính xác đã được đối chiếu với bàn cờ."
                    )
                else:
                    reconciled = PositionReconciler().reconcile(
                        state.pieces,
                        last_fen=self.last_fen,
                        turn_hint=side_to_move,
                        source="DOM",
                        max_plies=3,
                        allow_resync=state.turn_reliable,
                    )
                    fen = reconciled.fen
                    reconciled_accepted = reconciled.accepted
                    reconciled_status = reconciled.status
                board = chess.Board(fen)
                effective_turn = "Trắng" if board.turn == chess.WHITE else "Đen"
                status = (
                    f"DOM đọc {len(state.pieces)} quân, lượt {effective_turn} "
                    f"theo {'đồng hồ đang chạy' if state.turn_reliable else 'danh sách nước'} "
                    f"({state.site}, {'Đen' if state.black_at_bottom else 'Trắng'} ở dưới, "
                    f"clock {state.active_clock_position or 'không rõ'}). "
                    f"{reconciled_status}"
                )
                if not reconciled_accepted:
                    self.finished.emit(None, fen, len(state.pieces), None, None, status)
                    return
                if board.turn != self.side_to_move:
                    self.finished.emit(None, fen, len(state.pieces), None, None, status)
                    return
                if not self._should_analyze(
                    fen, self.last_fen, self.has_current_analysis, self.force_analysis
                ):
                    self.finished.emit(None, fen, len(state.pieces), None, None, status)
                    return
                result = self._analyze(fen)
                latest_state = reader.read()
                time.sleep(stability_delay)
                latest_confirmed = reader.read()
                if self._piece_signature(latest_state.pieces) != self._piece_signature(
                    latest_confirmed.pieces
                ):
                    self.finished.emit(
                        None,
                        fen,
                        len(latest_confirmed.pieces),
                        None,
                        None,
                        "Bàn cờ đang chuyển động sau phân tích; đã bỏ kết quả cũ và chờ ảnh ổn định.",
                    )
                    return
                latest_state = latest_confirmed
                if self._piece_signature(latest_state.pieces) != self._piece_signature(state.pieces):
                    if latest_state.exact_fen:
                        latest_fen = latest_state.exact_fen
                    else:
                        latest = PositionReconciler().reconcile(
                            latest_state.pieces,
                            last_fen=fen,
                            turn_hint=(latest_state.turn if latest_state.turn is not None else self.side_to_move),
                            source="DOM sau phân tích",
                            max_plies=3,
                            allow_resync=latest_state.turn_reliable,
                        )
                        latest_fen = latest.fen
                    self.finished.emit(
                        None,
                        latest_fen,
                        len(latest_state.pieces),
                        None,
                        None,
                        "Bàn cờ đã đổi trong lúc Stockfish tính; đã bỏ kết quả cũ và chuyển sang thế mới.",
                    )
                    return
                self.finished.emit(result, fen, len(state.pieces), None, None, status)
                return
            except DomUnavailableError:
                pass
            except DomReadError as exc:
                self.failed.emit(f"DOM tạm thời chưa đọc đủ bàn cờ: {exc}")
                return
            except Exception as exc:
                self.failed.emit(str(exc))
                return

            box, board_image = self._capture_detected_board()
            self.board_detected.emit(board_image, box)
            model_path = Path(str(self.config.get("vision.yolo_model_path", "")))
            if not model_path.exists():
                recognition = self.template_recognizer.recognize(
                    board_image,
                    perspective=str(self.config.get("vision.perspective", "white")),
                )
                preliminary_fen = FenBuilder().build(recognition.pieces, side_to_move=self.side_to_move)
                preliminary_board = chess.Board(preliminary_fen)
                if (
                    preliminary_board.king(chess.WHITE) is None
                    or preliminary_board.king(chess.BLACK) is None
                ):
                    update = self.tracker.process(
                        board_image,
                        perspective=str(self.config.get("vision.perspective", "white")),
                        player_color=self.side_to_move,
                    )
                    self.finished.emit(None, update.fen, update.changed_squares, board_image, box, recognition.status)
                    return
                reconciled = PositionReconciler().reconcile(
                    recognition.pieces,
                    last_fen=self.last_fen,
                    turn_hint=self.side_to_move,
                    source="Nhận diện mẫu",
                )
                fen = reconciled.fen
                board = chess.Board(fen)
                if not reconciled.accepted:
                    self.finished.emit(
                        None,
                        fen,
                        len(recognition.pieces),
                        board_image,
                        box,
                        f"{recognition.status} {reconciled.status}",
                    )
                    return
                if board.turn != self.side_to_move:
                    self.finished.emit(None, fen, len(recognition.pieces), board_image, box, reconciled.status)
                    return
                if not self._should_analyze(
                    fen, self.last_fen, self.has_current_analysis, self.force_analysis
                ):
                    self.finished.emit(None, fen, len(recognition.pieces), board_image, box, reconciled.status)
                    return
                result = self._analyze(fen)
                self.finished.emit(result, fen, len(recognition.pieces), board_image, box, reconciled.status)
                return

            detector = YoloDetector(
                str(model_path),
                float(self.config.get("vision.confidence_threshold", 0.5)),
            )
            detections = detector.detect(board_image)
            if not detections:
                raise RuntimeError(
                    "Mô hình YOLO không nhận diện được quân cờ nào trên bàn cờ. "
                    "Hãy kiểm tra đúng mô hình quân cờ và giảm ngưỡng tin cậy trong Cài đặt → Nhận diện."
                )
            pieces = PieceMapper().map_to_squares(
                detections,
                board_size=box.size,
                perspective=str(self.config.get("vision.perspective", "white")),
            )
            reconciled = PositionReconciler().reconcile(
                pieces,
                last_fen=self.last_fen,
                turn_hint=self.side_to_move,
                source="YOLO",
            )
            fen = reconciled.fen
            board = chess.Board(fen)
            if not reconciled.accepted:
                self.finished.emit(None, fen, len(detections), board_image, box, reconciled.status)
                return
            if board.turn != self.side_to_move:
                self.finished.emit(None, fen, len(detections), board_image, box, reconciled.status)
                return
            if not self._should_analyze(
                fen, self.last_fen, self.has_current_analysis, self.force_analysis
            ):
                self.finished.emit(None, fen, len(detections), board_image, box, reconciled.status)
                return
            result = self._analyze(fen)
            self.finished.emit(result, fen, len(detections), board_image, box, reconciled.status)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _analyze(self, fen: str) -> AnalysisResult:
        try:
            return self.engine_manager.analyze_fen(fen, force=self.force_analysis, realtime=True)
        except Exception as exc:
            self.engine_manager.close()
            raise RuntimeError(f"Stockfish gặp lỗi: {exc}") from exc

    @staticmethod
    def _should_analyze(
        fen: str,
        last_fen: str,
        has_current_analysis: bool,
        force_analysis: bool,
    ) -> bool:
        return force_analysis or fen != last_fen or not has_current_analysis

    def _capture_detected_board(self) -> tuple[BoardBox, object]:
        screenshot = ScreenCapture().capture()
        detector = BoardDetector()
        box = detector.detect(screenshot)
        if box is None:
            configured_box = BoardBox.from_config(self.config.get("vision.board_position"))
            detector = BoardDetector(configured_box)
            box = detector.detect(screenshot)
        if box is None:
            raise RuntimeError("Không tìm thấy bàn cờ trên màn hình. Hãy bảo đảm bàn cờ đang hiển thị rõ trong trình duyệt.")
        return box, detector.crop(screenshot, box)

    @staticmethod
    def _piece_signature(pieces: list[object]) -> tuple[tuple[int, str], ...]:
        return tuple(
            sorted(
                (int(getattr(piece, "square_index")), str(getattr(piece, "label")))
                for piece in pieces
            )
        )


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager, engine_manager: EngineManager) -> None:
        super().__init__()
        self.config = config
        self.engine_manager = engine_manager
        self._realtime_thread: QThread | None = None
        self._realtime_worker: RealtimeWorker | None = None
        self._last_realtime_fen = ""
        self._last_realtime_error = ""
        self._last_realtime_best_move = ""
        self._last_log_message = ""
        self._site_generation = 0
        self._browser_target_id = ""
        self._force_realtime_refresh = False
        self._refresh_in_progress = False
        self._realtime_busy_ticks = 0
        self._realtime_hang_reported = False
        self._board_seen_logged = False
        self._visual_tracker = VisualBoardTracker()
        self._template_recognizer = TemplatePieceRecognizer()
        self._realtime_enabled = False
        self._realtime_timer = QTimer(self)
        self._realtime_timer.setInterval(500)
        self._realtime_timer.timeout.connect(self._realtime_tick)

        self.setWindowTitle("Trợ lý cờ vua")
        self._build_ui()
        self._load_settings_into_controls()
        QTimer.singleShot(600, self._start_auto_realtime)

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        controls = QGroupBox("Điều khiển")
        top_bar = QGridLayout(controls)
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Yếu", "WEAK")
        self.profile_combo.addItem("Trung bình", "MEDIUM")
        self.profile_combo.addItem("Mạnh nhất", "STRONG")
        self.time_spin = QSpinBox()
        self.time_spin.setRange(100, 60000)
        self.time_spin.setSuffix(" ms")
        self.time_spin.setSingleStep(100)
        self.time_spin.setToolTip("Chỉ dùng khi tắt Thời gian thông minh.")
        self.adaptive_time_checkbox = QCheckBox("Thời gian thông minh")
        self.adaptive_time_checkbox.setToolTip(
            "Tự tăng thời gian cho thế khó và giảm thời gian cho thế dễ. "
            "Khi bật, thời gian cố định bên cạnh sẽ được bỏ qua."
        )
        self.side_combo = QComboBox()
        self.side_combo.addItem("Tôi cầm Trắng", "white")
        self.side_combo.addItem("Tôi cầm Đen", "black")
        self.new_game_button = QPushButton("＋ Ván mới")
        self.open_chesscom_button = QPushButton("Chess.com")
        self.open_lichess_button = QPushButton("Lichess")
        self.open_chessbase_button = QPushButton("ChessBase")
        self.open_chessclub_button = QPushButton("ChessClub")
        self.settings_button = QPushButton("⚙ Cài đặt")
        self.refresh_best_button = QPushButton("↻ Tính lại nước tốt nhất")
        self.refresh_best_button.setStyleSheet(
            "font-size: 15px; font-weight: 700; padding: 9px 14px; "
            "background: #15803d; color: white; border: 1px solid #166534; border-radius: 7px;"
        )
        self.new_game_button.setStyleSheet(
            "font-weight: 700; padding: 7px 12px; background: #fff7ed; "
            "color: #9a3412; border: 1px solid #fdba74; border-radius: 6px;"
        )
        site_button_style = (
            "font-weight: 600; padding: 7px 10px; background: #eff6ff; "
            "color: #1d4ed8; border: 1px solid #93c5fd; border-radius: 6px;"
        )
        for button in (
            self.open_chesscom_button,
            self.open_lichess_button,
            self.open_chessbase_button,
            self.open_chessclub_button,
        ):
            button.setStyleSheet(site_button_style)
        self.settings_button.setStyleSheet(
            "padding: 7px 10px; background: #f8fafc; color: #334155; "
            "border: 1px solid #cbd5e1; border-radius: 6px;"
        )
        self.profile_summary_label = QLabel("-")
        self.profile_summary_label.setStyleSheet(
            "padding: 6px 10px; color: #1e3a8a; background: #eff6ff; "
            "border: 1px solid #bfdbfe; border-radius: 5px; font-weight: 600;"
        )

        top_bar.addWidget(QLabel("Chế độ"), 0, 0)
        top_bar.addWidget(self.profile_combo, 0, 1)
        self.time_label = QLabel("Mỗi nước")
        top_bar.addWidget(self.time_label, 0, 2)
        top_bar.addWidget(self.time_spin, 0, 3)
        top_bar.addWidget(self.adaptive_time_checkbox, 1, 0, 1, 2)
        top_bar.addWidget(QLabel("Bên chơi"), 2, 0)
        top_bar.addWidget(self.side_combo, 2, 1)
        top_bar.addWidget(self.new_game_button, 2, 2)
        top_bar.addWidget(self.settings_button, 2, 3)
        top_bar.addWidget(self.open_chesscom_button, 3, 0)
        top_bar.addWidget(self.open_lichess_button, 3, 1)
        top_bar.addWidget(self.open_chessbase_button, 4, 0)
        top_bar.addWidget(self.open_chessclub_button, 4, 1)
        top_bar.addWidget(self.refresh_best_button, 3, 2, 2, 2)
        top_bar.addWidget(self.profile_summary_label, 5, 0, 1, 4)
        top_bar.setColumnStretch(1, 1)
        layout.addWidget(controls)

        fen_group = QGroupBox("Nhập FEN")
        fen_layout = QVBoxLayout(fen_group)
        self.fen_input = QPlainTextEdit()
        self.fen_input.setPlainText(START_FEN)
        self.fen_input.setMaximumHeight(88)
        fen_layout.addWidget(self.fen_input)
        layout.addWidget(fen_group)
        fen_group.setVisible(False)

        vision_group = QGroupBox("Lấy bàn cờ từ màn hình")
        vision_layout = QHBoxLayout(vision_group)
        self.board_position_label = QLabel("-")
        self.calibrate_button = QPushButton("Chọn vùng bàn cờ")
        self.capture_button = QPushButton("Thử chụp bàn cờ")
        self.screen_fen_button = QPushButton("Tạo FEN từ màn hình")
        vision_layout.addWidget(QLabel("Bàn cờ"))
        vision_layout.addWidget(self.board_position_label, 1)
        vision_layout.addWidget(self.calibrate_button)
        vision_layout.addWidget(self.capture_button)
        vision_layout.addWidget(self.screen_fen_button)
        layout.addWidget(vision_group)
        vision_group.setVisible(False)

        result_group = QGroupBox("Kết quả phân tích")
        result_layout = QVBoxLayout(result_group)
        self.best_move_label = QLabel("-")
        self.best_move_label.setWordWrap(True)
        self.best_move_label.setStyleSheet("font-size: 24px; font-weight: 700; color: #15803d;")
        self.best_move_label.setMinimumHeight(42)
        self.move_from_to_label = QLabel("-")
        self.move_from_to_label.setStyleSheet("font-size: 20px; font-weight: 600; color: #111827;")
        self.evaluation_label = QLabel("-")
        self.depth_label = QLabel("-")
        self.details_label = QLabel("-")
        self.fen_status_label = QLabel("-")
        self.fen_status_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("NƯỚC TỐT NHẤT", self.best_move_label)
        form.addRow("CHỈ DẪN", self.move_from_to_label)
        form.addRow("Đánh giá", self.evaluation_label)
        form.addRow("Độ sâu", self.depth_label)
        form.addRow("Chi tiết", self.details_label)
        form.addRow("Trạng thái", self.fen_status_label)
        self.board_widget = AnalysisBoardWidget()
        result_layout.addWidget(self.board_widget, 1)
        result_layout.addLayout(form)

        layout.addWidget(result_group)

        log_group = QGroupBox("Hoạt động gần đây")
        log_layout = QVBoxLayout(log_group)
        self.status_output = QTextEdit()
        self.status_output.setReadOnly(True)
        self.status_output.setMaximumHeight(120)
        self.status_output.setPlaceholderText("Các thay đổi quan trọng sẽ xuất hiện ở đây.")
        log_layout.addWidget(self.status_output)
        layout.addWidget(log_group)

        self.profile_combo.currentIndexChanged.connect(self._apply_profile)
        self.time_spin.valueChanged.connect(self._set_time)
        self.adaptive_time_checkbox.toggled.connect(self._set_adaptive_time)
        self.side_combo.currentIndexChanged.connect(self._set_side)
        self.new_game_button.clicked.connect(self._new_game)
        self.open_chesscom_button.clicked.connect(self._open_chesscom)
        self.open_lichess_button.clicked.connect(self._open_lichess)
        self.open_chessbase_button.clicked.connect(self._open_chessbase)
        self.open_chessclub_button.clicked.connect(self._open_chessclub)
        self.settings_button.clicked.connect(self._open_settings)
        self.refresh_best_button.clicked.connect(self._refresh_best_move)
        self.calibrate_button.clicked.connect(self._calibrate_board)
        self.capture_button.clicked.connect(self._capture_board)
        self.screen_fen_button.clicked.connect(self._build_fen_from_screen)

    def _load_settings_into_controls(self) -> None:
        preset = str(self.config.get("analysis.preset", "STRONG"))
        if preset not in {"WEAK", "MEDIUM", "STRONG"}:
            preset = "STRONG"
        profile_index = self.profile_combo.findData(preset)
        self.profile_combo.setCurrentIndex(max(profile_index, 0))
        self.time_spin.setValue(int(self.config.get("analysis.time_ms", 1000)))
        self.adaptive_time_checkbox.blockSignals(True)
        self.adaptive_time_checkbox.setChecked(
            bool(self.config.get("analysis.adaptive_time_enabled", True))
        )
        self.adaptive_time_checkbox.blockSignals(False)
        self._sync_time_controls()
        self._refresh_profile_summary()
        perspective = str(self.config.get("vision.perspective", "white"))
        index = self.side_combo.findData(perspective)
        self.side_combo.blockSignals(True)
        self.side_combo.setCurrentIndex(max(index, 0))
        self.side_combo.blockSignals(False)
        self.board_widget.set_perspective(str(self.side_combo.currentData()))
        self._refresh_board_position_label()

    @Slot(int)
    def _apply_profile(self, _index: int) -> None:
        profile = str(self.profile_combo.currentData())
        self.config.apply_profile(profile)
        self.time_spin.blockSignals(True)
        self.time_spin.setValue(int(self.config.get("analysis.time_ms", 1000)))
        self.time_spin.blockSignals(False)
        self._sync_time_controls()
        self._refresh_profile_summary()
        self.engine_manager.clear_cache()
        self._log(f"Sức mạnh Stockfish: {self.profile_combo.currentText()}.")

    @Slot(int)
    def _set_time(self, value: int) -> None:
        self.config.set("analysis.time_ms", value)
        profile = str(self.profile_combo.currentData())
        if profile in {"WEAK", "MEDIUM", "STRONG"}:
            self.config.set(f"profiles.{profile}.time_ms", value)
        self.config.save()
        self.engine_manager.clear_cache()
        self._refresh_profile_summary()

    @Slot(bool)
    def _set_adaptive_time(self, enabled: bool) -> None:
        self.config.set("analysis.adaptive_time_enabled", enabled)
        self.config.save()
        self.engine_manager.clear_cache()
        self._sync_time_controls()
        self._refresh_profile_summary()
        if enabled:
            self._log("Phân tích thông minh: tự điều chỉnh thời gian theo độ khó của thế cờ.")
        else:
            self._log(
                f"Phân tích cố định: Stockfish dùng {self.time_spin.value() / 1000:.1f} giây mỗi nước."
            )

    def _sync_time_controls(self) -> None:
        adaptive = self.adaptive_time_checkbox.isChecked()
        self.time_spin.setEnabled(not adaptive)
        self.time_label.setEnabled(not adaptive)

    def _refresh_profile_summary(self) -> None:
        profile = str(self.profile_combo.currentData())
        values = self.config.get(f"profiles.{profile}", {})
        if not isinstance(values, dict):
            self.profile_summary_label.setText("-")
            return
        if self.adaptive_time_checkbox.isChecked():
            min_time = int(self.config.get("analysis.adaptive_min_time_ms", 700)) / 1000
            max_time = int(self.config.get("analysis.adaptive_realtime_max_time_ms", 4200)) / 1000
            time_text = f"thông minh {min_time:.1f}–{max_time:.1f} giây"
        else:
            time_text = f"cố định {self.time_spin.value() / 1000:.1f} giây"
        self.profile_summary_label.setText(
            f"{int(values.get('threads', 1))} luồng  ·  "
            f"{int(values.get('hash_mb', 128))} MB  ·  {time_text}  ·  "
            f"{int(values.get('multipv', 1))} phương án"
        )

    @Slot()
    def _set_side(self, *_args) -> None:
        perspective = str(self.side_combo.currentData())
        self._site_generation += 1
        self.config.set("vision.perspective", perspective)
        self.config.save()
        self.board_widget.set_perspective(perspective)
        self._last_realtime_fen = ""
        self._last_realtime_error = ""
        self._last_realtime_best_move = ""
        self._force_realtime_refresh = False
        self._refresh_in_progress = False
        self._board_seen_logged = False
        self._visual_tracker.reset()
        self._template_recognizer.reset()
        self._log(f"Bạn đang chơi bên {'Trắng' if perspective == 'white' else 'Đen'}.")

    @Slot()
    def _new_game(self) -> None:
        self._site_generation += 1
        self._visual_tracker.reset()
        self._template_recognizer.reset()
        self.engine_manager.new_game()
        self._last_realtime_fen = ""
        self._last_realtime_error = ""
        self._last_realtime_best_move = ""
        self._force_realtime_refresh = False
        self._refresh_in_progress = False
        self._board_seen_logged = False
        self.fen_input.setPlainText(START_FEN)
        self.board_widget.set_position(START_FEN)
        self.best_move_label.setText("-")
        self.move_from_to_label.setText("-")
        self.evaluation_label.setText("-")
        self.depth_label.setText("-")
        self.details_label.setText("-")
        self.fen_status_label.setText("-")
        self._log("Đã bắt đầu ván mới: lịch sử bàn cờ và gợi ý cũ đã được xóa.")

    @Slot()
    def _open_chesscom(self) -> None:
        self.config.set("browser.preferred_site", "chess.com")
        self.config.save()
        self._open_site(CHESS_COM_URL, "Chess.com")

    @Slot()
    def _open_lichess(self) -> None:
        self.config.set("browser.preferred_site", "lichess")
        self.config.save()
        self._open_site(LICHESS_URL, "Lichess")

    @Slot()
    def _open_chessbase(self) -> None:
        self.config.set("browser.preferred_site", "chessbase")
        self.config.save()
        self._open_site(CHESSBASE_URL, "ChessBase")

    @Slot()
    def _open_chessclub(self) -> None:
        self.config.set("browser.preferred_site", "chessclub")
        self.config.save()
        self._open_site(CHESSCLUB_URL, "ChessClub")

    def _open_site(self, url: str, name: str) -> None:
        target_id = open_chess_url(url)
        if not target_id:
            self._log(f"Không mở được {name}: trình duyệt kết nối chưa sẵn sàng.")
            return
        # Invalidate signals still in flight from the previously selected tab.
        # QThread cannot be killed safely while Stockfish owns the engine lock.
        self._site_generation += 1
        self._browser_target_id = target_id
        self._last_realtime_fen = ""
        self._last_realtime_error = ""
        self._last_realtime_best_move = ""
        self._force_realtime_refresh = True
        self._log(f"Đã mở {name}. Đang chờ bàn cờ xuất hiện trong tab mới.")
        if not self._realtime_enabled:
            self._realtime_enabled = True
            self._realtime_timer.start()
        self._realtime_tick()

    @Slot()
    def _open_settings(self) -> None:
        dialog = SettingsWindow(self.config, self)
        if dialog.exec():
            self.engine_manager.clear_cache()
            self._load_settings_into_controls()
            self._log("Đã lưu cài đặt và áp dụng cho lần phân tích tiếp theo.")

    @Slot()
    def _calibrate_board(self) -> None:
        try:
            screenshot = ScreenCapture().capture()
        except Exception as exc:
            QMessageBox.critical(self, "Chụp màn hình thất bại", str(exc))
            self._log(f"Chụp màn hình thất bại: {exc}")
            return

        dialog = BoardCalibrationWindow(screenshot, self)
        if not dialog.exec():
            return
        box = dialog.selected_box
        if box is None:
            QMessageBox.warning(self, "Chưa chọn bàn cờ", "Hãy kéo chuột chọn đúng vùng bàn cờ trước khi lưu.")
            return

        self.config.set("vision.board_position", box.to_dict())
        self.config.save()
        self._refresh_board_position_label()
        self._log(f"Đã chọn vùng bàn cờ: x={box.x}, y={box.y}, kích thước={box.size}")

    @Slot()
    def _capture_board(self) -> None:
        try:
            _, board_image = self._capture_calibrated_board()
        except Exception as exc:
            QMessageBox.critical(self, "Chụp bàn cờ thất bại", str(exc))
            self._log(f"Chụp bàn cờ thất bại: {exc}")
            return
        height, width = board_image.shape[:2]
        self._log(f"Đã chụp ảnh bàn cờ: {width}×{height}")

    @Slot()
    def _build_fen_from_screen(self) -> None:
        try:
            box, board_image = self._capture_calibrated_board()
            detector = YoloDetector(
                str(self.config.get("vision.yolo_model_path", "")),
                float(self.config.get("vision.confidence_threshold", 0.5)),
            )
            detections = detector.detect(board_image)
            pieces = PieceMapper().map_to_squares(
                detections,
                board_size=box.size,
                perspective=str(self.config.get("vision.perspective", "white")),
            )
            side_to_move = chess.WHITE if self.side_combo.currentData() == "white" else chess.BLACK
            fen = FenBuilder().build(pieces, side_to_move=side_to_move)
        except Exception as exc:
            QMessageBox.critical(self, "Tạo FEN từ màn hình thất bại", str(exc))
            self._log(f"Tạo FEN từ màn hình thất bại: {exc}")
            return

        self.fen_input.setPlainText(fen)
        self.board_widget.set_position(fen)
        self._log(f"Đã tạo FEN từ màn hình với {len(detections)} quân cờ nhận diện được.")

    @Slot()
    def _start_auto_realtime(self) -> None:
        if self._realtime_enabled:
            return
        self._realtime_enabled = True
        self._last_realtime_fen = ""
        self._last_realtime_error = ""
        self._last_realtime_best_move = ""
        self._board_seen_logged = False
        self._log("Theo dõi tự động đã bật. Đang tìm bàn cờ trong trình duyệt.")
        self._realtime_tick()
        self._realtime_timer.start()

    def _stop_realtime(self) -> None:
        self._realtime_enabled = False
        self._realtime_timer.stop()
        self._log("Đã dừng tự động quét.")

    def shutdown_workers(self) -> None:
        self._realtime_enabled = False
        self._realtime_timer.stop()
        self._stop_thread(self._realtime_thread)
        self._realtime_thread = None
        self._realtime_worker = None

    def closeEvent(self, event: Any) -> None:  # noqa: N802, ANN401
        self.shutdown_workers()
        super().closeEvent(event)

    @staticmethod
    def _stop_thread(thread: QThread | None, timeout_ms: int = 15_000) -> None:
        if thread is None or thread.isFinished():
            return
        thread.quit()
        if thread.wait(timeout_ms):
            return
        thread.terminate()
        thread.wait(2_000)

    @Slot()
    def _realtime_tick(self) -> None:
        if not self._realtime_enabled:
            return
        if self._realtime_thread is not None:
            self._realtime_busy_ticks += 1
            if self._realtime_busy_ticks >= 30 and not self._realtime_hang_reported:
                self._realtime_hang_reported = True
                self._log("Stockfish phản hồi chậm hơn 15 giây; yêu cầu tiếp theo đang được giữ lại.")
                self.fen_status_label.setText("Stockfish đang phản hồi chậm; ứng dụng vẫn tiếp tục chờ.")
            return

        side_to_move = chess.WHITE if self.side_combo.currentData() == "white" else chess.BLACK
        force_analysis = self._force_realtime_refresh
        self._force_realtime_refresh = False
        self._refresh_in_progress = force_analysis
        self._realtime_busy_ticks = 0
        self._realtime_hang_reported = False
        if force_analysis:
            self.refresh_best_button.setEnabled(False)
            self.refresh_best_button.setText("Đang tính lại...")
            self.fen_status_label.setText("Đang đọc lại bàn cờ và tính nước tốt nhất mới...")
            self._log("Đang đọc lại bàn cờ và tính một kết quả mới bằng Stockfish.")
        self._realtime_thread = QThread(self)
        self._realtime_worker = RealtimeWorker(
            self.config,
            self.engine_manager,
            self._visual_tracker,
            self._template_recognizer,
            side_to_move,
            self._last_realtime_fen,
            preferred_site=str(self.config.get("browser.preferred_site", "auto")),
            browser_target_id=self._browser_target_id,
            generation=self._site_generation,
            has_current_analysis=bool(self._last_realtime_best_move),
            force_analysis=force_analysis,
        )
        self._realtime_worker.moveToThread(self._realtime_thread)
        self._realtime_thread.started.connect(self._realtime_worker.run)
        self._realtime_worker.board_detected.connect(self._board_detected)
        self._realtime_worker.finished.connect(self._realtime_finished)
        self._realtime_worker.failed.connect(self._realtime_failed)
        self._realtime_worker.finished.connect(self._realtime_thread.quit)
        self._realtime_worker.failed.connect(self._realtime_thread.quit)
        self._realtime_thread.finished.connect(self._realtime_thread.deleteLater)
        self._realtime_thread.finished.connect(self._reset_realtime_worker)
        self._realtime_thread.start()

    @Slot(object, object)
    def _board_detected(self, board_image: object, box: BoardBox) -> None:
        if self._is_stale_worker_signal():
            return
        self.board_position_label.setText(f"x={box.x}, y={box.y}, kích thước={box.size}")
        self.board_widget.set_captured_position(self.fen_input.toPlainText().strip() or START_FEN, board_image)
        if not self._board_seen_logged:
            self._board_seen_logged = True
            self._log("Đã tìm thấy bàn cờ. Đang nhận diện quân cờ...")

    @Slot(object, str, int, object, object, str)
    def _realtime_finished(
        self,
        result: AnalysisResult | None,
        fen: str,
        detections_count: int,
        board_image: object,
        box: BoardBox,
        status: str,
    ) -> None:
        if self._is_stale_worker_signal():
            return
        previous_fen = self._last_realtime_fen
        self.fen_input.setPlainText(fen)
        self._update_fen_status(fen, detections_count, status)
        if box is not None:
            self.board_position_label.setText(f"x={box.x}, y={box.y}, kích thước={box.size}")
        else:
            self.board_position_label.setText("DOM")
        self._last_realtime_error = ""
        self._last_realtime_fen = fen
        if result is None:
            if previous_fen and fen != previous_fen:
                self._clear_best_move_display()
                if "tự đồng bộ lại" in status:
                    self._log("Đã khôi phục trạng thái ván từ bàn cờ hiện tại.")
            if self._refresh_in_progress:
                self._log(self._no_analysis_message(fen, status))
            if board_image is None:
                self.board_widget.set_position(fen)
                self.details_label.setText("DOM · đang theo dõi")
            else:
                self.board_widget.set_captured_position(fen, board_image)
                self.details_label.setText("Hình ảnh · đang theo dõi")
            return

        self._render_analysis_result(result, board_image)
        if self._refresh_in_progress:
            self._log(
                f"Đã tính xong: {result.best_move_san}, đánh giá {result.evaluation} "
                f"({self._source_name(result.source)})."
            )
        if result.best_move_uci != self._last_realtime_best_move:
            self._last_realtime_best_move = result.best_move_uci

    @Slot(str)
    def _realtime_failed(self, message: str) -> None:
        if self._is_stale_worker_signal():
            return
        if message != self._last_realtime_error:
            self._last_realtime_error = message
            self._log(f"Chưa đọc được bàn cờ: {message}")

    def _is_stale_worker_signal(self) -> bool:
        sender = self.sender()
        generation = getattr(sender, "generation", self._site_generation)
        return generation != self._site_generation

    @Slot()
    def _reset_realtime_worker(self) -> None:
        self._realtime_thread = None
        self._realtime_worker = None
        self._realtime_busy_ticks = 0
        self._realtime_hang_reported = False
        if self._refresh_in_progress:
            self._refresh_in_progress = False
            self.refresh_best_button.setEnabled(True)
            self.refresh_best_button.setText("↻ Tính lại nước tốt nhất")
        if self._force_realtime_refresh and self._realtime_enabled:
            QTimer.singleShot(0, self._realtime_tick)

    @Slot()
    def _refresh_best_move(self) -> None:
        self.engine_manager.clear_cache()
        self._force_realtime_refresh = True
        self._last_realtime_error = ""
        self.refresh_best_button.setText("Đang chờ lượt tính...")
        self.fen_status_label.setText("Yêu cầu tính lại đã được ghi nhận.")
        if self._realtime_thread is not None:
            self._log("Đã ghi nhận yêu cầu tính lại; sẽ chạy ngay sau tác vụ hiện tại.")
            return
        if not self._realtime_enabled:
            self._realtime_enabled = True
            self._realtime_timer.start()
        self._realtime_tick()

    def _capture_calibrated_board(self) -> tuple[BoardBox, object]:
        configured_box = BoardBox.from_config(self.config.get("vision.board_position"))
        if configured_box is None:
            raise RuntimeError("Chưa chọn vùng bàn cờ. Hãy bấm “Chọn vùng bàn cờ” trước.")
        screenshot = ScreenCapture().capture()
        detector = BoardDetector(configured_box)
        box = detector.detect(screenshot)
        if box is None:
            raise RuntimeError("Vùng bàn cờ đã chọn nằm ngoài ảnh chụp hiện tại.")
        return box, detector.crop(screenshot, box)

    def _refresh_board_position_label(self) -> None:
        box = BoardBox.from_config(self.config.get("vision.board_position"))
        if box is None:
            self.board_position_label.setText("Chưa chọn")
            return
        self.board_position_label.setText(f"x={box.x}, y={box.y}, kích thước={box.size}")

    def _render_analysis_result(self, result: AnalysisResult, board_image: object | None = None) -> None:
        self.best_move_label.setText(self._describe_best_move(result))
        self.move_from_to_label.setText(self._from_to_text(result.best_move_uci))
        self.evaluation_label.setText(result.evaluation)
        self.depth_label.setText(str(result.depth or "-"))
        source_text = {
            "cache": "Bộ nhớ đệm",
            "book": "Sách khai cuộc",
            "tablebase": "Cơ sở dữ liệu tàn cuộc Syzygy",
            "engine": "Stockfish",
            "engine_book_check": "Stockfish kiểm tra sách khai cuộc",
        }.get(result.source, result.source)
        self.details_label.setText(f"{source_text} · {result.thinking_time_ms} ms")
        self._update_fen_status(result.fen, len(chess.Board(result.fen).piece_map()), result.source)
        if board_image is None:
            self.board_widget.set_position(result.fen, result.best_move_uci)
        else:
            self.board_widget.set_captured_position(result.fen, board_image, result.best_move_uci)
        self._show_move_on_web_board(result)

    def _clear_best_move_display(self) -> None:
        self.best_move_label.setText("Đang chờ nước mới...")
        self.move_from_to_label.setText("-")
        self.evaluation_label.setText("-")
        self.depth_label.setText("-")
        self.details_label.setText("-")
        self._last_realtime_best_move = ""

    def _no_analysis_message(self, fen: str, status: str) -> str:
        try:
            board_turn = chess.Board(fen).turn
            player_turn = chess.WHITE if self.side_combo.currentData() == "white" else chess.BLACK
            if board_turn != player_turn:
                opponent = "Đen" if player_turn == chess.WHITE else "Trắng"
                return f"Chưa cần tính nước: hiện đang là lượt {opponent}."
        except ValueError:
            pass
        if "đang chuyển động" in status or "đang chuyển" in status:
            return "Bàn cờ đang chuyển động; ứng dụng sẽ đọc lại khi quân đã đứng yên."
        if "không đổi" in status:
            return "Bàn cờ chưa có nước mới; kết quả hiện tại vẫn được giữ nguyên."
        return f"Chưa thể tính nước mới. {status}"

    @staticmethod
    def _source_name(source: str) -> str:
        return {
            "cache": "kết quả đã lưu",
            "book": "sách khai cuộc",
            "tablebase": "cơ sở dữ liệu tàn cuộc",
            "engine": "Stockfish",
            "engine_book_check": "Stockfish kiểm tra sách khai cuộc",
        }.get(source, source)

    def _show_move_on_web_board(self, result: AnalysisResult) -> None:
        try:
            DomBoardReader(
                preferred_site=str(self.config.get("browser.preferred_site", "auto")),
                target_id=self._browser_target_id,
            ).show_best_move(
                result.best_move_uci,
                perspective=str(self.side_combo.currentData()),
                label=self._describe_best_move(result),
            )
        except Exception:
            return

    def _describe_best_move(self, result: AnalysisResult) -> str:
        try:
            board = chess.Board(result.fen)
            move = chess.Move.from_uci(result.best_move_uci)
            piece = board.piece_at(move.from_square)
            captured = board.piece_at(move.to_square)
        except ValueError:
            return result.best_move_san
        if piece is None:
            return result.best_move_san

        text = f"{self._piece_name(piece)} từ {chess.square_name(move.from_square)} đến {chess.square_name(move.to_square)}"
        if captured is not None:
            text += f", ăn {self._piece_name(captured).lower()}"
        if move.promotion is not None:
            text += f", phong cấp thành {self._piece_type_name(move.promotion).lower()}"
        return text

    @staticmethod
    def _from_to_text(move_uci: str) -> str:
        if len(move_uci) < 4:
            return "-"
        return f"Ô đi: {move_uci[:2]}  →  Ô đến: {move_uci[2:4]}"

    def _piece_name(self, piece: chess.Piece) -> str:
        color = "Trắng" if piece.color == chess.WHITE else "Đen"
        return f"{self._piece_type_name(piece.piece_type)} {color}"

    @staticmethod
    def _piece_type_name(piece_type: int) -> str:
        names = {
            chess.PAWN: "Tốt",
            chess.KNIGHT: "Mã",
            chess.BISHOP: "Tượng",
            chess.ROOK: "Xe",
            chess.QUEEN: "Hậu",
            chess.KING: "Vua",
        }
        return names.get(piece_type, "Quân")

    def _update_fen_status(self, fen: str, piece_count: int, status: str = "") -> None:
        try:
            board = chess.Board(fen)
            turn_text = "Trắng đi" if board.turn == chess.WHITE else "Đen đi"
            self.fen_status_label.setText(f"{turn_text}, {piece_count} quân. {status}")
        except ValueError:
            self.fen_status_label.setText(f"FEN không hợp lệ. {status}")

    def _log(self, message: str) -> None:
        if message == self._last_log_message:
            return
        self._last_log_message = message
        self.status_output.append(message)
