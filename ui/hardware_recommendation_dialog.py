from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.hardware_profile import EngineRecommendation, HardwareProfile


class HardwareRecommendationDialog(QDialog):
    def __init__(self, config: ConfigManager, profile: HardwareProfile, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.profile = profile
        self.editors: dict[str, QSpinBox] = {}
        self.recommendation = profile.recommend_max_strength()

        self.setWindowTitle("Cấu hình mặc định Stockfish")
        self.setMinimumWidth(520)
        self.resize(560, 690)
        layout = QVBoxLayout(self)

        hardware = QGroupBox("Cấu hình máy hiện tại")
        hardware_form = QFormLayout(hardware)
        cpu_label = QLabel(profile.cpu_name.strip())
        cpu_label.setWordWrap(True)
        hardware_form.addRow("CPU", cpu_label)
        hardware_form.addRow(
            "Nhân / luồng",
            QLabel(f"{profile.physical_cores} nhân / {profile.logical_processors} luồng"),
        )
        hardware_form.addRow(
            "RAM",
            QLabel(f"{profile.ram_total_gb:.1f} GB tổng / {profile.ram_free_gb:.1f} GB còn trống"),
        )
        gpu_label = QLabel(", ".join(profile.gpu_names) or "Không xác định")
        gpu_label.setWordWrap(True)
        os_label = QLabel(profile.os_name)
        os_label.setWordWrap(True)
        hardware_form.addRow("GPU", gpu_label)
        hardware_form.addRow("Hệ điều hành", os_label)
        layout.addWidget(hardware)

        layout.addWidget(self._default_group(self.recommendation))

        note = QLabel(
            "Đây là cấu hình mạnh duy nhất dùng khi không bật Rapid, Blitz hoặc Bullet."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #94a3b8;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Lưu và sử dụng")
        buttons.button(QDialogButtonBox.Cancel).setText("Giữ cấu hình hiện tại")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _default_group(self, recommended: EngineRecommendation) -> QWidget:
        group = QGroupBox("Mặc định mạnh")
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        saved = self.config.get("default_config", {})
        if not isinstance(saved, dict):
            saved = {}

        threads = QSpinBox()
        threads.setRange(1, max(64, self.profile.logical_processors))
        threads.setValue(int(saved.get("threads", recommended.threads)))
        hash_mb = QSpinBox()
        hash_mb.setRange(128, 65536)
        hash_mb.setSingleStep(128)
        hash_mb.setSuffix(" MB")
        hash_mb.setValue(int(saved.get("hash_mb", recommended.hash_mb)))
        time_ms = QSpinBox()
        time_ms.setRange(100, 60000)
        time_ms.setSingleStep(100)
        time_ms.setSuffix(" ms")
        time_ms.setValue(int(saved.get("time_ms", recommended.time_ms)))
        multipv = QSpinBox()
        multipv.setRange(1, 10)
        multipv.setValue(int(saved.get("multipv", recommended.multipv)))

        recommendation = QLabel(
            f"Khuyến nghị: {recommended.threads} luồng · {recommended.hash_mb} MB · "
            f"{recommended.time_ms / 1000:.1f}s · {recommended.multipv} nước"
        )
        recommendation.setWordWrap(True)
        recommendation.setStyleSheet(
            "padding: 7px; color: #bbf7d0; background: #052e16; "
            "border: 1px solid #166534; border-radius: 4px; font-weight: 600;"
        )
        description_label = QLabel("Dùng khi không có preset nhịp độ nào được bật")
        description_label.setWordWrap(True)

        form.addRow(description_label)
        form.addRow("Luồng", threads)
        form.addRow("Hash", hash_mb)
        form.addRow("Thời gian", time_ms)
        form.addRow("Số nước", multipv)
        form.addRow(recommendation)
        self.editors = {
            "threads": threads,
            "hash_mb": hash_mb,
            "time_ms": time_ms,
            "multipv": multipv,
        }
        return group

    def _save(self) -> None:
        active_preset = str(
            self.config.get("analysis.active_time_control_preset", "")
        ).upper()
        self.config.update_default_config({
            **{setting: editor.value() for setting, editor in self.editors.items()},
            "ponder": False,
            "adaptive_time_enabled": True,
        })
        self.config.set("hardware.signature", self.profile.signature)
        self.config.set("hardware.cpu_name", self.profile.cpu_name)
        self.config.set("hardware.physical_cores", self.profile.physical_cores)
        self.config.set("hardware.logical_processors", self.profile.logical_processors)
        self.config.set("hardware.ram_total_gb", self.profile.ram_total_gb)
        self.config.set("hardware.gpu_names", list(self.profile.gpu_names))
        if active_preset in {"RAPID", "BLITZ", "BULLET"}:
            self.config.apply_time_control_preset(active_preset)
        else:
            self.config.apply_default_config()
        self.accept()
