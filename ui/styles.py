WINDOW_BACKGROUND = (27, 30, 36)
CORNER_RADIUS = 12

WINDOW_STYLES = """
QWidget {
    color: #e6e9ef;
    font-family: "Segoe UI";
    font-size: 13px;
}
QLabel#title {
    font-weight: 600;
}
QMdiArea {
    background: transparent;
    border: none;
}
QMdiSubWindow {
    background: #272d37;
    border: 1px solid #49515e;
}
QLabel#testWindowContent {
    background: #272d37;
    color: #b6becb;
}
QToolButton {
    border: none;
    border-radius: 5px;
    background: transparent;
    min-width: 28px;
    min-height: 28px;
    font-size: 18px;
}
QToolButton:hover {
    background: #414854;
}
QToolButton:pressed {
    background: #555e6d;
}
QToolButton#closeButton:hover {
    background: #9c4148;
}
QToolButton#closeButton:pressed {
    background: #b65058;
}
"""
