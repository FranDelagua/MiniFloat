import logging

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPaintEvent, QPainter
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ui.desktop import Desktop
from ui.styles import CORNER_RADIUS, WINDOW_BACKGROUND, WINDOW_STYLES
from ui.title_bar import TitleBar


logger = logging.getLogger(__name__)


class MainWindow(QWidget):
    RESIZE_MARGIN = 7

    def __init__(self, always_on_top: bool = True, opacity: float = 0.92) -> None:
        super().__init__()
        self.setWindowTitle("MiniFloat")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | (
                Qt.WindowType.WindowStaysOnTopHint
                if always_on_top
                else Qt.WindowType.Widget
            )
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 180)
        self.resize(400, 280)
        self.setStyleSheet(WINDOW_STYLES)
        self.setWindowOpacity(opacity)

        title_bar = TitleBar(self, round(opacity * 100))
        title_bar.opacity_changed.connect(
            lambda value: self.setWindowOpacity(value / 100)
        )
        desktop = Desktop()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([self.RESIZE_MARGIN] * 4))
        layout.setSpacing(0)
        layout.addWidget(title_bar)
        layout.addWidget(desktop, 1)

        screen = QApplication.primaryScreen()
        if screen is not None:
            position = screen.availableGeometry().center() - self.rect().center()
            self.move(position)

    def set_always_on_top(self, enabled: bool) -> None:
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == enabled:
            return
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.show()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*WINDOW_BACKGROUND))
        painter.drawRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)

    def _resize_edges(self, position: QPointF) -> Qt.Edge:
        edges = Qt.Edge(0)
        if position.x() < self.RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - self.RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if position.y() < self.RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - self.RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._resize_edges(event.position())
            handle = self.windowHandle()
            if edges and handle is not None:
                if not handle.startSystemResize(edges):
                    logger.warning("Windows could not start resizing the window.")
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        edges = self._resize_edges(event.position())
        diagonal_forward = (
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        )
        diagonal_backward = (
            Qt.Edge.RightEdge | Qt.Edge.TopEdge,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
        )
        if edges in diagonal_forward:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in diagonal_backward:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.unsetCursor()
        super().leaveEvent(event)
