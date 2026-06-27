from __future__ import annotations

import html
import math
import queue
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import chess
import numpy as np
from PySide6.QtCore import QObject, QPointF, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF, QTextCursor
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
    QScrollArea,
    QSpinBox,
    QSizePolicy,
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
        self.setMinimumSize(440, 440)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

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
        painter.fillRect(self.rect(), QColor("#0b1120"))

        side = min(self.width(), self.height()) - 12
        if side <= 0:
            return
        left = (self.width() - side) / 2
        top = (self.height() - side) / 2
        square = side / 8

        light = QColor("#cbd5e1")
        dark = QColor("#52637a")
        highlight = QColor(74, 222, 128, 115)

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
        refinement_analysis: bool = False,
        last_analysis_result: AnalysisResult | None = None,
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
        self.refinement_analysis = refinement_analysis
        self.last_analysis_result = last_analysis_result

    @Slot()
    def run(self) -> None:
        pipeline_started = time.perf_counter()
        try:
            dom_fallback_reason = ""
            try:
                reader = DomBoardReader(
                    preferred_site=self.preferred_site,
                    target_id=self.browser_target_id,
                )
                first_dom_started = time.perf_counter()
                state = reader.read()
                first_dom_ms = int((time.perf_counter() - first_dom_started) * 1000)
                stability_delay = (
                    0.02 if self._bullet_fast_path()
                    else 0.05 if "lichess.org" in state.url.lower()
                    else 0.03
                )
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
                side_to_move = self._turn_hint(
                    state.turn,
                    state.turn_reliable,
                    self.side_to_move,
                )
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
                        allow_resync=(
                            state.turn_reliable
                            or state.site == "chessclub"
                            or self.force_analysis
                        ),
                        allow_piece_increase_resync=(
                            state.site == "chessclub" or self.force_analysis
                        ),
                        trusted_turn_hint=state.turn_reliable,
                    )
                    fen = reconciled.fen
                    reconciled_accepted = reconciled.accepted
                    reconciled_status = reconciled.status
                board = chess.Board(fen)
                effective_turn = "Trắng" if board.turn == chess.WHITE else "Đen"
                turn_source = (
                    state.turn_source
                    if state.turn_reliable
                    else "màu người chơi đã chọn"
                )
                status = (
                    f"DOM đọc {len(state.pieces)} quân, lượt {effective_turn} "
                    f"theo {turn_source} "
                    f"({state.site}, {'Đen' if state.black_at_bottom else 'Trắng'} ở dưới, "
                    f"clock {state.active_clock_position or 'không rõ'}). "
                    f"{reconciled_status}"
                )
                preferred_site = self._normalized_site(self.preferred_site)
                if preferred_site != "auto" and preferred_site != state.site:
                    status = (
                        f"DOM tự chọn {state.site} thay cho site đã lưu {preferred_site}. "
                        f"{status}"
                    )
                if not reconciled_accepted:
                    self.finished.emit(None, fen, len(state.pieces), None, None, status)
                    return
                if board.turn != self.side_to_move:
                    if self.force_analysis:
                        forced_board = board.copy(stack=False)
                        forced_board.turn = self.side_to_move
                        if forced_board.is_valid():
                            board = forced_board
                            fen = board.fen()
                            status += " Đã dùng màu người chơi làm lượt đi theo yêu cầu tính lại."
                        else:
                            self.finished.emit(None, fen, len(state.pieces), None, None, status)
                            return
                    else:
                        if self._can_use_ponder_fen(
                            state.site,
                            bool(state.exact_fen),
                            bool(self.last_fen),
                        ):
                            ponder_note = self._start_ponder_for_opponent_turn(
                                fen, state.site
                            )
                            if ponder_note:
                                status += f" {ponder_note}"
                        else:
                            self.engine_manager.stop_ponder()
                            status += " Ponder cần FEN chính xác từ website."
                        self.finished.emit(None, fen, len(state.pieces), None, None, status)
                        return
                # A speculative Bullet search starts as soon as a suggestion is
                # shown. Polling the unchanged player position must not resolve
                # that search as a miss before the player has moved.
                if not self._should_analyze(
                    fen,
                    self.last_fen,
                    self.has_current_analysis,
                    self.force_analysis or self.refinement_analysis,
                ):
                    self.finished.emit(None, fen, len(state.pieces), None, None, status)
                    return
                ponder_missed = False
                if not self._bullet_fast_path():
                    if self._can_use_ponder_fen(
                        state.site,
                        bool(state.exact_fen),
                        bool(self.last_fen),
                    ):
                        ponder_result, ponder_outcome = self.engine_manager.resolve_ponder(
                            fen,
                            settle_ms=int(
                                self.config.get("analysis.ponder_hit_settle_ms", 120)
                            ),
                        )
                        if ponder_outcome == "miss":
                            ponder_missed = True
                            status += " Ponder miss; đã chuyển sang phân tích vị trí thực tế."
                        elif ponder_outcome == "hit-empty":
                            status += " Ponder hit nhưng chưa có đủ dữ liệu; đang tính tiếp."
                        elif ponder_outcome == "hit-partial" and ponder_result is not None:
                            expected = min(
                                self._realtime_multipv(state.site),
                                chess.Board(fen).legal_moves.count(),
                            )
                            status += (
                                f" Ponder hit; hiện ngay {len(ponder_result.lines)}/{expected} "
                                "phương án và đang bổ sung phần còn thiếu."
                            )
                            self.finished.emit(
                                replace(ponder_result, source="ponder_partial"),
                                fen,
                                len(state.pieces),
                                None,
                                None,
                                status,
                            )
                            completed = self._analyze_ponder_completion(fen, expected)
                            completed_state = reader.read()
                            if self._piece_signature(completed_state.pieces) != self._piece_signature(
                                state.pieces
                            ):
                                self.finished.emit(
                                    None,
                                    completed_state.exact_fen or fen,
                                    len(completed_state.pieces),
                                    None,
                                    None,
                                    "Bàn cờ đổi khi đang bổ sung các phương án Ponder; đã bỏ kết quả cũ.",
                                )
                                return
                            self.finished.emit(
                                replace(completed, source="ponder_complete"),
                                fen,
                                len(state.pieces),
                                None,
                                None,
                                f"{status} Đã bổ sung đủ {len(completed.lines)} phương án.",
                            )
                            return
                        elif ponder_result is not None:
                            status += " Ponder hit; dùng ngay kết quả đã tính trong lượt đối thủ."
                            self.finished.emit(
                                ponder_result, fen, len(state.pieces), None, None, status
                            )
                            return
                    else:
                        self.engine_manager.stop_ponder()
                    if ponder_missed and not self.force_analysis and not self.refinement_analysis:
                        quick_result = self._analyze_quick(
                            fen,
                            multipv=self._realtime_multipv(state.site),
                        )
                        quick_state = reader.read()
                        if self._piece_signature(quick_state.pieces) != self._piece_signature(
                            state.pieces
                        ):
                            self.finished.emit(
                                None,
                                quick_state.exact_fen or fen,
                                len(quick_state.pieces),
                                None,
                                None,
                                "Bàn cờ đổi trong lúc tính nhanh sau ponder miss; đã bỏ kết quả cũ.",
                            )
                            return
                        self.finished.emit(
                            replace(quick_result, source="ponder_miss_fast"),
                            fen,
                            len(state.pieces),
                            None,
                            None,
                            status + " Đã hiện gợi ý nhanh; Stockfish đang tinh chỉnh nền.",
                        )
                        return
                    if self.refinement_analysis:
                        result = self._analyze(fen, multipv=self._realtime_multipv(state.site))
                        self.finished.emit(
                            result, fen, len(state.pieces), None, None,
                            status + " Đã tinh chỉnh kết quả nền.",
                        )
                        return
                result, changed_during_analysis = self._analyze_with_dom_monitor(
                    fen,
                    reader,
                    self._piece_signature(state.pieces),
                    multipv=self._realtime_multipv(state.site),
                )
                if self._bullet_fast_path():
                    # Bullet has no DOM monitor — always re-read after
                    # analysis to confirm the board is still the same.
                    latest_state = reader.read()
                else:
                    latest_state = reader.read()
                    if self._bullet_fast_path():
                        latest_confirmed = latest_state
                    else:
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
                if (
                    changed_during_analysis
                    or self._piece_signature(latest_state.pieces)
                    != self._piece_signature(state.pieces)
                ):
                    if latest_state.exact_fen:
                        latest_fen = latest_state.exact_fen
                    else:
                        latest = PositionReconciler().reconcile(
                            latest_state.pieces,
                            last_fen=fen,
                            turn_hint=(latest_state.turn if latest_state.turn is not None else self.side_to_move),
                            source="DOM sau phân tích",
                            max_plies=3,
                            allow_resync=(
                                latest_state.turn_reliable
                                or latest_state.site == "chessclub"
                                or self.force_analysis
                            ),
                            allow_piece_increase_resync=(
                                latest_state.site == "chessclub" or self.force_analysis
                            ),
                            trusted_turn_hint=latest_state.turn_reliable,
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
                if ponder_missed:
                    status += " Kết quả đầy đủ đã được tinh chỉnh sau gợi ý nhanh."
                if self._bullet_fast_path() and result is not None:
                    pipeline_ms = int((time.perf_counter() - pipeline_started) * 1000)
                    status += (
                        f" Bullet: tổng {pipeline_ms} ms, "
                        f"DOM {first_dom_ms} ms, Stockfish {result.thinking_time_ms} ms."
                    )
                self.finished.emit(result, fen, len(state.pieces), None, None, status)
                return
            except DomUnavailableError as exc:
                dom_fallback_reason = str(exc)
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
                image_status = self._image_status(recognition.status, dom_fallback_reason)
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
                    self.finished.emit(None, update.fen, update.changed_squares, board_image, box, image_status)
                    return
                reconciled = PositionReconciler().reconcile(
                    recognition.pieces,
                    last_fen=self.last_fen,
                    turn_hint=self.side_to_move,
                    source="Nhận diện mẫu",
                )
                image_status = self._image_status(
                    f"{recognition.status} {reconciled.status}",
                    dom_fallback_reason,
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
                        image_status,
                    )
                    return
                if board.turn != self.side_to_move:
                    if self.force_analysis:
                        board.turn = self.side_to_move
                        fen = board.fen()
                    else:
                        self.finished.emit(None, fen, len(recognition.pieces), board_image, box, image_status)
                        return
                if not self._should_analyze(
                    fen, self.last_fen, self.has_current_analysis, self.force_analysis
                ):
                    self.finished.emit(None, fen, len(recognition.pieces), board_image, box, image_status)
                    return
                result = self._analyze(fen, multipv=self._preferred_site_multipv())
                self.finished.emit(result, fen, len(recognition.pieces), board_image, box, image_status)
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
            image_status = self._image_status(reconciled.status, dom_fallback_reason)
            fen = reconciled.fen
            board = chess.Board(fen)
            if not reconciled.accepted:
                self.finished.emit(None, fen, len(detections), board_image, box, image_status)
                return
            if board.turn != self.side_to_move:
                if self.force_analysis:
                    board.turn = self.side_to_move
                    fen = board.fen()
                else:
                    self.finished.emit(None, fen, len(detections), board_image, box, image_status)
                    return
            if not self._should_analyze(
                fen, self.last_fen, self.has_current_analysis,
                self.force_analysis or self.refinement_analysis,
            ):
                self.finished.emit(None, fen, len(detections), board_image, box, image_status)
                return
            result = self._analyze(fen, multipv=self._preferred_site_multipv())
            self.finished.emit(result, fen, len(detections), board_image, box, image_status)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _analyze(self, fen: str, multipv: int = 1) -> AnalysisResult:
        try:
            if self._bullet_fast_path():
                result = self.engine_manager.analyze_fen(
                    fen,
                    force=self.force_analysis,
                    realtime=True,
                    multipv_override=1,
                    time_ms_override=int(self.config.get("analysis.time_ms", 150)),
                    adaptive_override=False,
                )
                return replace(result, source="bullet")
            if self.refinement_analysis:
                result = self.engine_manager.analyze_fen(
                    fen,
                    force=True,
                    realtime=True,
                    multipv_override=multipv,
                    time_ms_override=int(
                        self.config.get("analysis.ponder_refinement_time_ms", 2000)
                    ),
                    adaptive_override=False,
                )
                return replace(result, source="ponder_miss_refined")
            kwargs = {
                "force": self.force_analysis,
                "realtime": not self.force_analysis,
            }
            if self.force_analysis or multipv > 1:
                kwargs["multipv_override"] = multipv
            return self.engine_manager.analyze_fen(fen, **kwargs)
        except Exception as exc:
            self.engine_manager.close_engine()
            raise RuntimeError(f"Stockfish gặp lỗi: {exc}") from exc

    def _analyze_quick(self, fen: str, multipv: int) -> AnalysisResult:
        try:
            time_ms = int(
                self.config.get("analysis.ponder_miss_quick_time_ms", 650)
            )
            return self.engine_manager.analyze_fen(
                fen,
                force=True,
                realtime=True,
                multipv_override=multipv,
                time_ms_override=time_ms,
                adaptive_override=False,
            )
        except Exception as exc:
            self.engine_manager.close_engine()
            raise RuntimeError(f"Stockfish tính nhanh sau ponder miss gặp lỗi: {exc}") from exc

    def _analyze_ponder_completion(self, fen: str, multipv: int) -> AnalysisResult:
        try:
            return self.engine_manager.analyze_fen(
                fen,
                force=True,
                realtime=True,
                multipv_override=multipv,
                time_ms_override=int(
                    self.config.get("analysis.ponder_completion_time_ms", 650)
                ),
                adaptive_override=False,
            )
        except Exception as exc:
            self.engine_manager.close_engine()
            raise RuntimeError(f"Stockfish bổ sung phương án Ponder gặp lỗi: {exc}") from exc

    def _analyze_with_dom_monitor(
        self,
        fen: str,
        reader: DomBoardReader,
        initial_signature: tuple[tuple[int, str], ...],
        multipv: int = 1,
    ) -> tuple[AnalysisResult | None, bool]:
        if self._bullet_fast_path():
            return self._analyze(fen, multipv=multipv), False

        stop_monitor = threading.Event()
        board_changed = threading.Event()

        def monitor() -> None:
            interval = 0.03 if self._bullet_fast_path() else 0.10
            while not stop_monitor.wait(interval):
                try:
                    current = reader.read()
                except (DomUnavailableError, DomReadError):
                    continue
                if self._piece_signature(current.pieces) == initial_signature:
                    continue
                board_changed.set()
                self.engine_manager.cancel_analysis()
                return

        monitor_thread = threading.Thread(
            target=monitor,
            daemon=True,
            name="dom-position-monitor",
        )
        monitor_thread.start()
        try:
            try:
                result = self._analyze(fen, multipv=multipv)
            except RuntimeError:
                if not board_changed.is_set():
                    raise
                result = None
        finally:
            stop_monitor.set()
            # Bullet analyses only 150 ms — the monitor may still be mid-read
            # inside a 100–400 ms WebSocket round-trip.  A 50 ms grace window
            # lets an already-completing read finish; anything longer would
            # cancel the latency gain we just achieved.  The daemon thread
            # exits on its own shortly after.
            join_timeout = 0.05 if self._bullet_fast_path() else 0.5
            monitor_thread.join(timeout=join_timeout)
        return result, board_changed.is_set()

    @staticmethod
    def _image_status(status: str, dom_fallback_reason: str) -> str:
        if not dom_fallback_reason:
            return status
        return f"Fallback hình ảnh vì DOM: {dom_fallback_reason} {status}"

    @staticmethod
    def _normalized_site(site: str) -> str:
        aliases = {
            "chesscom": "chess.com",
            "play.chessbase.com": "chessbase",
            "icc": "chessclub",
            "play.chessclub.com": "chessclub",
        }
        normalized = site.lower()
        return aliases.get(normalized, normalized)

    def _preferred_site_multipv(self) -> int:
        return self._realtime_multipv(self.preferred_site)

    def _bullet_fast_path(self) -> bool:
        return str(
            self.config.get("analysis.active_time_control_preset", "")
        ).upper() == "BULLET"

    def _realtime_multipv(self, site: str) -> int:
        active = str(self.config.get("analysis.active_time_control_preset", "")).upper()
        configured = int(self.config.get("engine.multipv", 1))
        if active:
            configured = int(
                self.config.get(
                    f"time_control_presets.{active}.multipv",
                    self.config.get("engine.multipv", 3),
                )
            )
        return self._site_multipv(site, configured)

    def _start_ponder_for_opponent_turn(self, current_fen: str, site: str) -> str:
        if not self._ponder_enabled(site):
            return ""

        multipv = self._realtime_multipv(site)
        phase, available, expected, depth = (
            self.engine_manager.ponder_progress_for_origin(current_fen)
        )
        if phase == "running":
            return (
                f"Ponder đang tính {available}/{expected} PV ở độ sâu D{depth} "
                "trong lượt đối thủ."
            )
        if phase == "ready":
            return (
                f"Ponder đã sẵn sàng {available}/{expected} PV ở độ sâu D{depth} "
                "và tiếp tục đào sâu."
            )

        target = None
        source = "PV trước"
        if self.last_analysis_result is not None:
            target = self._ponder_target(self.last_analysis_result, current_fen)
        if target is None:
            source = "dự đoán nhanh"
            try:
                target = self._predict_ponder_target(current_fen)
            except Exception:
                return "Ponder không thể tạo dự đoán nước đối thủ."
        if target is None:
            return "Ponder không tìm được nước đối thủ hợp lệ để dự đoán."
        target_fen, predicted_reply = target
        phase = self.engine_manager.start_ponder(
            target_fen,
            multipv=multipv,
            max_time_ms=int(self.config.get("analysis.ponder_max_time_ms", 10000)),
            origin_fen=current_fen,
        )
        if phase == "started":
            return (
                f"Ponder đang tính 0/{multipv} PV, dự đoán đối thủ đi "
                f"{predicted_reply} từ {source}."
            )
        if phase == "ready":
            return f"Ponder đã sẵn sàng {multipv}/{multipv} PV cho {predicted_reply}."
        return f"Ponder tiếp tục tính 0/{multipv} PV cho {predicted_reply}."

    def _predict_ponder_target(self, current_fen: str) -> tuple[str, str] | None:
        board = chess.Board(current_fen)
        prediction_time_ms = int(
            self.config.get("analysis.ponder_prediction_time_ms", 200)
        )
        prediction = self.engine_manager.analyze_fen(
            current_fen,
            force=True,
            realtime=True,
            multipv_override=1,
            time_ms_override=prediction_time_ms,
            adaptive_override=False,
        )
        try:
            reply = chess.Move.from_uci(prediction.best_move_uci)
        except ValueError:
            return None
        if reply not in board.legal_moves:
            return None
        reply_san = board.san(reply)
        board.push(reply)
        return board.fen(), reply_san

    def _ponder_enabled(self, site: str) -> bool:
        active = str(self.config.get("analysis.active_time_control_preset", "")).upper()
        return (
            active in {"RAPID", "BLITZ"}
            and bool(self.config.get("engine.ponder", False))
            and self._normalized_site(site) in {
                "chess.com", "lichess", "chessbase", "chessclub"
            }
        )

    @staticmethod
    def _can_use_ponder_fen(site: str, exact_fen: bool, has_history: bool) -> bool:
        # ChessClub currently exposes neither move-list SAN nor a reliable
        # active clock. Once legal history has been tracked, the reconciled FEN
        # is safe enough to ponder without waiting for unavailable exact DOM data.
        return exact_fen or (site == "chessclub" and has_history)

    @classmethod
    def _ponder_target(
        cls,
        previous_result: AnalysisResult,
        current_fen: str,
    ) -> tuple[str, str] | None:
        try:
            previous = chess.Board(previous_result.fen)
            current = chess.Board(current_fen)
        except ValueError:
            return None
        actual_move: chess.Move | None = None
        current_key = cls._fen_position_key(current.fen())
        for move in previous.legal_moves:
            candidate = previous.copy(stack=False)
            candidate.push(move)
            if cls._fen_position_key(candidate.fen()) == current_key:
                actual_move = move
                break
        if actual_move is None:
            return None
        line = next(
            (item for item in previous_result.lines if item.move_uci == actual_move.uci()),
            None,
        )
        if line is None or len(line.pv) < 2:
            return None
        try:
            reply = chess.Move.from_uci(line.pv[1])
        except ValueError:
            return None
        if reply not in current.legal_moves:
            return None
        reply_san = current.san(reply)
        target = current.copy(stack=False)
        target.push(reply)
        return target.fen(), reply_san

    @staticmethod
    def _fen_position_key(fen: str) -> str:
        return " ".join(fen.split()[:4])

    @classmethod
    def _site_multipv(cls, site: str, configured: int = 3) -> int:
        return max(1, min(int(configured), 3))

    @staticmethod
    def _should_analyze(
        fen: str,
        last_fen: str,
        has_current_analysis: bool,
        force_analysis: bool,
    ) -> bool:
        return force_analysis or fen != last_fen or not has_current_analysis

    @staticmethod
    def _turn_hint(
        detected_turn: chess.Color | None,
        detected_reliable: bool,
        player_color: chess.Color,
    ) -> chess.Color:
        return detected_turn if detected_turn is not None and detected_reliable else player_color

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


class WebOverlayDispatcher:
    def __init__(self) -> None:
        self._commands: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="web-overlay-dispatcher",
        )
        self._thread.start()

    def show(
        self,
        moves: list[dict[str, object]],
        perspective: str,
        preferred_site: str,
        target_id: str,
    ) -> None:
        self._submit(
            {
                "kind": "show",
                "moves": moves,
                "perspective": perspective,
                "preferred_site": preferred_site,
                "target_id": target_id,
            }
        )

    def clear(self, preferred_site: str, target_id: str) -> None:
        self._submit(
            {
                "kind": "clear",
                "preferred_site": preferred_site,
                "target_id": target_id,
            }
        )

    def stop(self) -> None:
        self._stopped.set()
        self._submit({"kind": "stop"})
        self._thread.join(timeout=1.0)

    def _submit(self, command: dict[str, object]) -> None:
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                break
        try:
            self._commands.put_nowait(command)
        except queue.Full:
            pass

    def _run(self) -> None:
        reader: DomBoardReader | None = None
        reader_key: tuple[str, str] | None = None
        while not self._stopped.is_set():
            try:
                command = self._commands.get(timeout=0.25)
            except queue.Empty:
                continue
            while True:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    break
            if command.get("kind") == "stop":
                break

            preferred_site = str(command.get("preferred_site", "auto"))
            target_id = str(command.get("target_id", ""))
            key = (preferred_site, target_id)
            if reader is None or reader_key != key:
                if reader is not None:
                    reader.close_local_connection()
                reader = DomBoardReader(
                    preferred_site=preferred_site,
                    target_id=target_id,
                )
                reader_key = key
            try:
                if command.get("kind") == "show":
                    reader.show_moves(
                        list(command.get("moves", [])),
                        str(command.get("perspective", "white")),
                        isolated_connection=True,
                    )
                elif command.get("kind") == "clear":
                    reader.clear_best_move(isolated_connection=True)
            except Exception:
                if reader is not None:
                    reader.close_local_connection()
                continue
        if reader is not None:
            reader.close_local_connection()


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
        self._last_analysis_result: AnalysisResult | None = None
        self._last_log_message = ""
        self._site_generation = 0
        self._browser_target_id = ""
        self._force_realtime_refresh = False
        self._force_realtime_refinement = False
        self._refresh_in_progress = False
        self._realtime_busy_ticks = 0
        self._realtime_started_at = 0.0
        self._realtime_hang_reported = False
        self._engine_warmup_thread: threading.Thread | None = None
        self._board_seen_logged = False
        self._visual_tracker = VisualBoardTracker()
        self._template_recognizer = TemplatePieceRecognizer()
        self._web_overlay_dispatcher = WebOverlayDispatcher()
        self._realtime_enabled = False
        self._realtime_timer = QTimer(self)
        self._realtime_timer.setInterval(150)
        self._realtime_timer.timeout.connect(self._realtime_tick)

        self.setWindowTitle("Trợ lý cờ vua")
        self._build_ui()
        self._load_settings_into_controls()
        self._refresh_ponder_badge_idle()
        QTimer.singleShot(300, self._warm_up_engine_async)
        QTimer.singleShot(600, self._start_auto_realtime)

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        self.root_layout = layout

        controls = QGroupBox("Điều khiển")
        top_bar = QGridLayout(controls)
        top_bar.setContentsMargins(8, 4, 8, 7)
        top_bar.setHorizontalSpacing(6)
        top_bar.setVerticalSpacing(5)
        self.default_engine_label = QLabel("Mặc định mạnh")
        self.default_engine_label.setStyleSheet("font-weight: 700; color: #dcfce7;")
        self.time_spin = QSpinBox()
        self.time_spin.setRange(10, 60000)
        self.time_spin.setSuffix(" ms")
        self.time_spin.setSingleStep(10)
        self.time_spin.setToolTip("Chỉ dùng khi tắt Thời gian thông minh.")
        self.adaptive_time_checkbox = QCheckBox("Thời gian thông minh")
        self.adaptive_time_checkbox.setToolTip(
            "Tự tăng thời gian cho thế khó và giảm thời gian cho thế dễ. "
            "Khi bật, thời gian cố định bên cạnh sẽ được bỏ qua."
        )
        self.rapid_time_button = QPushButton("Rapid")
        self.blitz_time_button = QPushButton("Blitz")
        self.bullet_time_button = QPushButton("Bullet")
        for button in (
            self.rapid_time_button,
            self.blitz_time_button,
            self.bullet_time_button,
        ):
            button.setToolTip("Áp dụng ngay preset nhịp độ đã lưu trong Cài đặt.")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setStyleSheet(
                "QPushButton:checked { background: #166534; color: #dcfce7; "
                "border: 1px solid #22c55e; font-weight: 700; }"
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
        self.refresh_best_button.setToolTip(
            "Đọc lại bàn cờ, bỏ cache và dùng thời gian phân tích sâu tối đa của chế độ hiện tại."
        )
        self.refresh_best_button.setStyleSheet(
            "font-size: 14px; font-weight: 700; padding: 6px 10px; "
            "background: #166534; color: #f0fdf4; border: 1px solid #22c55e; border-radius: 7px;"
        )
        self.web_overlay_button = QPushButton()
        self.web_overlay_button.setCheckable(True)
        self.web_overlay_button.setToolTip(
            "Bật: vẽ mũi tên màu, số thứ tự và điểm cho tối đa 3 nước trên website; "
            "ô nguồn có viền trắng nét đứt, ô đích mang màu của nước đi.\n"
            "Tắt: website không có dấu gợi ý; các nước chỉ hiện trong ứng dụng, phù hợp khi live stream."
        )
        self.new_game_button.setStyleSheet(
            "font-weight: 700; padding: 5px 9px; background: #431407; "
            "color: #fdba74; border: 1px solid #c2410c; border-radius: 6px;"
        )
        site_button_style = (
            "font-weight: 600; padding: 5px 8px; background: #172554; "
            "color: #bfdbfe; border: 1px solid #2563eb; border-radius: 6px;"
        )
        for button in (
            self.open_chesscom_button,
            self.open_lichess_button,
            self.open_chessbase_button,
            self.open_chessclub_button,
        ):
            button.setStyleSheet(site_button_style)
        self.settings_button.setStyleSheet(
            "padding: 5px 8px; background: #1e293b; color: #cbd5e1; "
            "border: 1px solid #475569; border-radius: 6px;"
        )
        for control in (
            self.default_engine_label,
            self.time_spin,
            self.side_combo,
            self.rapid_time_button,
            self.blitz_time_button,
            self.bullet_time_button,
            self.new_game_button,
            self.open_chesscom_button,
            self.open_lichess_button,
            self.open_chessbase_button,
            self.open_chessclub_button,
            self.settings_button,
            self.refresh_best_button,
            self.web_overlay_button,
        ):
            control.setMinimumHeight(29)
            control.setMaximumHeight(34)
        self.profile_summary_label = QLabel("-")
        self.profile_summary_label.setWordWrap(True)
        self.profile_summary_label.setMinimumWidth(0)
        self.profile_summary_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.profile_summary_label.setStyleSheet(
            "padding: 4px 7px; color: #bfdbfe; background: #172554; "
            "border: 1px solid #1d4ed8; border-radius: 5px; font-weight: 600;"
        )

        top_bar.addWidget(QLabel("Engine"), 0, 0)
        top_bar.addWidget(self.default_engine_label, 0, 1, 1, 2)
        self.time_label = QLabel("Mỗi nước")
        top_bar.addWidget(self.adaptive_time_checkbox, 0, 3, 1, 3)
        top_bar.addWidget(self.time_label, 0, 6)
        top_bar.addWidget(self.time_spin, 0, 7)
        top_bar.addWidget(self.rapid_time_button, 1, 0, 1, 2)
        top_bar.addWidget(self.blitz_time_button, 1, 2, 1, 2)
        top_bar.addWidget(self.bullet_time_button, 1, 4, 1, 2)
        top_bar.addWidget(self.refresh_best_button, 1, 6, 1, 2)
        top_bar.addWidget(self.side_combo, 2, 0, 1, 3)
        top_bar.addWidget(self.new_game_button, 2, 3, 1, 2)
        top_bar.addWidget(self.settings_button, 2, 5, 1, 3)
        top_bar.addWidget(self.open_chesscom_button, 3, 0, 1, 2)
        top_bar.addWidget(self.open_lichess_button, 3, 2, 1, 2)
        top_bar.addWidget(self.open_chessbase_button, 3, 4, 1, 2)
        top_bar.addWidget(self.open_chessclub_button, 3, 6, 1, 2)
        top_bar.addWidget(self.web_overlay_button, 4, 0, 1, 3)
        top_bar.addWidget(self.profile_summary_label, 4, 3, 1, 5)
        for column in range(8):
            top_bar.setColumnStretch(column, 1)
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

        self.result_group = QGroupBox("Kết quả phân tích")
        result_layout = QVBoxLayout(self.result_group)
        self.best_move_label = QLabel("-")
        self.best_move_label.setStyleSheet("font-size: 24px; font-weight: 700; color: #4ade80;")
        self.best_move_label.setMinimumHeight(42)
        self.move_from_to_label = QLabel("-")
        self.move_from_to_label.setStyleSheet("font-size: 20px; font-weight: 600; color: #e2e8f0;")
        self.evaluation_label = QLabel("-")
        self.candidate_moves_label = QLabel("-")
        self.difficulty_label = QLabel("-")
        self.depth_label = QLabel("-")
        self.details_label = QLabel("-")
        self.fen_status_label = QLabel("-")
        # Dynamic text must wrap inside the width chosen by the user. Letting
        # QLabel's content size hint drive the form can expand the main window
        # whenever a longer move description or status arrives.
        for label in (
            self.best_move_label,
            self.move_from_to_label,
            self.evaluation_label,
            self.candidate_moves_label,
            self.difficulty_label,
            self.depth_label,
            self.details_label,
            self.fen_status_label,
        ):
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            label.setMinimumWidth(0)
            label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
        self.candidate_moves_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Minimum,
        )
        self.candidate_moves_label.setStyleSheet(
            "font-size: 14px; color: #e2e8f0; padding: 6px; "
            "background: #0f172a; border: 1px solid #334155; border-radius: 6px;"
        )
        self.candidate_moves_label.setTextFormat(Qt.TextFormat.RichText)
        self.candidate_moves_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.analysis_details_panel = QWidget()
        details_layout = QVBoxLayout(self.analysis_details_panel)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(6)
        difficulty_title = QLabel("ĐỘ KHÓ THẾ CỜ")
        difficulty_title.setStyleSheet("font-weight: 800; color: #cbd5e1;")
        difficulty_header = QWidget()
        difficulty_header_layout = QHBoxLayout(difficulty_header)
        difficulty_header_layout.setContentsMargins(0, 0, 0, 0)
        difficulty_header_layout.setSpacing(8)
        difficulty_header_layout.addWidget(difficulty_title)
        difficulty_header_layout.addStretch(1)
        self.ponder_status_label = QLabel("PONDER: CHỜ")
        self.ponder_status_label.setToolTip(
            "Cho biết Stockfish đang ponder, đã hit, đang hiện gợi ý nhanh hay đã trả kết quả cuối."
        )
        self.ponder_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        difficulty_header_layout.addWidget(self.ponder_status_label)
        details_layout.addWidget(difficulty_header)
        details_layout.addWidget(self.difficulty_label)
        primary_details = QWidget()
        form = QFormLayout(primary_details)
        form.setContentsMargins(0, 0, 4, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(6)
        form.addRow("CÁC LỰA CHỌN", self.candidate_moves_label)
        form.addRow("Độ sâu", self.depth_label)
        form.addRow("Chi tiết", self.details_label)
        form.addRow("Trạng thái", self.fen_status_label)
        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details_scroll.setWidget(primary_details)
        details_layout.addWidget(details_scroll, 1)
        self.board_widget = AnalysisBoardWidget()
        self.result_content_layout = QHBoxLayout()
        self.result_content_layout.setContentsMargins(0, 0, 0, 0)
        self.result_content_layout.setSpacing(18)
        self.result_content_layout.addWidget(self.board_widget, 3)
        self.result_content_layout.addWidget(self.analysis_details_panel, 2)
        result_layout.addLayout(self.result_content_layout, 1)

        layout.addWidget(self.result_group, 5)

        self.log_group = QGroupBox("Nhật ký trạng thái")
        self.log_group.setMaximumHeight(125)
        log_layout = QVBoxLayout(self.log_group)
        self.status_output = QPlainTextEdit()
        self.status_output.setReadOnly(True)
        self.status_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.status_output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.status_output.setMaximumBlockCount(120)
        self.status_output.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        self.status_output.setMinimumHeight(64)
        self.status_output.setMaximumHeight(88)
        self.status_output.setStyleSheet(
            "font-family: 'Segoe UI'; font-size: 13px; padding: 8px;"
        )
        self.status_output.setPlaceholderText("Trạng thái ứng dụng sẽ xuất hiện ở đây.")
        log_layout.addWidget(self.status_output)
        layout.addWidget(self.log_group, 1)

        self.time_spin.valueChanged.connect(self._set_time)
        self.adaptive_time_checkbox.toggled.connect(self._set_adaptive_time)
        self.rapid_time_button.clicked.connect(lambda: self._apply_time_control_preset("RAPID"))
        self.blitz_time_button.clicked.connect(lambda: self._apply_time_control_preset("BLITZ"))
        self.bullet_time_button.clicked.connect(lambda: self._apply_time_control_preset("BULLET"))
        self.side_combo.currentIndexChanged.connect(self._set_side)
        self.new_game_button.clicked.connect(self._new_game)
        self.open_chesscom_button.clicked.connect(self._open_chesscom)
        self.open_lichess_button.clicked.connect(self._open_lichess)
        self.open_chessbase_button.clicked.connect(self._open_chessbase)
        self.open_chessclub_button.clicked.connect(self._open_chessclub)
        self.settings_button.clicked.connect(self._open_settings)
        self.refresh_best_button.clicked.connect(self._refresh_best_move)
        self.web_overlay_button.toggled.connect(self._set_web_overlay_enabled)
        self.calibrate_button.clicked.connect(self._calibrate_board)
        self.capture_button.clicked.connect(self._capture_board)
        self.screen_fen_button.clicked.connect(self._build_fen_from_screen)

    def _load_settings_into_controls(self) -> None:
        self.time_spin.blockSignals(True)
        self.time_spin.setValue(int(self.config.get("analysis.time_ms", 1000)))
        self.time_spin.blockSignals(False)
        self.adaptive_time_checkbox.blockSignals(True)
        self.adaptive_time_checkbox.setChecked(
            bool(self.config.get("analysis.adaptive_time_enabled", True))
        )
        self.adaptive_time_checkbox.blockSignals(False)
        self._sync_time_controls()
        self._sync_active_time_control_indicator()
        self._sync_realtime_poll_interval()
        self._refresh_profile_summary()
        perspective = str(self.config.get("vision.perspective", "white"))
        index = self.side_combo.findData(perspective)
        self.side_combo.blockSignals(True)
        self.side_combo.setCurrentIndex(max(index, 0))
        self.side_combo.blockSignals(False)
        self.board_widget.set_perspective(str(self.side_combo.currentData()))
        self.web_overlay_button.blockSignals(True)
        self.web_overlay_button.setChecked(
            bool(self.config.get("browser.web_overlay_enabled", True))
        )
        self.web_overlay_button.blockSignals(False)
        self._apply_web_overlay_mode()
        self._refresh_board_position_label()

    @Slot(bool)
    def _set_web_overlay_enabled(self, enabled: bool) -> None:
        self.config.set("browser.web_overlay_enabled", enabled)
        self.config.save()
        self._apply_web_overlay_mode()
        if enabled:
            if self._last_analysis_result is not None:
                self._show_move_on_web_board(self._last_analysis_result)
            self._log("Overlay web đã bật: bàn cờ ứng dụng được ẩn và gợi ý sẽ hiện trên website.")
        else:
            self._clear_move_from_web_board_async()
            self._log("Overlay web đã tắt: website không còn gợi ý; nước tốt nhất chỉ hiện trong ứng dụng.")

    def _apply_web_overlay_mode(self) -> None:
        enabled = self.web_overlay_button.isChecked()
        if enabled:
            self.board_widget.setMinimumSize(0, 0)
        else:
            self.board_widget.setMinimumSize(460, 460)
        self.board_widget.setVisible(not enabled)
        self.analysis_details_panel.setMinimumWidth(0 if enabled else 380)
        self.analysis_details_panel.setMaximumWidth(16777215 if enabled else 480)
        self.result_content_layout.setStretch(0, 0 if enabled else 3)
        self.result_content_layout.setStretch(1, 1 if enabled else 2)
        self.root_layout.invalidate()
        self.centralWidget().updateGeometry()
        self.updateGeometry()
        if enabled:
            self.web_overlay_button.setText("Overlay web: BẬT · UI ẩn")
            self.web_overlay_button.setStyleSheet(
                "font-weight: 700; padding: 5px 8px; background: #14532d; "
                "color: #dcfce7; border: 1px solid #22c55e; border-radius: 6px;"
            )
        else:
            self.web_overlay_button.setText("Overlay web: TẮT · Chỉ UI")
            self.web_overlay_button.setStyleSheet(
                "font-weight: 700; padding: 5px 8px; background: #7f1d1d; "
                "color: #fee2e2; border: 1px solid #ef4444; border-radius: 6px;"
            )
        QTimer.singleShot(0, self._resize_for_overlay_mode)

    def _resize_for_overlay_mode(self) -> None:
        if self.isMaximized() or self.isFullScreen():
            return
        available = self.screen().availableGeometry()
        if self.web_overlay_button.isChecked():
            desired_width, desired_height = 920, 940
        else:
            desired_width, desired_height = 1080, 980
        self.resize(
            min(desired_width, available.width()),
            min(desired_height, available.height()),
        )

    @Slot(int)
    def _set_time(self, value: int) -> None:
        self.config.update_default_config({"time_ms": value})
        self.config.apply_default_config()
        self.engine_manager.clear_cache()
        self._refresh_profile_summary()
        self._sync_active_time_control_indicator()
        self._sync_realtime_poll_interval()
        self._refresh_ponder_badge_idle()

    @Slot(bool)
    def _set_adaptive_time(self, enabled: bool) -> None:
        self.config.update_default_config({"adaptive_time_enabled": enabled})
        self.config.apply_default_config()
        self.engine_manager.clear_cache()
        self._sync_time_controls()
        self._refresh_profile_summary()
        self._sync_active_time_control_indicator()
        self._sync_realtime_poll_interval()
        self._refresh_ponder_badge_idle()
        if enabled:
            self._log("Phân tích thông minh: tự điều chỉnh thời gian theo độ khó của thế cờ.")
        else:
            self._log(
                f"Phân tích cố định: Stockfish dùng {self.time_spin.value() / 1000:.1f} giây mỗi nước."
            )

    def _apply_time_control_preset(self, name: str) -> None:
        self.engine_manager.stop_ponder()
        enabled = self.config.toggle_time_control_preset(name)
        self.adaptive_time_checkbox.blockSignals(True)
        self.time_spin.blockSignals(True)
        self.adaptive_time_checkbox.setChecked(
            bool(self.config.get("analysis.adaptive_time_enabled", True))
        )
        self.time_spin.setValue(int(self.config.get("analysis.time_ms", 1000)))
        self.adaptive_time_checkbox.blockSignals(False)
        self.time_spin.blockSignals(False)
        self.engine_manager.clear_cache()
        self._sync_time_controls()
        self._refresh_profile_summary()
        self._sync_active_time_control_indicator()
        self._sync_realtime_poll_interval()
        self._refresh_ponder_badge_idle()
        self._warm_up_engine_async()
        if enabled:
            self._log(f"Đã áp dụng preset {name.title()}.")
        else:
            self._log("Đã trở về cấu hình Stockfish mạnh nhất mặc định.")

    def _warm_up_engine_async(self) -> None:
        if (
            self._engine_warmup_thread is not None
            and self._engine_warmup_thread.is_alive()
        ):
            return

        def run() -> None:
            try:
                self.engine_manager.warm_up()
            except Exception:
                return

        self._engine_warmup_thread = threading.Thread(
            target=run,
            daemon=True,
            name="stockfish-warmup",
        )
        self._engine_warmup_thread.start()

    def _sync_active_time_control_indicator(self) -> None:
        active = str(self.config.get("analysis.active_time_control_preset", "")).upper()
        preset = self.config.get(f"time_control_presets.{active}", {}) if active else {}
        matches = isinstance(preset, dict) and bool(preset)
        if matches and "adaptive_time_enabled" in preset:
            matches = bool(preset["adaptive_time_enabled"]) == bool(
                self.config.get("analysis.adaptive_time_enabled", True)
            )
        timing_keys = {
            "threads": "engine.threads",
            "hash_mb": "engine.hash_mb",
            "multipv": "engine.multipv",
            "ponder": "engine.ponder",
            "skill_level": "engine.skill_level",
            "contempt": "engine.contempt",
            "time_ms": "analysis.time_ms",
            "min_time_ms": "analysis.adaptive_min_time_ms",
            "probe_time_ms": "analysis.adaptive_probe_time_ms",
            "realtime_max_time_ms": "analysis.adaptive_realtime_max_time_ms",
            "hard_max_time_ms": "analysis.adaptive_max_time_ms",
            "ponder_max_time_ms": "analysis.ponder_max_time_ms",
            "ponder_hit_settle_ms": "analysis.ponder_hit_settle_ms",
            "ponder_miss_quick_time_ms": "analysis.ponder_miss_quick_time_ms",
            "ponder_prediction_time_ms": "analysis.ponder_prediction_time_ms",
            "ponder_completion_time_ms": "analysis.ponder_completion_time_ms",
            "ponder_stop_timeout_ms": "analysis.ponder_stop_timeout_ms",
            "ponder_refinement_time_ms": "analysis.ponder_refinement_time_ms",
            "ponder_ready_depth": "analysis.ponder_ready_depth",
        }
        if matches:
            for source, target in timing_keys.items():
                if source in preset and int(preset[source]) != int(self.config.get(target, 0)):
                    matches = False
                    break
        if matches and "site" in preset:
            matches = str(preset["site"]) == str(self.config.get("browser.preferred_site", "auto"))
        if matches and "game_minutes" in preset:
            matches = int(preset["game_minutes"]) == int(self.config.get("analysis.game_minutes", 0))
        if not matches:
            active = ""
            self.config.set("analysis.active_time_control_preset", "")

        buttons = {
            "RAPID": self.rapid_time_button,
            "BLITZ": self.blitz_time_button,
            "BULLET": self.bullet_time_button,
        }
        for name, button in buttons.items():
            button.blockSignals(True)
            button.setAutoExclusive(False)
            button.setChecked(name == active)
            button.setAutoExclusive(True)
            button.blockSignals(False)

    def _sync_time_controls(self) -> None:
        adaptive = self.adaptive_time_checkbox.isChecked()
        self.time_spin.setEnabled(not adaptive)
        self.time_label.setEnabled(not adaptive)

    def _sync_realtime_poll_interval(self) -> None:
        active = str(
            self.config.get("analysis.active_time_control_preset", "")
        ).upper()
        self._realtime_timer.setInterval(25 if active == "BULLET" else 150)

    def _refresh_profile_summary(self) -> None:
        if self.adaptive_time_checkbox.isChecked():
            min_time = int(self.config.get("analysis.adaptive_min_time_ms", 700)) / 1000
            max_time = int(self.config.get("analysis.adaptive_realtime_max_time_ms", 4200)) / 1000
            time_text = f"thông minh {min_time:.1f}–{max_time:.1f} giây"
        else:
            time_text = f"cố định {self.time_spin.value() / 1000:.1f} giây"
        multipv_text = f"{int(self.config.get('engine.multipv', 1))} phương án"
        ponder_text = "Ponder bật" if bool(self.config.get("engine.ponder", False)) else "Ponder tắt"
        self.profile_summary_label.setText(
            f"{int(self.config.get('engine.threads', 1))} luồng  ·  "
            f"{int(self.config.get('engine.hash_mb', 128))} MB  ·  {time_text}  ·  "
            f"{multipv_text}  ·  {ponder_text}"
        )

    def _refresh_ponder_badge_idle(self) -> None:
        active = str(self.config.get("analysis.active_time_control_preset", "")).upper()
        enabled = bool(active) and bool(self.config.get("engine.ponder", False))
        if enabled:
            self._set_ponder_badge("idle", "PONDER: CHỜ")
        else:
            self._set_ponder_badge("off", "PONDER: TẮT")

    def _update_ponder_badge(
        self,
        result: AnalysisResult | None,
        fen: str,
        status: str,
    ) -> None:
        if result is not None:
            elapsed = f"{result.thinking_time_ms / 1000:.1f}s"
            if result.source == "ponder":
                self._set_ponder_badge(
                    "hit", f"PONDER HIT · {len(result.lines)} PV · {elapsed}"
                )
            elif result.source == "ponder_partial":
                self._set_ponder_badge(
                    "quick", f"PONDER HIT · {len(result.lines)} PV · ĐANG BỔ SUNG"
                )
            elif result.source == "ponder_complete":
                self._set_ponder_badge(
                    "hit", f"PONDER HIT · ĐỦ {len(result.lines)} PV · {elapsed}"
                )
            elif result.source == "ponder_miss_fast":
                self._set_ponder_badge("quick", f"PONDER MISS · NHANH · {elapsed}")
            else:
                self._set_ponder_badge("final", f"KẾT QUẢ CUỐI · {elapsed}")
            return

        if "Ponder đang tính" in status or "Ponder tiếp tục tính" in status:
            progress = next(
                (
                    token
                    for token in status.split()
                    if "/" in token
                    and all(part.isdigit() for part in token.split("/", 1))
                ),
                "",
            )
            predicted = ""
            marker = "đối thủ đi "
            if marker in status:
                predicted = status.split(marker, 1)[1].split(".", 1)[0].strip()
            depth = next(
                (token for token in status.split() if token.startswith("D") and token[1:].isdigit()),
                "",
            )
            details = " · ".join(
                item for item in (progress, depth, predicted) if item
            )
            suffix = f" · {details}" if details else ""
            self._set_ponder_badge("thinking", f"PONDER: ĐANG TÍNH{suffix}")
            return
        if "Ponder đã sẵn sàng" in status or "Ponder đã chuẩn bị xong" in status:
            progress = next(
                (token for token in status.split() if "/" in token),
                "",
            )
            depth = next(
                (token for token in status.split() if token.startswith("D") and token[1:].isdigit()),
                "",
            )
            details = " · ".join(item for item in (progress, depth) if item)
            suffix = f" · {details}" if details else ""
            self._set_ponder_badge("ready", f"PONDER: SẴN SÀNG{suffix}")
            return
        if "Ponder cần FEN chính xác" in status:
            self._set_ponder_badge("unavailable", "PONDER: THIẾU FEN")
            return
        if "Ponder không thể" in status or "Ponder không tìm được" in status:
            self._set_ponder_badge("unavailable", "PONDER: KHÔNG DỰ ĐOÁN ĐƯỢC")
            return

        active = str(self.config.get("analysis.active_time_control_preset", "")).upper()
        enabled = bool(active) and bool(self.config.get("engine.ponder", False))
        if not enabled:
            self._set_ponder_badge("off", "PONDER: TẮT")
            return
        try:
            board = chess.Board(fen)
            player = chess.WHITE if self.side_combo.currentData() == "white" else chess.BLACK
            if board.turn != player:
                self._set_ponder_badge("unavailable", "PONDER: KHÔNG KHẢ DỤNG")
                return
        except ValueError:
            pass
        self._set_ponder_badge("idle", "PONDER: CHỜ")

    def _set_ponder_badge(self, state: str, text: str) -> None:
        palette = {
            "off": ("#334155", "#cbd5e1", "#64748b"),
            "idle": ("#1f2937", "#d1d5db", "#6b7280"),
            "thinking": ("#581c87", "#f3e8ff", "#a855f7"),
            "ready": ("#164e63", "#cffafe", "#06b6d4"),
            "hit": ("#14532d", "#dcfce7", "#22c55e"),
            "quick": ("#713f12", "#fef3c7", "#f59e0b"),
            "final": ("#1e3a8a", "#dbeafe", "#3b82f6"),
            "unavailable": ("#3f3f46", "#d4d4d8", "#71717a"),
        }
        background, foreground, border = palette.get(state, palette["idle"])
        self.ponder_status_label.setText(text)
        self.ponder_status_label.setStyleSheet(
            f"font-size: 11px; font-weight: 900; padding: 3px 7px; "
            f"color: {foreground}; background: {background}; "
            f"border: 1px solid {border}; border-radius: 5px;"
        )

    @Slot()
    def _set_side(self, *_args) -> None:
        self.engine_manager.stop_ponder()
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
        self._refresh_ponder_badge_idle()

    @Slot()
    def _new_game(self) -> None:
        self.engine_manager.stop_ponder()
        self._site_generation += 1
        self._visual_tracker.reset()
        self._template_recognizer.reset()
        self.engine_manager.new_game()
        self._last_realtime_fen = ""
        self._last_realtime_error = ""
        self._last_realtime_best_move = ""
        self._last_analysis_result = None
        self._force_realtime_refresh = False
        self._refresh_in_progress = False
        self._board_seen_logged = False
        self.fen_input.setPlainText(START_FEN)
        self.board_widget.set_position(START_FEN)
        self.best_move_label.setText("-")
        self.move_from_to_label.setText("-")
        self.evaluation_label.setText("-")
        self.candidate_moves_label.setText("-")
        self.difficulty_label.setText("-")
        self.depth_label.setText("-")
        self.details_label.setText("-")
        self.fen_status_label.setText("-")
        self._refresh_ponder_badge_idle()
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
        self.engine_manager.stop_ponder()
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
            self.engine_manager.stop_ponder()
            self.engine_manager.refresh_opening_book()
            self.engine_manager.clear_cache()
            self._load_settings_into_controls()
            self._refresh_ponder_badge_idle()
            self._warm_up_engine_async()
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
        self.engine_manager.stop_ponder()
        self._realtime_enabled = False
        self._realtime_timer.stop()
        self._web_overlay_dispatcher.stop()
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
            elapsed = time.monotonic() - self._realtime_started_at
            if elapsed >= 15.0 and not self._realtime_hang_reported:
                self._realtime_hang_reported = True
                self._log("Stockfish phản hồi chậm hơn 15 giây; yêu cầu tiếp theo đang được giữ lại.")
                self.fen_status_label.setText("Stockfish đang phản hồi chậm; ứng dụng vẫn tiếp tục chờ.")
            return

        side_to_move = chess.WHITE if self.side_combo.currentData() == "white" else chess.BLACK
        force_analysis = self._force_realtime_refresh
        refinement_analysis = self._force_realtime_refinement
        self._force_realtime_refresh = False
        self._force_realtime_refinement = False
        self._refresh_in_progress = force_analysis
        self._realtime_busy_ticks = 0
        self._realtime_started_at = time.monotonic()
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
            refinement_analysis=refinement_analysis,
            last_analysis_result=self._last_analysis_result,
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
        self._update_ponder_badge(result, fen, status)
        if result is None:
            position_changed = bool(previous_fen and fen != previous_fen)
            if position_changed:
                self._clear_best_move_display()
                if "tự đồng bộ lại" in status:
                    self._log("Đã khôi phục trạng thái ván từ bàn cờ hiện tại.")
            if self._refresh_in_progress:
                self._log(self._no_analysis_message(fen, status))
            retained_move = self._retained_board_move(
                previous_fen,
                fen,
                self.board_widget.best_move_uci,
            )
            if board_image is None:
                self.board_widget.set_position(fen, retained_move)
            else:
                self.board_widget.set_captured_position(fen, board_image, retained_move)
            if not retained_move:
                self.details_label.setText(
                    "DOM · đang theo dõi" if board_image is None else "Hình ảnh · đang theo dõi"
                )
            return

        self._start_bullet_speculation(result)
        self._render_analysis_result(result, board_image)
        if result.source == "ponder_miss_fast" and int(
            self.config.get("analysis.ponder_refinement_time_ms", 2000)
        ) > 0:
            self._force_realtime_refinement = True
        if self._refresh_in_progress:
            self._log(
                f"Đã tính xong: {result.best_move_san}, đánh giá {result.evaluation} "
                f"({self._source_name(result.source)})."
            )
        if result.best_move_uci != self._last_realtime_best_move:
            self._last_realtime_best_move = result.best_move_uci

    def _start_bullet_speculation(self, result: AnalysisResult) -> None:
        active = str(
            self.config.get("analysis.active_time_control_preset", "")
        ).upper()
        if active != "BULLET" or not bool(self.config.get("engine.ponder", False)):
            return
        target = self._bullet_speculation_target(result)
        if target is None:
            return
        origin_fen, target_fen = target
        self.engine_manager.start_ponder(
            target_fen,
            multipv=1,
            max_time_ms=int(self.config.get("analysis.ponder_max_time_ms", 10000)),
            origin_fen=origin_fen,
        )

    @staticmethod
    def _bullet_speculation_target(
        result: AnalysisResult,
    ) -> tuple[str, str] | None:
        if not result.lines or len(result.lines[0].pv) < 2:
            return None
        try:
            board = chess.Board(result.fen)
            suggested = chess.Move.from_uci(result.lines[0].pv[0])
            if suggested not in board.legal_moves:
                return None
            board.push(suggested)
            origin_fen = board.fen()
            predicted_reply = chess.Move.from_uci(result.lines[0].pv[1])
            if predicted_reply not in board.legal_moves:
                return None
            board.push(predicted_reply)
        except ValueError:
            return None
        return origin_fen, board.fen()

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

    @staticmethod
    def _retained_board_move(previous_fen: str, current_fen: str, current_move: str) -> str:
        """Keep the visible hint while polling the same position without re-analysis."""
        return current_move if previous_fen and previous_fen == current_fen else ""

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
        if (
            self._force_realtime_refresh or self._force_realtime_refinement
        ) and self._realtime_enabled:
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
        self._last_analysis_result = result
        self._show_move_on_web_board_async(result)
        self.best_move_label.setText(self._describe_best_move(result))
        self.move_from_to_label.setText(self._from_to_text(result.best_move_uci))
        self.evaluation_label.setText(result.evaluation)
        candidate_count = max(1, min(len(result.lines), 4))
        self.candidate_moves_label.setMinimumHeight(
            86 if candidate_count == 1 else 72 * candidate_count + 30
        )
        self.candidate_moves_label.setText(self._candidate_moves_text(result))
        difficulty_text, difficulty_color = self._position_difficulty(result)
        self.difficulty_label.setText(difficulty_text)
        self.difficulty_label.setStyleSheet(
            f"font-weight: 800; color: {difficulty_color}; padding: 8px 10px; "
            "background: #111827; border: 1px solid #334155; border-radius: 6px;"
        )
        self.depth_label.setText(str(result.depth or "-"))
        source_text = {
            "cache": "Bộ nhớ đệm",
            "book": "Sách khai cuộc",
            "tablebase": "Cơ sở dữ liệu tàn cuộc Syzygy",
            "engine": "Stockfish",
            "engine_book_check": "Stockfish kiểm tra sách khai cuộc",
            "ponder": "Ponder hit",
            "ponder_partial": "Ponder hit chưa đủ phương án",
            "ponder_complete": "Ponder hit đã bổ sung đủ phương án",
            "ponder_miss_fast": "Gợi ý nhanh sau ponder miss",
            "ponder_miss_refined": "Kết quả tinh chỉnh sau ponder miss",
        }.get(result.source, result.source)
        self.details_label.setText(f"{source_text} · {result.thinking_time_ms} ms")
        if board_image is None:
            self.board_widget.set_position(result.fen, result.best_move_uci)
        else:
            self.board_widget.set_captured_position(result.fen, board_image, result.best_move_uci)
        # Defer the web overlay update so that the board and labels paint
        # immediately.  The WebSocket round-trip (connect + 800-line JS script
        # + browser execution) takes 100–300 ms and must not block the UI.
    def _clear_best_move_display(self) -> None:
        self.best_move_label.setText("Đang chờ nước mới...")
        self.move_from_to_label.setText("-")
        self.evaluation_label.setText("-")
        self.candidate_moves_label.setText("-")
        self.difficulty_label.setText("-")
        self.depth_label.setText("-")
        self.details_label.setText("-")
        self._last_realtime_best_move = ""
        self._last_analysis_result = None

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
            "ponder": "Ponder hit",
            "ponder_partial": "Ponder hit chưa đủ phương án",
            "ponder_complete": "Ponder hit đã bổ sung đủ phương án",
            "ponder_miss_fast": "gợi ý nhanh sau ponder miss",
            "ponder_miss_refined": "kết quả tinh chỉnh sau ponder miss",
        }.get(source, source)

    def _show_move_on_web_board_async(self, result: AnalysisResult) -> None:
        if not self.web_overlay_button.isChecked():
            return
        try:
            try:
                human_index = self._human_candidate_index(
                    chess.Board(result.fen), result.lines[:3]
                )
            except ValueError:
                human_index = 1
            moves = [
                {
                    "uci": line.move_uci,
                    "label": line.move_san,
                    "score": line.score,
                    "rank": index,
                    "color": self._candidate_color(index),
                    "role": " · ".join(
                        role
                        for role, applies in (
                            ("E", index == 1),
                            ("T", index == human_index),
                        )
                        if applies
                    ),
                }
                for index, line in enumerate(result.lines[:3], start=1)
            ]
            preferred_site = str(self.config.get("browser.preferred_site", "auto"))
            target_id = self._browser_target_id
            perspective = str(self.side_combo.currentData())
        except Exception:
            return

        self._web_overlay_dispatcher.show(
            moves,
            perspective=perspective,
            preferred_site=preferred_site,
            target_id=target_id,
        )

    def _show_move_on_web_board(self, result: AnalysisResult) -> None:
        if not self.web_overlay_button.isChecked():
            return
        try:
            try:
                human_index = self._human_candidate_index(
                    chess.Board(result.fen), result.lines[:3]
                )
            except ValueError:
                human_index = 1
            moves = [
                {
                    "uci": line.move_uci,
                    "label": line.move_san,
                    "score": line.score,
                    "rank": index,
                    "color": self._candidate_color(index),
                    "role": " · ".join(
                        role
                        for role, applies in (
                            ("E", index == 1),
                            ("T", index == human_index),
                        )
                        if applies
                    ),
                }
                for index, line in enumerate(result.lines[:3], start=1)
            ]
            DomBoardReader(
                preferred_site=str(self.config.get("browser.preferred_site", "auto")),
                target_id=self._browser_target_id,
            ).show_moves(
                moves,
                perspective=str(self.side_combo.currentData()),
            )
        except Exception:
            return

    def _bullet_fast_path(self) -> bool:
        return str(
            self.config.get("analysis.active_time_control_preset", "")
        ).upper() == "BULLET"

    def _clear_move_from_web_board_async(self) -> None:
        preferred_site = str(self.config.get("browser.preferred_site", "auto"))
        target_id = self._browser_target_id

        self._web_overlay_dispatcher.clear(
            preferred_site=preferred_site,
            target_id=target_id,
        )

    def _clear_move_from_web_board(self) -> None:
        try:
            DomBoardReader(
                preferred_site=str(self.config.get("browser.preferred_site", "auto")),
                target_id=self._browser_target_id,
            ).clear_best_move()
        except Exception:
            return

    def _candidate_moves_text(self, result: AnalysisResult) -> str:
        try:
            board = chess.Board(result.fen)
        except ValueError:
            return "Không thể đọc các phương án vì FEN không hợp lệ."

        human_index = self._human_candidate_index(board, result.lines[:3])
        best_cp = result.lines[0].score_cp if result.lines else None
        descriptions = []
        for index, line in enumerate(result.lines[:3], start=1):
            move_text = self._describe_move(board, line.move_uci, line.move_san)
            color = self._candidate_color(index)
            ranking = "TỐT NHẤT" if index == 1 else f"LỰA CHỌN {index}"
            badges = []
            if index == 1:
                badges.append(
                    '<span style="background:#14532d; color:#dcfce7; padding:2px 6px; '
                    'border-radius:4px; font-size:11px; font-weight:800;">ENGINE</span>'
                )
            if index == human_index:
                badges.append(
                    '<span style="background:#1e3a8a; color:#dbeafe; padding:2px 6px; '
                    'border-radius:4px; font-size:11px; font-weight:800;">THỰC DỤNG</span>'
                )
            role_text = " &nbsp;" + " &nbsp;".join(badges) if badges else ""
            practical_note = ""
            if index == human_index:
                if best_cp is not None and line.score_cp is not None:
                    loss_cp = max(0, int(best_cp) - int(line.score_cp))
                    practical_note = (
                        '<br><span style="color:#93c5fd; font-size:12px;">'
                        + (
                            "Cũng là nước tự nhiên, thực dụng nhất."
                            if loss_cp == 0
                            else f"Thực dụng, dễ chơi; kém #1 khoảng {loss_cp / 100:.2f} điểm."
                        )
                        + "</span>"
                    )
            descriptions.append(
                f'<div style="margin:3px 0 7px 0; padding:7px 9px; '
                f'border-left:5px solid {color}; background:#111c30;">'
                f'<span style="font-size:16px; font-weight:800; color:{color};">'
                f'#{index} &nbsp; {html.escape(ranking)}</span>{role_text}<br>'
                f'<span style="color:#f8fafc; font-weight:650;">{html.escape(move_text)}</span>'
                f'<span style="color:#94a3b8;"> &nbsp;·&nbsp; Đánh giá </span>'
                f'<span style="font-size:16px; font-weight:800; color:{color};">'
                f'{html.escape(line.score)}</span>{practical_note}</div>'
            )
        if not descriptions:
            return "Không có phương án hợp lệ."
        return (
            '<div style="color:#94a3b8; margin:0 0 5px 2px;">'
            'Điểm + có lợi cho bên đang đi · điểm − có lợi cho đối thủ<br>'
            '<span style="font-size:11px;">“Thực dụng” là phương án tự nhiên, dễ chơi và có mức mất điểm chấp nhận được.</span></div>'
            + "".join(descriptions)
        )

    @classmethod
    def _human_candidate_index(cls, board: chess.Board, lines: list[object]) -> int:
        if len(lines) < 2:
            return 0
        best_cp = getattr(lines[0], "score_cp", None)
        if best_cp is None:
            return 1

        tactical = board.is_check() or sum(
            1 for move in board.legal_moves if board.is_capture(move)
        ) >= 5
        max_loss_cp = 30 if tactical else 60
        best_index = 1
        best_practical_score = cls._move_naturalness(board, getattr(lines[0], "move_uci", ""))

        for index, line in enumerate(lines[1:], start=2):
            score_cp = getattr(line, "score_cp", None)
            if score_cp is None:
                continue
            loss_cp = max(0, int(best_cp) - int(score_cp))
            if loss_cp > max_loss_cp:
                continue
            naturalness = cls._move_naturalness(board, getattr(line, "move_uci", ""))
            practical_score = naturalness - loss_cp / 18.0 - (index - 1) * 0.15
            if practical_score > best_practical_score + 0.25:
                best_practical_score = practical_score
                best_index = index
        return best_index

    @staticmethod
    def _move_naturalness(board: chess.Board, move_uci: str) -> float:
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            return -10.0
        if move not in board.legal_moves:
            return -10.0
        piece = board.piece_at(move.from_square)
        if piece is None:
            return -10.0

        score = 0.0
        if board.is_castling(move):
            score += 6.0
        if board.is_capture(move):
            score += 1.5
        if board.gives_check(move):
            score += 1.0
        if move.promotion:
            score += 4.0

        from_rank = chess.square_rank(move.from_square)
        to_file = chess.square_file(move.to_square)
        back_rank = 0 if piece.color == chess.WHITE else 7
        if piece.piece_type in {chess.KNIGHT, chess.BISHOP} and from_rank == back_rank:
            score += 3.0
        if piece.piece_type == chess.PAWN and to_file in {3, 4}:
            score += 2.0
        if piece.piece_type == chess.QUEEN and board.fullmove_number <= 10:
            score -= 2.5
        if piece.piece_type == chess.KING and not board.is_castling(move):
            score -= 2.0

        mover = board.turn
        next_board = board.copy(stack=False)
        next_board.push(move)
        if next_board.is_attacked_by(not mover, move.to_square) and not next_board.is_attacked_by(
            mover, move.to_square
        ):
            score -= 2.0
        return score

    @staticmethod
    def _candidate_color(index: int) -> str:
        return {
            1: "#4ade80",
            2: "#38bdf8",
            3: "#facc15",
            4: "#fb7185",
        }.get(index, "#cbd5e1")

    @staticmethod
    def _position_difficulty(result: AnalysisResult) -> tuple[str, str]:
        try:
            board = chess.Board(result.fen)
        except ValueError:
            return "Chưa xác định — FEN không hợp lệ", "#94a3b8"

        legal_count = board.legal_moves.count()
        if legal_count <= 1:
            return "DỄ — nước đi gần như bắt buộc", "#4ade80"

        capture_count = sum(1 for move in board.legal_moves if board.is_capture(move))
        tactical_pressure = board.is_check() or capture_count >= 5
        scored_lines = [line for line in result.lines if line.score_cp is not None]
        gap = None
        if len(scored_lines) >= 2:
            gap = int(scored_lines[0].score_cp) - int(scored_lines[1].score_cp)

        if gap is not None and gap >= 120:
            return (
                "KHÓ — phương án số 1 vượt trội; các lựa chọn sau mất ít nhất "
                f"{gap / 100:.2f} điểm",
                "#f87171",
            )
        if tactical_pressure:
            reason = "đang bị chiếu" if board.is_check() else "có nhiều nước bắt quân"
            return f"KHÓ — thế chiến thuật, {reason}", "#f87171"
        if len(scored_lines) >= 3:
            third_gap = int(scored_lines[0].score_cp) - int(scored_lines[2].score_cp)
            if gap is not None and gap <= 35 and third_gap <= 70:
                return "DỄ — có nhiều nước gần tương đương để lựa chọn", "#4ade80"
        if gap is not None and gap <= 80:
            return "TRUNG BÌNH — vài phương án chơi được, ưu tiên phương án số 1", "#facc15"
        if capture_count <= 2 and legal_count < 35:
            return "DỄ — thế tương đối yên tĩnh", "#4ade80"
        return "TRUNG BÌNH — cần cân nhắc thứ tự nước đi", "#facc15"

    def _describe_best_move(self, result: AnalysisResult) -> str:
        try:
            board = chess.Board(result.fen)
        except ValueError:
            return result.best_move_san
        return self._describe_move(board, result.best_move_uci, result.best_move_san)

    def _describe_move(self, board: chess.Board, move_uci: str, fallback: str) -> str:
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            return fallback
        piece = board.piece_at(move.from_square)
        if piece is None:
            return fallback

        from_square = chess.square_name(move.from_square)
        to_square = chess.square_name(move.to_square)
        text = f"{self._piece_name(piece)}: {from_square} → {to_square}"

        captured_square = move.to_square
        if board.is_en_passant(move):
            captured_square += -8 if piece.color == chess.WHITE else 8
        captured = board.piece_at(captured_square)
        if captured is not None:
            text += (
                f", ăn {self._piece_name(captured)}"
                f" tại {chess.square_name(captured_square)}"
            )
        if board.is_castling(move):
            wing = "cánh vua" if chess.square_file(move.to_square) > chess.square_file(move.from_square) else "cánh hậu"
            text += f", nhập thành {wing}"
        if move.promotion is not None:
            text += f", phong cấp thành {self._piece_type_name(move.promotion)}"
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
        message = " ".join(str(message).split())
        if not message or message == self._last_log_message:
            return
        self._last_log_message = message
        marker = self._log_marker(message)
        timestamp = time.strftime("%H:%M:%S")
        self.status_output.appendPlainText(f"{timestamp}  {marker}  {message}")
        self.status_output.moveCursor(QTextCursor.MoveOperation.End)
        self.status_output.ensureCursorVisible()

    @staticmethod
    def _log_marker(message: str) -> str:
        normalized = message.casefold()
        if any(word in normalized for word in ("thất bại", "không ", "chưa ", "chậm", "lỗi")):
            return "⚠"
        if normalized.startswith(("đã ", "bạn đang ")):
            return "✓"
        if normalized.startswith(("đang ", "theo dõi ")):
            return "…"
        return "•"
