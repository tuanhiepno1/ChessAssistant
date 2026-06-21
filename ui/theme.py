from __future__ import annotations


DARK_STYLESHEET = """
QWidget {
    background-color: #0f172a;
    color: #e2e8f0;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QMainWindow, QDialog {
    background-color: #0b1120;
}
QGroupBox {
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
    color: #f8fafc;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #cbd5e1;
}
QLabel {
    background: transparent;
}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #111827;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 5px;
    padding: 5px 7px;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #60a5fa;
}
QComboBox::drop-down {
    border: 0;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #111827;
    color: #f8fafc;
    border: 1px solid #475569;
    selection-background-color: #1d4ed8;
}
QPushButton {
    background-color: #1e293b;
    color: #e2e8f0;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 7px 11px;
}
QPushButton:hover {
    background-color: #334155;
    border-color: #64748b;
}
QPushButton:pressed {
    background-color: #0f172a;
}
QPushButton:disabled, QLineEdit:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QComboBox:disabled {
    background-color: #172033;
    color: #64748b;
    border-color: #263449;
}
QCheckBox {
    spacing: 8px;
    background: transparent;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #64748b;
    border-radius: 4px;
    background-color: #111827;
}
QCheckBox::indicator:checked {
    background-color: #2563eb;
    border-color: #60a5fa;
}
QTabWidget::pane {
    border: 1px solid #334155;
    border-radius: 6px;
    background-color: #0f172a;
}
QTabBar::tab {
    background-color: #172033;
    color: #94a3b8;
    border: 1px solid #334155;
    padding: 7px 12px;
}
QTabBar::tab:selected {
    background-color: #1e293b;
    color: #f8fafc;
    border-bottom-color: #60a5fa;
}
QTextEdit, QPlainTextEdit {
    background-color: #090f1d;
}
QScrollBar:vertical {
    background: #0f172a;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #475569;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    color: #f8fafc;
    background-color: #1e293b;
    border: 1px solid #64748b;
    padding: 5px;
}
"""


def apply_dark_theme(app) -> None:  # noqa: ANN001
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)

