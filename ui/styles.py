WINDOW_BACKGROUND = (116, 136, 157)
DESKTOP_BACKGROUND = (138, 157, 176)
CORNER_RADIUS = 12

WINDOW_STYLES = """
QWidget {
    color: #f0f2f6;
    font-family: "Segoe UI";
    font-size: 13px;
}
QLabel#title {
    font-weight: 600;
}
QWidget#titleBar {
    background: #39495b;
    border-radius: 8px;
}
QWidget#desktop {
    background: #8a9db0;
    border: none;
}
QWidget#controlBar {
    background: #39495b;
    border: 1px solid #526276;
    border-radius: 7px;
}
QDialog {
    background: #39495b;
}
QListWidget {
    background: #53677b;
    alternate-background-color: #4b5f73;
    border: 1px solid #526276;
    border-radius: 6px;
    outline: none;
    selection-background-color: #887da3;
    selection-color: #ffffff;
}
QListWidget::item {
    min-height: 28px;
    padding: 4px 8px;
    border-radius: 4px;
}
QListWidget::item:hover {
    background: #7d8499;
    color: #ffffff;
}
QListWidget::item:selected {
    background: #887da3;
    color: #ffffff;
}
QMenu {
    background: #39495b;
    color: #f0f2f6;
    border: 1px solid #526276;
    padding: 4px;
}
QMenu::item {
    min-height: 24px;
    padding: 5px 24px 5px 10px;
    border-radius: 4px;
    background: transparent;
}
QMenu::item:selected {
    background: #7d8499;
    color: #ffffff;
}
QMenu::item:checked {
    background: #887da3;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    margin: 4px 6px;
    background: #526276;
}
QPushButton {
    color: #f0f2f6;
    background: #887da3;
    border: 1px solid #61728a;
    border-radius: 5px;
    padding: 5px 12px;
}
QPushButton:hover {
    background: #7d8499;
}
QPushButton:pressed {
    background: #776d91;
}
QPushButton:disabled {
    color: #9da7b4;
    background: #3f4e60;
    border-color: #4b596a;
}
QSlider::groove:horizontal {
    height: 4px;
    border-radius: 2px;
    background: #5b6b7e;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: #a99cc4;
}
QSlider::handle:horizontal:hover {
    background: #b7abd0;
}
QToolButton {
    border: none;
    border-radius: 6px;
    background: #887da3;
    min-width: 28px;
    min-height: 28px;
    font-size: 16px;
}
QToolButton:hover {
    background: #7d8499;
}
QToolButton:pressed {
    background: #776d91;
}
QToolButton#pinButton {
    background: #887da3;
    padding: 0;
}
QToolButton#pinButton:checked {
    background: #887da3;
}
QToolButton#pinButton:hover {
    background: #7d8499;
}
QToolButton#addWindowButton {
    background: #887da3;
}
QToolButton#addWindowButton:hover {
    background: #7d8499;
}
QToolButton#externalWindowButton {
    background: #887da3;
}
QToolButton#externalWindowButton:hover {
    background: #7d8499;
}
QToolButton#closeButton:hover {
    background: #9a6876;
}
QToolButton#closeButton:pressed {
    background: #ad7484;
}
"""
