import logging

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QHideEvent,
    QMouseEvent,
    QMoveEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.windows import enumerate_windows, place_directly_below
from ui.backdrop import Backdrop
from ui.control_bar import ControlBar
from ui.desktop import Desktop
from ui.styles import CORNER_RADIUS, WINDOW_BACKGROUND, WINDOW_STYLES
from ui.title_bar import TitleBar
from ui.window_picker import WindowPickerDialog


logger = logging.getLogger(__name__)


class MainWindow(QWidget):
    RESIZE_MARGIN = 7

    def __init__(self, always_on_top: bool = True, opacity: float = 0.92) -> None:
        super().__init__()
        self._pinned = True
        self._opacity = opacity
        self._control_bar: ControlBar | None = None
        self._backdrop: Backdrop | None = None
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

        self._title_bar = TitleBar(self)
        self._desktop = Desktop()
        self._desktop.layout_changed.connect(self._update_backdrop_cutouts)
        self._control_bar = ControlBar(self, round(opacity * 100))
        self._control_bar.set_always_on_top(always_on_top)
        self._control_bar.opacity_changed.connect(self._set_opacity)
        self._control_bar.pin_changed.connect(self._set_pinned)
        self._control_bar.window_requested.connect(self._add_external_window)
        self._control_bar.external_window_selected.connect(
            self._desktop.activate_external_window
        )
        self._control_bar.external_visibility_toggled.connect(
            self._desktop.toggle_active_external_window
        )
        self._control_bar.external_release_requested.connect(
            self._release_active_external_window
        )
        self._desktop.external_windows_changed.connect(
            self._control_bar.set_external_windows
        )
        self._desktop.window_detach_failed.connect(self._show_detach_error)
        self._control_bar.setStyleSheet(WINDOW_STYLES)
        self._control_bar.setWindowOpacity(opacity)
        self._backdrop = Backdrop(always_on_top)
        self._backdrop.setWindowOpacity(opacity)
        bar_space = QWidget(self)
        bar_space.setObjectName("controlBarSpace")
        bar_space.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bar_space.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        bar_space.setFixedHeight(self._control_bar.height())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([self.RESIZE_MARGIN] * 4))
        layout.setSpacing(0)
        layout.addWidget(self._title_bar)
        layout.addWidget(self._desktop, 1)
        layout.addWidget(bar_space)

        screen = QApplication.primaryScreen()
        if screen is not None:
            position = screen.availableGeometry().center() - self.rect().center()
            self.move(position)

    def set_always_on_top(self, enabled: bool) -> None:
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == enabled:
            return
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if self._backdrop is not None:
            self._backdrop.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if self._control_bar is not None:
            self._control_bar.set_always_on_top(enabled)
        if was_visible:
            self.show()
            self._sync_surfaces()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._pinned:
            painter.setClipRect(0, 0, self.width(), self._title_bar.geometry().bottom() + 1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*WINDOW_BACKGROUND))
        painter.drawRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)
        if self._control_bar is not None:
            # The native control bar applies its own opacity.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self._control_bar_rect(), Qt.GlobalColor.transparent)
        if not self._pinned:
            painter.setClipping(False)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(*WINDOW_BACKGROUND), self.RESIZE_MARGIN * 2))
            painter.drawRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)

    def _set_opacity(self, value: int) -> None:
        if not self._pinned:
            return
        opacity = value / 100
        self._opacity = opacity
        self.setWindowOpacity(opacity)
        if self._control_bar is not None:
            self._control_bar.set_surface_opacity(opacity)
        if self._backdrop is not None:
            self._backdrop.setWindowOpacity(opacity)

    def _set_pinned(self, pinned: bool) -> None:
        if self._pinned == pinned:
            return
        try:
            self._desktop.set_interactive(pinned)
        except OSError as error:
            self._control_bar.pin_button.setChecked(self._pinned)
            QMessageBox.critical(
                self, "MiniFloat - PIN", f"No se pudo cambiar el modo PIN: {error}"
            )
            return
        self._pinned = pinned
        self._title_bar.set_interactive(pinned)
        self._control_bar.set_pin_only_mode(not pinned)
        if pinned:
            self._control_bar.set_opacity_value(round(self._opacity * 100))
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not pinned)
        if was_visible:
            self.show()
        self._update_backdrop_cutouts()
        self._sync_surfaces()
        self.update()

    def _add_external_window(self) -> None:
        if not self._pinned:
            return
        try:
            candidates = enumerate_windows(self._desktop.managed_handles)
        except OSError as error:
            QMessageBox.critical(
                self, "MiniFloat - Ventanas", f"No se pudieron enumerar ventanas: {error}"
            )
            return

        dialog = WindowPickerDialog(candidates, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        candidate = dialog.selected_window()
        if candidate is None:
            return
        try:
            self._desktop.add_external_window(candidate)
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(
                self,
                "MiniFloat - Ventanas",
                f"No se pudo incorporar {candidate.title!r}: {error}",
            )

    def _show_detach_error(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "MiniFloat - Ventanas",
            f"No se pudo completar la operación de ventana externa: {message}",
        )

    def _release_active_external_window(self) -> None:
        instance_id = self._desktop.active_external_window_id
        if instance_id is not None:
            self._desktop.release_external_window(instance_id)

    def _sync_surfaces(self) -> None:
        if self._control_bar is None or self._backdrop is None:
            return
        if not self.isVisible() or self.isMinimized():
            self._control_bar.hide()
            self._control_bar._pin_overlay.hide()
            self._backdrop.hide()
            return

        bar_rect = self._control_bar_rect()
        bar_point = self.mapToGlobal(bar_rect.topLeft())
        self._control_bar.setGeometry(
            bar_point.x(), bar_point.y(), bar_rect.width(), bar_rect.height()
        )
        self._control_bar.show()
        self._control_bar.sync_pin_overlay()
        if self._pinned:
            self._backdrop.hide()
            return

        self._backdrop.setGeometry(self.geometry())
        self._update_backdrop_cutouts()
        self._backdrop.show()
        try:
            place_directly_below(int(self._backdrop.winId()), int(self.winId()))
        except OSError as error:
            self._set_pinned(True)
            self._control_bar.pin_button.setChecked(True)
            QMessageBox.critical(self, "MiniFloat - PIN", f"No se pudo activar PIN OFF: {error}")

    def _update_backdrop_cutouts(self) -> None:
        if self._backdrop is None or self._control_bar is None or self._pinned:
            return
        margin = self.RESIZE_MARGIN
        cutouts = [
            QRect(0, 0, self.width(), self._title_bar.geometry().bottom() + 1),
            QRect(0, 0, margin, self.height()),
            QRect(self.width() - margin, 0, margin, self.height()),
            QRect(0, self.height() - margin, self.width(), margin),
            self._control_bar_rect(),
        ]
        desktop_position = self._desktop.mapTo(self, QPoint(0, 0))
        desktop_rect = QRect(desktop_position, self._desktop.size())
        external_host = self._desktop.active_external_host
        if external_host is not None and external_host.isVisible():
            cutouts.append(desktop_rect)
        self._backdrop.set_cutouts(cutouts)

    def _control_bar_rect(self) -> QRect:
        if self._control_bar is None:
            return QRect()
        margin = self.RESIZE_MARGIN
        return QRect(
            margin,
            self.height() - margin - self._control_bar.height(),
            self.width() - 2 * margin,
            self._control_bar.height(),
        )

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._sync_surfaces()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_surfaces()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_surfaces()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._sync_surfaces()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.ActivationChange):
            self._sync_surfaces()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._desktop.close_external_windows():
            event.ignore()
            return
        if self._backdrop is not None:
            self._backdrop.close()
        super().closeEvent(event)

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
        if not self._pinned:
            event.accept()
            return
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
