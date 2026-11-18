from PySide6.QtCore import QEvent, QObject, Signal, Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QFrame, QLabel, QMdiArea, QMdiSubWindow


class Desktop(QMdiArea):
    layout_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._constraining = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackground(QBrush(Qt.GlobalColor.transparent))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().installEventFilter(self)

        self._add_test_window("Test Window", 12, 12, 170, 135)
        self._add_test_window("Test 2", 190, 48, 160, 120)

    def _add_test_window(
        self, title: str, x: int, y: int, width: int, height: int
    ) -> None:
        subwindow = QMdiSubWindow()
        subwindow.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        subwindow.setWindowFlags(
            Qt.WindowType.SubWindow
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        subwindow.setWindowTitle(title)

        content = QLabel("Ventana de prueba")
        content.setObjectName("testWindowContent")
        content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subwindow.setWidget(content)

        self.addSubWindow(subwindow)
        subwindow.installEventFilter(self)
        subwindow.setGeometry(x, y, width, height)
        subwindow.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            for subwindow in self.subWindowList():
                self._constrain(subwindow)
            self.layout_changed.emit()
        elif isinstance(watched, QMdiSubWindow) and event.type() in (
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.WindowStateChange,
        ):
            if not self._constraining:
                self._constrain(watched)
                self.layout_changed.emit()
        return super().eventFilter(watched, event)

    def _constrain(self, subwindow: QMdiSubWindow) -> None:
        if self._constraining:
            return
        area = self.viewport().size()
        if area.width() <= 0 or area.height() <= 0:
            return
        self._constraining = True
        try:
            if not subwindow.isMinimized():
                subwindow.resize(
                    min(subwindow.width(), area.width()),
                    min(subwindow.height(), area.height()),
                )
            x = max(0, min(subwindow.x(), max(0, area.width() - subwindow.width())))
            y = max(0, min(subwindow.y(), max(0, area.height() - subwindow.height())))
            subwindow.move(x, y)
        finally:
            self._constraining = False
