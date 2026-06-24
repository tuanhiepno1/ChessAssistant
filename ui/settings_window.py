from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
)

from core.config_manager import ConfigManager
from core.hardware_profile import detect_hardware


class SettingsWindow(QDialog):
    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.hardware = detect_hardware()
        self.setWindowTitle("Cài đặt")
        self.resize(590, 520)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._engine_tab(), "Stockfish")
        tabs.addTab(self._analysis_tab(), "Phân tích")
        tabs.addTab(self._time_control_presets_tab(), "Nhịp độ")
        tabs.addTab(self._book_tab(), "Khai cuộc")
        tabs.addTab(self._tablebase_tab(), "Tàn cuộc")
        tabs.addTab(self._vision_tab(), "Nhận diện")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Lưu")
        buttons.button(QDialogButtonBox.Cancel).setText("Hủy")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _engine_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.auto_summary = QLabel()
        self.auto_summary.setWordWrap(True)
        self.auto_summary.setStyleSheet(
            "padding: 8px; color: #bbf7d0; background: #052e16; border: 1px solid #166534;"
        )
        layout.addWidget(self.auto_summary)

        self.advanced_engine = QGroupBox("Cấu hình mặc định mạnh")
        form = QFormLayout(self.advanced_engine)
        self.stockfish_path = self._path_picker(file_mode=True)
        self.threads = QSpinBox()
        self.threads.setRange(1, 64)
        self.hash_mb = QSpinBox()
        self.hash_mb.setRange(16, 65536)
        self.hash_mb.setSuffix(" MB")
        self.multipv = QSpinBox()
        self.multipv.setRange(1, 10)
        self.skill_level = QSpinBox()
        self.skill_level.setRange(0, 20)
        self.threads.setToolTip("Số luồng CPU Stockfish sử dụng. Nhiều quá có thể làm chậm trình duyệt.")
        self.hash_mb.setToolTip("RAM dành cho bảng nhớ của Stockfish. Không phải càng lớn càng mạnh.")
        self.multipv.setToolTip("Số phương án hiển thị. Chọn 1 cho nước mạnh nhất và tốc độ cao nhất.")
        self.skill_level.setToolTip("20 là sức mạnh tối đa của Stockfish.")
        form.addRow("Đường dẫn Stockfish", self.stockfish_path)
        form.addRow("Số luồng xử lý", self.threads)
        form.addRow("Bộ nhớ băm", self.hash_mb)
        form.addRow("Số phương án gợi ý", self.multipv)
        form.addRow("Mức sức mạnh", self.skill_level)
        layout.addWidget(self.advanced_engine)
        self._refresh_auto_summary()
        return tab

    def _analysis_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.time_ms = QSpinBox()
        self.time_ms.setRange(100, 60000)
        self.time_ms.setSuffix(" ms")
        self.time_ms.setToolTip(
            "Thời gian càng cao thì kết quả càng ổn định. Chế độ mạnh nhất tự đặt theo cấu hình máy."
        )
        self.adaptive_time_enabled = QCheckBox()
        self.adaptive_min_time_ms = QSpinBox()
        self.adaptive_min_time_ms.setRange(100, 60000)
        self.adaptive_min_time_ms.setSuffix(" ms")
        self.adaptive_max_time_ms = QSpinBox()
        self.adaptive_max_time_ms.setRange(100, 120000)
        self.adaptive_max_time_ms.setSuffix(" ms")
        self.adaptive_realtime_max_time_ms = QSpinBox()
        self.adaptive_realtime_max_time_ms.setRange(100, 60000)
        self.adaptive_realtime_max_time_ms.setSuffix(" ms")
        self.adaptive_probe_time_ms = QSpinBox()
        self.adaptive_probe_time_ms.setRange(100, 10000)
        self.adaptive_probe_time_ms.setSuffix(" ms")
        self.cache_enabled = QCheckBox()
        mode_note = QLabel(
            "Bật/tắt Thời gian thông minh và chỉnh thời gian cố định ngay trên màn hình chính."
        )
        mode_note.setWordWrap(True)
        mode_note.setStyleSheet(
            "padding: 8px; color: #bfdbfe; background: #172554; "
            "border: 1px solid #1d4ed8; border-radius: 5px;"
        )
        form.addRow(mode_note)
        form.addRow("Nhanh nhất khi dễ", self.adaptive_min_time_ms)
        form.addRow("Lâu nhất khi khó", self.adaptive_max_time_ms)
        form.addRow("Trần realtime", self.adaptive_realtime_max_time_ms)
        form.addRow("Probe nhanh ban đầu", self.adaptive_probe_time_ms)
        form.addRow("Lưu kết quả theo FEN", self.cache_enabled)
        return tab

    def _book_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.book_enabled = QCheckBox()
        self.book_path = self._path_picker(file_mode=True)
        self.prefer_book = QCheckBox()
        self.verify_book = QCheckBox()
        self.book_max_loss = QSpinBox()
        self.book_max_loss.setRange(0, 200)
        self.book_max_loss.setSuffix(" centipawn")
        self.book_verify_time = QSpinBox()
        self.book_verify_time.setRange(100, 5000)
        self.book_verify_time.setSuffix(" ms")
        form.addRow("Bật sách khai cuộc", self.book_enabled)
        form.addRow("Đường dẫn sách", self.book_path)
        form.addRow("Ưu tiên nước trong sách", self.prefer_book)
        form.addRow("Kiểm tra lại bằng Stockfish", self.verify_book)
        form.addRow("Sai lệch tối đa cho phép", self.book_max_loss)
        form.addRow("Thời gian kiểm tra", self.book_verify_time)
        return tab

    def _time_control_presets_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        explanation = QLabel(
            "Mỗi preset lưu cấu hình độc lập. Khi bật Thời gian thông minh, "
            "Stockfish dùng Tối thiểu → Trần realtime; Thời gian cố định chỉ dùng khi tắt chế độ này.\n"
            "Ponder hit dùng kết quả đã tính trước. Ponder miss hiện gợi ý nhanh trước, "
            "sau đó mới tính kết quả đầy đủ."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(
            "padding: 8px; color: #bfdbfe; background: #172554; "
            "border: 1px solid #1d4ed8; border-radius: 5px;"
        )
        layout.addWidget(explanation)
        preset_tabs = QTabWidget()
        self.time_control_fields: dict[str, dict[str, QWidget]] = {}
        for name, label in {
            "RAPID": "Rapid",
            "BLITZ": "Blitz",
            "BULLET": "Bullet",
        }.items():
            panel = QWidget()
            form = QFormLayout(panel)
            fields: dict[str, QWidget] = {}

            threads = QSpinBox()
            threads.setRange(1, 64)
            fields["threads"] = threads
            hash_mb = QSpinBox()
            hash_mb.setRange(16, 65536)
            hash_mb.setSuffix(" MB")
            fields["hash_mb"] = hash_mb
            multipv = QSpinBox()
            multipv.setRange(1, 3)
            multipv.setSuffix(" phương án")
            fields["multipv"] = multipv
            fields["ponder"] = QCheckBox()
            fields["adaptive_time_enabled"] = QCheckBox()
            for key in ("time_ms", "min_time_ms", "probe_time_ms", "realtime_max_time_ms", "hard_max_time_ms"):
                spin = QSpinBox()
                spin.setRange(100, 120000)
                spin.setSuffix(" ms")
                fields[key] = spin
            for key in (
                "ponder_max_time_ms",
                "ponder_hit_settle_ms",
                "ponder_miss_quick_time_ms",
                "ponder_prediction_time_ms",
                "ponder_completion_time_ms",
                "ponder_stop_timeout_ms",
                "ponder_refinement_time_ms",
            ):
                spin = QSpinBox()
                spin.setRange(0, 120000)
                spin.setSuffix(" ms")
                fields[key] = spin
            ponder_ready_depth = QSpinBox()
            ponder_ready_depth.setRange(1, 50)
            ponder_ready_depth.setSuffix(" ply")
            fields["ponder_ready_depth"] = ponder_ready_depth

            form.addRow("Số luồng Stockfish", fields["threads"])
            form.addRow("Bộ nhớ Hash", fields["hash_mb"])
            form.addRow("Số phương án MultiPV", fields["multipv"])
            form.addRow("Bật tính trước Ponder", fields["ponder"])
            form.addRow("Bật thời gian thông minh", fields["adaptive_time_enabled"])
            form.addRow("Thời gian cố định (khi tắt thông minh)", fields["time_ms"])
            form.addRow("Thông minh: thời gian tối thiểu", fields["min_time_ms"])
            form.addRow("Thông minh: thăm dò ban đầu", fields["probe_time_ms"])
            form.addRow("Thông minh: trần khi theo dõi ván", fields["realtime_max_time_ms"])
            form.addRow("Thông minh: trần cứng khi tính tay", fields["hard_max_time_ms"])
            form.addRow("Ponder: thời gian chạy tối đa", fields["ponder_max_time_ms"])
            form.addRow("Ponder hit: chờ Stockfish ổn định", fields["ponder_hit_settle_ms"])
            form.addRow("Ponder miss: gợi ý nhanh đầu tiên", fields["ponder_miss_quick_time_ms"])
            form.addRow("Ponder: dự đoán nước đối thủ", fields["ponder_prediction_time_ms"])
            form.addRow("Ponder hit thiếu PV: thời gian bổ sung", fields["ponder_completion_time_ms"])
            form.addRow("Ponder miss: chờ dừng tìm kiếm cũ", fields["ponder_stop_timeout_ms"])
            form.addRow("Ponder miss: tinh chỉnh nền (0 = tắt)", fields["ponder_refinement_time_ms"])
            form.addRow("Ponder: độ sâu tối thiểu để báo sẵn sàng", fields["ponder_ready_depth"])
            self.time_control_fields[name] = fields
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            preset_tabs.addTab(scroll, label)
        layout.addWidget(preset_tabs)
        return tab

    def _tablebase_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.tablebase_enabled = QCheckBox()
        self.syzygy_path = self._path_picker(file_mode=False)
        self.tablebase_max_pieces = QSpinBox()
        self.tablebase_max_pieces.setRange(3, 7)
        self.tablebase_max_pieces.setSuffix(" quân")
        form.addRow("Bật cơ sở dữ liệu tàn cuộc", self.tablebase_enabled)
        form.addRow("Đường dẫn Syzygy", self.syzygy_path)
        form.addRow("Số quân tối đa đã cài", self.tablebase_max_pieces)
        return tab

    def _vision_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.yolo_model_path = self._path_picker(file_mode=True)
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(0.05, 0.99)
        self.confidence.setSingleStep(0.05)
        self.confidence.setDecimals(2)
        self.perspective = QComboBox()
        self.perspective.addItem("Nhìn từ phía Trắng", "white")
        self.perspective.addItem("Nhìn từ phía Đen", "black")
        form.addRow("Đường dẫn mô hình YOLO", self.yolo_model_path)
        form.addRow("Ngưỡng tin cậy", self.confidence)
        form.addRow("Góc nhìn bàn cờ", self.perspective)
        return tab

    def _path_picker(self, file_mode: bool) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit()
        button = QPushButton("Chọn")
        container.line_edit = line_edit  # type: ignore[attr-defined]

        def browse() -> None:
            if file_mode:
                path, _ = QFileDialog.getOpenFileName(self, "Chọn tệp")
            else:
                path = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
            if path:
                line_edit.setText(path)

        button.clicked.connect(browse)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        return container

    def _line_text(self, widget: QWidget) -> str:
        return widget.line_edit.text()  # type: ignore[attr-defined]

    def _set_line_text(self, widget: QWidget, value: str) -> None:
        widget.line_edit.setText(value)  # type: ignore[attr-defined]

    def _load(self) -> None:
        self._set_line_text(self.stockfish_path, str(self.config.get("engine.stockfish_path", "")))
        default = self.config.get("default_config", {})
        if not isinstance(default, dict):
            default = {}
        self.threads.setValue(int(default.get("threads", 16)))
        self.hash_mb.setValue(int(default.get("hash_mb", 8000)))
        self.multipv.setValue(int(default.get("multipv", 1)))
        self.skill_level.setValue(int(default.get("skill_level", 20)))
        self.time_ms.setValue(int(default.get("time_ms", 4500)))
        self.adaptive_time_enabled.setChecked(bool(default.get("adaptive_time_enabled", True)))
        adaptive = self.adaptive_time_enabled.isChecked()
        for widget in (
            self.adaptive_min_time_ms,
            self.adaptive_max_time_ms,
            self.adaptive_realtime_max_time_ms,
            self.adaptive_probe_time_ms,
        ):
            widget.setEnabled(adaptive)
        self.adaptive_min_time_ms.setValue(int(default.get("min_time_ms", 700)))
        self.adaptive_max_time_ms.setValue(int(default.get("hard_max_time_ms", 6000)))
        self.adaptive_realtime_max_time_ms.setValue(int(default.get("realtime_max_time_ms", 4200)))
        self.adaptive_probe_time_ms.setValue(int(default.get("probe_time_ms", 300)))
        self.cache_enabled.setChecked(bool(self.config.get("analysis.cache_enabled", True)))
        self._load_time_control_presets()
        self.book_enabled.setChecked(bool(self.config.get("book.enabled", False)))
        self._set_line_text(self.book_path, str(self.config.get("book.path", "")))
        self.prefer_book.setChecked(bool(self.config.get("book.prefer_book", True)))
        self.verify_book.setChecked(bool(self.config.get("book.verify_with_engine", True)))
        self.book_max_loss.setValue(int(self.config.get("book.max_eval_loss_cp", 10)))
        self.book_verify_time.setValue(int(self.config.get("book.verify_time_ms", 500)))
        self.tablebase_enabled.setChecked(bool(self.config.get("tablebase.enabled", False)))
        self._set_line_text(self.syzygy_path, str(self.config.get("tablebase.syzygy_path", "")))
        self.tablebase_max_pieces.setValue(int(self.config.get("tablebase.max_pieces", 5)))
        self._set_line_text(self.yolo_model_path, str(self.config.get("vision.yolo_model_path", "")))
        self.confidence.setValue(float(self.config.get("vision.confidence_threshold", 0.5)))
        perspective = str(self.config.get("vision.perspective", "white"))
        index = self.perspective.findData(perspective)
        self.perspective.setCurrentIndex(max(index, 0))
        self.advanced_engine.setVisible(True)

    def _save(self) -> None:
        active_preset = str(
            self.config.get("analysis.active_time_control_preset", "")
        ).upper()
        self.config.set("engine.stockfish_path", self._line_text(self.stockfish_path))
        self.config.update_default_config({
            "threads": self.threads.value(),
            "hash_mb": self.hash_mb.value(),
            "multipv": self.multipv.value(),
            "ponder": False,
            "skill_level": self.skill_level.value(),
            "adaptive_time_enabled": self.adaptive_time_enabled.isChecked(),
            "time_ms": self.time_ms.value(),
            "min_time_ms": self.adaptive_min_time_ms.value(),
            "hard_max_time_ms": self.adaptive_max_time_ms.value(),
            "realtime_max_time_ms": self.adaptive_realtime_max_time_ms.value(),
            "probe_time_ms": self.adaptive_probe_time_ms.value(),
        })
        self.config.set("analysis.cache_enabled", self.cache_enabled.isChecked())
        self._save_time_control_presets()
        self.config.set("book.enabled", self.book_enabled.isChecked())
        self.config.set("book.path", self._line_text(self.book_path))
        self.config.set("book.prefer_book", self.prefer_book.isChecked())
        self.config.set("book.verify_with_engine", self.verify_book.isChecked())
        self.config.set("book.max_eval_loss_cp", self.book_max_loss.value())
        self.config.set("book.verify_time_ms", self.book_verify_time.value())
        self.config.set("tablebase.enabled", self.tablebase_enabled.isChecked())
        self.config.set("tablebase.syzygy_path", self._line_text(self.syzygy_path))
        self.config.set("tablebase.max_pieces", self.tablebase_max_pieces.value())
        self.config.set("vision.yolo_model_path", self._line_text(self.yolo_model_path))
        self.config.set("vision.confidence_threshold", self.confidence.value())
        self.config.set("vision.perspective", self.perspective.currentData())
        if active_preset in {"RAPID", "BLITZ", "BULLET"}:
            self.config.apply_time_control_preset(active_preset)
        else:
            self.config.apply_default_config()
        self.config.save()
        self.accept()

    def _load_time_control_presets(self) -> None:
        fallbacks = {
            "threads": self.config.get("engine.threads", 1),
            "hash_mb": self.config.get("engine.hash_mb", 128),
            "multipv": self.config.get("engine.multipv", 1),
            "time_ms": self.config.get("analysis.time_ms", 1000),
            "min_time_ms": self.config.get("analysis.adaptive_min_time_ms", 700),
            "probe_time_ms": self.config.get("analysis.adaptive_probe_time_ms", 300),
            "realtime_max_time_ms": self.config.get("analysis.adaptive_realtime_max_time_ms", 4200),
            "hard_max_time_ms": self.config.get("analysis.adaptive_max_time_ms", 6000),
            "ponder_max_time_ms": self.config.get("analysis.ponder_max_time_ms", 10000),
            "ponder_hit_settle_ms": self.config.get("analysis.ponder_hit_settle_ms", 25),
            "ponder_miss_quick_time_ms": self.config.get("analysis.ponder_miss_quick_time_ms", 650),
            "ponder_prediction_time_ms": self.config.get("analysis.ponder_prediction_time_ms", 200),
            "ponder_completion_time_ms": self.config.get("analysis.ponder_completion_time_ms", 650),
            "ponder_stop_timeout_ms": self.config.get("analysis.ponder_stop_timeout_ms", 200),
            "ponder_refinement_time_ms": self.config.get("analysis.ponder_refinement_time_ms", 2000),
            "ponder_ready_depth": self.config.get("analysis.ponder_ready_depth", 8),
        }
        for name, fields in self.time_control_fields.items():
            preset = self.config.get(f"time_control_presets.{name}", {})
            if not isinstance(preset, dict):
                preset = {}
            for key, fallback in fallbacks.items():
                field = fields[key]
                assert isinstance(field, QSpinBox)
                field.setValue(int(preset.get(key, fallback)))
            adaptive = fields["adaptive_time_enabled"]
            assert isinstance(adaptive, QCheckBox)
            adaptive.setChecked(bool(preset.get("adaptive_time_enabled", False)))
            ponder = fields["ponder"]
            assert isinstance(ponder, QCheckBox)
            ponder.setChecked(bool(preset.get("ponder", False)))

    def _save_time_control_presets(self) -> None:
        for name, fields in self.time_control_fields.items():
            values: dict[str, object] = {}
            for key in (
                "threads", "hash_mb", "multipv", "time_ms", "min_time_ms",
                "probe_time_ms", "realtime_max_time_ms", "hard_max_time_ms",
                "ponder_max_time_ms", "ponder_hit_settle_ms",
                "ponder_miss_quick_time_ms", "ponder_prediction_time_ms",
                "ponder_completion_time_ms", "ponder_ready_depth",
                "ponder_stop_timeout_ms", "ponder_refinement_time_ms",
            ):
                field = fields[key]
                assert isinstance(field, QSpinBox)
                values[key] = field.value()
            adaptive = fields["adaptive_time_enabled"]
            assert isinstance(adaptive, QCheckBox)
            values["adaptive_time_enabled"] = adaptive.isChecked()
            ponder = fields["ponder"]
            assert isinstance(ponder, QCheckBox)
            values["ponder"] = ponder.isChecked()
            self.config.update_time_control_preset(name, values)

    def _refresh_auto_summary(self) -> None:
        recommendation = self.hardware.recommend_max_strength()
        self.auto_summary.setText(
            f"{self.hardware.cpu_name.strip()} • {self.hardware.physical_cores} nhân/"
            f"{self.hardware.logical_processors} luồng • RAM {self.hardware.ram_total_gb:.1f} GB\n"
            f"{recommendation.threads} luồng Stockfish, bộ nhớ băm {recommendation.hash_mb} MB, "
            f"{recommendation.time_ms / 1000:.1f} giây mỗi nước — cấu hình mặc định mạnh."
        )
