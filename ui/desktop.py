import logging

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QWidget

from app.windows import (
    ExternalWindow,
    ExternalWindowState,
    WindowCandidate,
    native_client_geometry,
)


logger = logging.getLogger(__name__)


class ExternalWindowEmbeddingError(RuntimeError):
    pass


class _ExternalWindowHost(QWidget):
    def __init__(self, desktop: "Desktop", external: ExternalWindow) -> None:
        super().__init__(desktop)
        self.external: ExternalWindow | None = external
        self.setObjectName("externalWindowHost")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            not desktop.is_interactive,
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def native_parent_handle(self) -> int:
        return int(self.winId())

    def release_reference(self) -> None:
        self.external = None
        self.hide()
        self.setParent(None)
        self.deleteLater()


class Desktop(QWidget):
    layout_changed = Signal()
    window_detach_failed = Signal(str)
    external_windows_changed = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self._interactive = True
        self._external_windows: dict[str, _ExternalWindowHost] = {}
        self._minimized_external_windows: set[str] = set()
        self._active_external_window: str | None = None
        self.setObjectName("desktop")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setInterval(500)
        self._cleanup_timer.timeout.connect(self._remove_closed_windows)

    @property
    def is_interactive(self) -> bool:
        return self._interactive

    @property
    def managed_handles(self) -> set[int]:
        return {
            host.external.handle
            for host in self._external_windows.values()
            if host.external is not None
        }

    @property
    def active_external_host(self) -> QWidget | None:
        if self._active_external_window is None:
            return None
        return self._external_windows.get(self._active_external_window)

    @property
    def active_external_window_id(self) -> str | None:
        return self._active_external_window

    @property
    def active_external_is_minimized(self) -> bool:
        return self._active_external_window in self._minimized_external_windows

    def external_window_items(self) -> list[tuple[str, str]]:
        return [
            (
                instance_id,
                f"{host.external.process_name} — {host.external.title}",
            )
            for instance_id, host in self._external_windows.items()
            if host.external is not None
        ]

    def add_external_window(self, candidate: WindowCandidate) -> str:
        external = ExternalWindow.capture(candidate)
        host = _ExternalWindowHost(self, external)
        host.setGeometry(self.rect())
        host_handle = host.native_parent_handle
        try:
            external.adopt(host_handle, native_client_geometry(host_handle))
        except (OSError, RuntimeError) as error:
            if (
                external.state is ExternalWindowState.RECOVERY_REQUIRED
                and external.is_alive()
            ):
                instance_id = external.instance_id
                self._external_windows[instance_id] = host
                self._cleanup_timer.start()
                self.activate_external_window(instance_id)
                self._emit_external_windows_changed()
            else:
                host.release_reference()
            raise ExternalWindowEmbeddingError(
                f"No se pudo adoptar {candidate.title!r}: {error}"
            ) from error

        instance_id = external.instance_id
        self._external_windows[instance_id] = host
        self._cleanup_timer.start()
        self.activate_external_window(instance_id)
        self._emit_external_windows_changed()
        return instance_id

    def activate_external_window(self, instance_id: str) -> bool:
        host = self._external_windows.get(instance_id)
        if host is None or host.external is None:
            return False
        if not host.external.is_alive():
            self._forget_external_window(instance_id)
            return False

        self._active_external_window = instance_id
        self._minimized_external_windows.discard(instance_id)
        for current_id, current_host in self._external_windows.items():
            if current_id == instance_id:
                self._sync_external_host_geometry(current_host)
                current_host.show()
                current_host.raise_()
            else:
                current_host.hide()
        self._emit_external_windows_changed()
        self.layout_changed.emit()
        return True

    def toggle_active_external_window(self) -> None:
        instance_id = self._active_external_window
        host = self._external_windows.get(instance_id or "")
        if host is None:
            return
        if instance_id in self._minimized_external_windows:
            self.activate_external_window(instance_id)
            return

        self._minimized_external_windows.add(instance_id)
        host.hide()
        next_id = next(
            (
                candidate_id
                for candidate_id in self._external_windows
                if candidate_id != instance_id
                and candidate_id not in self._minimized_external_windows
            ),
            None,
        )
        if next_id is not None:
            self.activate_external_window(next_id)
        else:
            self._active_external_window = instance_id
            self._emit_external_windows_changed()
            self.layout_changed.emit()

    def release_external_window(self, instance_id: str) -> bool:
        host = self._external_windows.get(instance_id)
        if host is None or host.external is None:
            return False
        external = host.external
        if not external.is_alive():
            self._forget_external_window(instance_id)
            return True

        was_visible = host.isVisible()
        host.hide()
        try:
            released = external.release()
        except (OSError, RuntimeError) as error:
            if (
                external.state
                in (
                    ExternalWindowState.ADOPTED,
                    ExternalWindowState.RECOVERY_REQUIRED,
                )
            ):
                if was_visible:
                    host.show()
                    host.raise_()
            self.window_detach_failed.emit(str(error))
            return False

        if not released and external.state is not ExternalWindowState.RELEASED:
            self.window_detach_failed.emit(
                f"No se pudo liberar {external.title!r}: estado inesperado."
            )
            if was_visible:
                host.show()
                host.raise_()
            return False
        self._forget_external_window(instance_id)
        return True

    def close_external_windows(self) -> bool:
        for instance_id in list(self._external_windows):
            if not self.release_external_window(instance_id):
                return False
        return True

    def set_interactive(self, enabled: bool) -> None:
        changed: list[ExternalWindow] = []
        try:
            for host in self._external_windows.values():
                external = host.external
                if external is not None:
                    external.set_interactive(enabled)
                    changed.append(external)
                host.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents, not enabled
                )
        except OSError:
            for external in reversed(changed):
                try:
                    external.set_interactive(self._interactive)
                except OSError:
                    logger.exception(
                        "No se pudo restaurar el estado de entrada de la ventana "
                        "externa %s.",
                        external.instance_id,
                    )
            raise

        self._interactive = enabled

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        for host in self._external_windows.values():
            self._sync_external_host_geometry(host)
        self.layout_changed.emit()

    def _forget_external_window(self, instance_id: str) -> None:
        host = self._external_windows.pop(instance_id, None)
        if host is None:
            return
        self._minimized_external_windows.discard(instance_id)
        host.release_reference()
        if not self._external_windows:
            self._cleanup_timer.stop()

        if self._active_external_window == instance_id:
            self._active_external_window = None
            next_id = next(
                (
                    candidate_id
                    for candidate_id in self._external_windows
                    if candidate_id not in self._minimized_external_windows
                ),
                None,
            )
            if next_id is not None:
                self.activate_external_window(next_id)
        self._emit_external_windows_changed()
        self.layout_changed.emit()

    def _sync_external_host_geometry(self, host: _ExternalWindowHost) -> None:
        area = self.rect()
        host.setGeometry(area)
        external = host.external
        if external is not None:
            try:
                external.set_geometry(native_client_geometry(host.native_parent_handle))
            except OSError as error:
                message = (
                    f"No se pudo ajustar {external.title!r} al escritorio: {error}"
                )
                logger.exception(message)
                self.window_detach_failed.emit(message)

    def _emit_external_windows_changed(self) -> None:
        self.external_windows_changed.emit(
            self.external_window_items(), self._active_external_window
        )

    def _remove_closed_windows(self) -> None:
        for instance_id, host in list(self._external_windows.items()):
            external = host.external
            if external is None or not external.is_alive():
                self._forget_external_window(instance_id)
