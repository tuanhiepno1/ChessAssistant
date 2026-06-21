from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.hardware_profile import EngineRecommendation, HardwareProfile


PROFILE_INFO = (
    ("WEAK", "Yếu", "Nhẹ máy, phản hồi nhanh"),
    ("MEDIUM", "Trung bình", "Cân bằng tốc độ và độ sâu"),
    ("STRONG", "Mạnh nhất", "Dùng tối đa tài nguyên đã cấu hình"),
)


class HardwareRecommendationDialog(QDialog):
    def __init__(self, config: ConfigManager, profile: HardwareProfile, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.profile = profile
        self.editors: dict[str, dict[str, QSpinBox]] = {}
        self.recommendations = {
            "WEAK": profile.recommend_weak(),
            "MEDIUM": profile.recommend_medium(),
            "STRONG": profile.recommend_max_strength(),
        }

        self.setWindowTitle("Cấu hình máy và chế độ Stockfish")
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

        self.selected_profile = QComboBox()
        for key, label, _description in PROFILE_INFO:
            self.selected_profile.addItem(label, key)
        preset = self._normalized_preset(str(config.get("analysis.preset", "STRONG")))
        self.selected_profile.setCurrentIndex(max(0, self.selected_profile.findData(preset)))
        selection_row = QHBoxLayout()
        selection_row.addWidget(QLabel("Chế độ dùng khi mở ứng dụng"))
        selection_row.addWidget(self.selected_profile, 1)
        layout.addLayout(selection_row)

        profiles_tabs = QTabWidget()
        for key, label, description in PROFILE_INFO:
            profiles_tabs.addTab(
                self._profile_group(key, label, description, self.recommendations[key]),
                label,
            )
        profiles_tabs.setCurrentIndex(max(0, self.selected_profile.currentIndex()))
        self.selected_profile.currentIndexChanged.connect(profiles_tabs.setCurrentIndex)
        profiles_tabs.currentChanged.connect(self.selected_profile.setCurrentIndex)
        layout.addWidget(profiles_tabs)

        note = QLabel(
            "Các số khuyến nghị chỉ là điểm bắt đầu. Bạn có thể chỉnh và lưu riêng từng chế độ; "
            "ứng dụng sẽ không tự ghi đè lại khi đổi chế độ."
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

    def _profile_group(
        self,
        key: str,
        label: str,
        description: str,
        recommended: EngineRecommendation,
    ) -> QWidget:
        group = QGroupBox(label)
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        saved = self.config.get(f"profiles.{key}", {})
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
        description_label = QLabel(description)
        description_label.setWordWrap(True)

        form.addRow(description_label)
        form.addRow("Luồng", threads)
        form.addRow("Hash", hash_mb)
        form.addRow("Thời gian", time_ms)
        form.addRow("Số nước", multipv)
        form.addRow(recommendation)
        self.editors[key] = {
            "threads": threads,
            "hash_mb": hash_mb,
            "time_ms": time_ms,
            "multipv": multipv,
        }
        return group

    def _save(self) -> None:
        for key, editors in self.editors.items():
            for setting, editor in editors.items():
                self.config.set(f"profiles.{key}.{setting}", editor.value())
            self.config.set(f"profiles.{key}.ponder", False)

        selected = str(self.selected_profile.currentData())
        self.config.set("hardware.signature", self.profile.signature)
        self.config.set("hardware.cpu_name", self.profile.cpu_name)
        self.config.set("hardware.physical_cores", self.profile.physical_cores)
        self.config.set("hardware.logical_processors", self.profile.logical_processors)
        self.config.set("hardware.ram_total_gb", self.profile.ram_total_gb)
        self.config.set("hardware.gpu_names", list(self.profile.gpu_names))
        self.config.apply_profile(selected)
        self.accept()

    @staticmethod
    def _normalized_preset(preset: str) -> str:
        if preset in {"WEAK", "FAST", "BLITZ"}:
            return "WEAK"
        if preset in {"MEDIUM", "BALANCED10", "RAPID"}:
            return "MEDIUM"
        return "STRONG"
