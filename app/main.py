from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QApplication

from app.browser_bootstrap import ensure_chess_browser
from core.config_manager import ConfigManager
from core.hardware_profile import detect_hardware
from engine.engine_manager import EngineManager
from ui.hardware_recommendation_dialog import HardwareRecommendationDialog
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Trợ lý cờ vua")
    app.setOrganizationName("ChessAssistant")

    lock_path = Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation)) / "ChessAssistant.lock"
    app_lock = QLockFile(str(lock_path))
    app_lock.setStaleLockTime(10_000)
    if not app_lock.tryLock(100):
        QMessageBox.information(
            None,
            "Trợ lý cờ vua",
            "Ứng dụng đang chạy. Không cần mở thêm lần nữa.",
        )
        return 0

    browser_result = ensure_chess_browser()

    project_root = Path(__file__).resolve().parents[1]
    config = ConfigManager(project_root / "config" / "settings.json")
    hardware = detect_hardware()
    HardwareRecommendationDialog(config, hardware).exec()

    engine_manager = EngineManager(config)

    window = MainWindow(config, engine_manager)
    app.aboutToQuit.connect(window.shutdown_workers)
    window.resize(580, 780)
    window.show()
    if not browser_result.ready:
        QMessageBox.warning(
            window,
            "Không thể tự động kết nối trình duyệt",
            browser_result.message
            + "\nỨng dụng vẫn hoạt động với chế độ nhận diện hình ảnh hoặc nhập FEN.",
        )

    exit_code = app.exec()
    engine_manager.close()
    app_lock.unlock()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
