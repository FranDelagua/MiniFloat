from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QFrame, QLabel, QMdiArea, QMdiSubWindow


class Desktop(QMdiArea):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackground(QBrush(Qt.GlobalColor.transparent))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

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
        subwindow.setGeometry(x, y, width, height)
        subwindow.show()
