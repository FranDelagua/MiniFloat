import ctypes
import logging
import os
import sys
import uuid
from ctypes import wintypes
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import lru_cache
from typing import Any


logger = logging.getLogger(__name__)


class ExternalWindowState(Enum):
    NOT_ADOPTED = auto()
    ADOPTING = auto()
    ADOPTION_FAILED = auto()
    ROLLING_BACK = auto()
    ADOPTED = auto()
    RELEASING = auto()
    RELEASED = auto()
    RECOVERY_REQUIRED = auto()


class ExternalWindowTransitionError(RuntimeError):
    pass


# Mutaciones que adopt() aplica sobre el HWND; el rollback y la liberación solo
# deshacen las que consta que se aplicaron.
ADOPTION_STEPS = frozenset(
    {"visibility", "owner", "style", "extended_style", "parent", "geometry"}
)


@dataclass(frozen=True)
class WindowCandidate:
    handle: int
    title: str
    process_id: int
    process_name: str
    class_name: str
    visible: bool = True

    @property
    def hwnd(self) -> int:
        return self.handle

    @property
    def display_name(self) -> str:
        return f"{self.process_name} — {self.title}"


@dataclass(frozen=True)
class WindowPlacement:
    flags: int
    show_command: int
    minimum_position: tuple[int, int]
    maximum_position: tuple[int, int]
    normal_rect: tuple[int, int, int, int]


@dataclass
class ExternalWindow:
    instance_id: str
    handle: int
    title: str
    process_id: int
    process_name: str
    class_name: str
    original_parent: int
    original_owner: int
    original_style: int
    original_extended_style: int
    original_geometry: tuple[int, int, int, int]
    original_placement: WindowPlacement
    original_enabled: bool
    original_visible: bool
    original_was_minimized: bool
    original_was_maximized: bool
    state: ExternalWindowState = ExternalWindowState.NOT_ADOPTED
    adopted_parent: int | None = None
    adopted_geometry: tuple[int, int, int, int] | None = None
    applied_steps: set[str] = field(default_factory=set)

    @classmethod
    def capture(cls, candidate: WindowCandidate) -> "ExternalWindow":
        return _windows_api().capture(candidate)

    def adopt(
        self, parent: int, geometry: tuple[int, int, int, int]
    ) -> None:
        if self.state is not ExternalWindowState.NOT_ADOPTED:
            raise ExternalWindowTransitionError(
                f"No se puede adoptar {self.title!r} desde {self.state.name}."
            )
        if not self.is_alive():
            self._transition_to(ExternalWindowState.RELEASED)
            raise OSError(f"La ventana {self.title!r} ya no existe.")

        self._transition_to(ExternalWindowState.ADOPTING)
        self.adopted_parent = parent
        self.adopted_geometry = geometry
        api = _windows_api()
        try:
            api.adopt(self, parent, geometry)
        except OSError as error:
            self._transition_to(ExternalWindowState.ADOPTION_FAILED)
            if not self.is_alive():
                self._mark_released()
                raise

            self._transition_to(ExternalWindowState.ROLLING_BACK)
            try:
                restored = api.restore_original(self)
            except OSError as rollback_error:
                if not self.is_alive():
                    self._mark_released()
                    raise ExternalWindowTransitionError(
                        f"Falló la adopción de {self.title!r}; el HWND dejó de "
                        f"existir durante el rollback: {rollback_error} "
                        f"(error original: {error})"
                    ) from error
                self._transition_to(ExternalWindowState.RECOVERY_REQUIRED)
                raise ExternalWindowTransitionError(
                    f"Falló la adopción de {self.title!r} y también su rollback: "
                    f"{rollback_error} (error original: {error})"
                ) from error
            if restored:
                self._transition_to(ExternalWindowState.NOT_ADOPTED)
                self.adopted_parent = None
                self.adopted_geometry = None
            elif self.is_alive():
                self._transition_to(ExternalWindowState.RECOVERY_REQUIRED)
            else:
                self._mark_released()
            raise

        self._transition_to(ExternalWindowState.ADOPTED)

    def set_geometry(self, geometry: tuple[int, int, int, int]) -> None:
        if self.state is not ExternalWindowState.ADOPTED:
            return
        if not self.is_alive():
            return
        _windows_api().set_geometry(self, geometry)
        self.adopted_geometry = geometry

    def set_interactive(self, enabled: bool) -> None:
        if self.state is ExternalWindowState.ADOPTED and self.is_alive():
            _windows_api().set_enabled(self, enabled and self.original_enabled)

    def is_alive(self) -> bool:
        return _windows_api().matches_window(self)

    def release(self) -> bool:
        if self.state is ExternalWindowState.RELEASED:
            return False
        recovering = self.state is ExternalWindowState.RECOVERY_REQUIRED
        if self.state is not ExternalWindowState.ADOPTED and not recovering:
            raise ExternalWindowTransitionError(
                f"No se puede liberar {self.title!r} desde {self.state.name}."
            )
        if not self.is_alive():
            self._transition_to(ExternalWindowState.RELEASED)
            self.adopted_parent = None
            self.adopted_geometry = None
            return False

        self._transition_to(ExternalWindowState.RELEASING)
        api = _windows_api()
        try:
            restored = api.restore_original(self)
            if not restored and self.is_alive():
                raise OSError(
                    f"No se pudo verificar la liberación de {self.title!r}."
                )
        except OSError as error:
            if not self.is_alive():
                self._mark_released()
                logger.warning(
                    "HWND became invalid during release; no further Win32 "
                    "operations will be attempted (hwnd=%#x, title=%r, error=%s).",
                    self.handle,
                    self.title,
                    error,
                )
                return False
            if recovering:
                self._transition_to(ExternalWindowState.RECOVERY_REQUIRED)
                raise
            try:
                api.adopt(self, self.adopted_parent or 0, self.adopted_geometry or (0, 0, 0, 0))
            except OSError as rollback_error:
                self._transition_to(ExternalWindowState.RECOVERY_REQUIRED)
                raise ExternalWindowTransitionError(
                    f"Falló la liberación de {self.title!r} y también su rollback: "
                    f"{rollback_error}"
                ) from error
            self._transition_to(ExternalWindowState.ADOPTED)
            raise

        self._transition_to(ExternalWindowState.RELEASED)
        self.adopted_parent = None
        self.adopted_geometry = None
        return restored

    def _mark_released(self) -> None:
        self._transition_to(ExternalWindowState.RELEASED)
        self.adopted_parent = None
        self.adopted_geometry = None

    def _transition_to(self, state: ExternalWindowState) -> None:
        previous = self.state
        self.state = state
        logger.warning(
            "External HWND lifecycle: %s -> %s hwnd=%#x title=%r.",
            previous.name,
            state.name,
            self.handle,
            self.title,
        )


def is_selectable_window(
    candidate: WindowCandidate,
    current_process_id: int,
    excluded_handles: set[int] | None = None,
) -> bool:
    excluded = excluded_handles or set()
    return (
        candidate.handle != 0
        and candidate.visible
        and candidate.handle not in excluded
        and candidate.process_id != current_process_id
        and bool(candidate.title.strip())
    )


def enumerate_windows(excluded_handles: set[int] | None = None) -> list[WindowCandidate]:
    api = _windows_api()
    candidates = api.enumerate()
    current_process_id = os.getpid()
    return [
        candidate
        for candidate in candidates
        if is_selectable_window(candidate, current_process_id, excluded_handles)
    ]


def native_client_geometry(handle: int) -> tuple[int, int, int, int]:
    return _windows_api().client_geometry(handle)


class _NativeWindowPlacement(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


@dataclass(frozen=True)
class _WindowDiagnostic:
    is_window: bool
    parent_hwnd: int | None = None
    owner_hwnd: int | None = None
    thread_id: int | None = None
    process_id: int | None = None
    class_name: str | None = None


class _Win32Windows:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    GWLP_HWNDPARENT = -8
    GW_OWNER = 4
    GA_PARENT = 1
    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    WS_MINIMIZE = 0x20000000
    WS_MAXIMIZE = 0x01000000
    WS_BORDER = 0x00800000
    WS_DLGFRAME = 0x00400000
    WS_THICKFRAME = 0x00040000
    WS_SYSMENU = 0x00080000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    EMBEDDED_FRAME_STYLE = (
        WS_BORDER
        | WS_DLGFRAME
        | WS_THICKFRAME
        | WS_SYSMENU
        | WS_MINIMIZEBOX
        | WS_MAXIMIZEBOX
    )
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOPMOST = 0x00000008
    WS_EX_WINDOWEDGE = 0x00000100
    HWND_TOP = 0
    SW_HIDE = 0
    SW_SHOWNORMAL = 1
    SW_SHOWMINIMIZED = 2
    SW_SHOWMAXIMIZED = 3
    SW_SHOWMINNOACTIVE = 7
    SW_SHOW = 5
    SW_RESTORE = 9
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    SWP_SHOWWINDOW = 0x0040
    SWP_NOOWNERZORDER = 0x0200

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("La gestión de ventanas externas solo está disponible en Windows.")

        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_functions()

    def _inspect_hwnd(self, handle: int) -> _WindowDiagnostic:
        if not self.user32.IsWindow(handle):
            return _WindowDiagnostic(is_window=False)

        get_parent = getattr(self.user32, "GetParent", None)
        parent = int(get_parent(handle) or 0) if get_parent is not None else None
        get_window = getattr(self.user32, "GetWindow", None)
        owner = (
            int(get_window(handle, self.GW_OWNER) or 0)
            if get_window is not None
            else None
        )
        thread_id: int | None = None
        process_id: int | None = None
        get_thread_process = getattr(
            self.user32, "GetWindowThreadProcessId", None
        )
        if get_thread_process is not None:
            process = wintypes.DWORD()
            thread_id = int(
                get_thread_process(handle, ctypes.byref(process)) or 0
            )
            process_id = int(process.value)
        class_name: str | None = None
        get_class_name = getattr(self.user32, "GetClassNameW", None)
        if get_class_name is not None:
            buffer = ctypes.create_unicode_buffer(256)
            if get_class_name(handle, buffer, len(buffer)):
                class_name = buffer.value
        return _WindowDiagnostic(
            is_window=True,
            parent_hwnd=parent,
            owner_hwnd=owner,
            thread_id=thread_id,
            process_id=process_id,
            class_name=class_name,
        )

    @staticmethod
    def _format_hwnd(handle: int | None) -> str:
        return "unknown" if handle is None else f"{handle:#x}"

    def _invoke_hwnd_operation(
        self,
        handle: int,
        operation: str,
        function: Any,
        *args: Any,
        window: ExternalWindow | None = None,
        label: str | None = None,
        expected_identity: tuple[int, str] | None = None,
        related_hwnds: tuple[tuple[str, int], ...] = (),
    ) -> tuple[Any, int]:
        state_name = window.state.name if window is not None else "CAPTURING"
        title = window.title if window is not None else (label or "")
        identity = (
            (window.process_id, window.class_name)
            if window is not None
            else expected_identity
        )
        before = self._inspect_hwnd(handle)
        original_owner = window.original_owner if window is not None else None
        original_owner_valid = (
            bool(self.user32.IsWindow(original_owner))
            if original_owner is not None
            else None
        )
        parent_valid = (
            bool(self.user32.IsWindow(before.parent_hwnd))
            if before.parent_hwnd is not None
            else None
        )
        owner_valid = (
            bool(self.user32.IsWindow(before.owner_hwnd))
            if before.owner_hwnd is not None
            else None
        )
        error_before = ctypes.get_last_error()
        logger.warning(
            "Win32 before: state=%s operation=%s hwnd=%#x parent_hwnd=%s "
            "is_window(parent)=%s owner_hwnd=%s is_window(owner)=%s "
            "original_owner=%s is_window(original_owner)=%s "
            "is_window(hwnd)=%s pid=%s thread_id=%s result=<not-called> "
            "GetLastError(before)=%s title=%r args=%r",
            state_name,
            operation,
            handle,
            self._format_hwnd(before.parent_hwnd),
            parent_valid,
            self._format_hwnd(before.owner_hwnd),
            owner_valid,
            self._format_hwnd(original_owner),
            original_owner_valid,
            before.is_window,
            before.process_id,
            before.thread_id,
            error_before,
            title,
            args,
        )
        if not before.is_window:
            logger.error(
                "HWND became invalid; skipped operation=%s hwnd=%#x title=%r.",
                operation,
                handle,
                title,
            )
            raise OSError(
                f"HWND {handle:#x} dejó de ser válido antes de {operation}; "
                "se omitió la llamada Win32."
            )
        if identity is not None and (
            before.process_id != identity[0]
            or before.class_name != identity[1]
        ):
            logger.error(
                "HWND identity changed; skipped operation=%s hwnd=%#x "
                "process_id=%s class_name=%r expected_pid=%s "
                "expected_class=%r title=%r.",
                operation,
                handle,
                before.process_id,
                before.class_name,
                identity[0],
                identity[1],
                title,
            )
            raise OSError(
                f"HWND {handle:#x} ahora pertenece a otra ventana; "
                f"se omitió {operation}."
            )
        related_status = tuple(
            (
                related_name,
                related_handle,
                bool(self.user32.IsWindow(related_handle))
                if related_handle
                else True,
            )
            for related_name, related_handle in related_hwnds
        )
        if related_status:
            logger.warning(
                "Win32 related HWNDs: operation=%s hwnd=%#x related=%r title=%r.",
                operation,
                handle,
                related_status,
                title,
            )
        for related_name, related_handle, is_related_window in related_status:
            if not is_related_window:
                logger.error(
                    "Invalid related HWND; skipped operation=%s hwnd=%#x "
                    "%s_hwnd=%#x is_window=false title=%r.",
                    operation,
                    handle,
                    related_name,
                    related_handle,
                    title,
                )
                raise OSError(
                    f"El HWND {related_name} {related_handle:#x} dejó de ser "
                    f"válido antes de {operation}."
                )

        ctypes.set_last_error(0)
        result = function(handle, *args)
        error = ctypes.get_last_error()
        after = self._inspect_hwnd(handle)
        logger.warning(
            "Win32 after: state=%s operation=%s hwnd=%#x parent_hwnd=%s "
            "owner_hwnd=%s original_owner=%s is_window(hwnd)=%s pid=%s "
            "thread_id=%s result=%r "
            "GetLastError=%s title=%r args=%r",
            state_name,
            operation,
            handle,
            self._format_hwnd(after.parent_hwnd),
            self._format_hwnd(after.owner_hwnd),
            self._format_hwnd(original_owner),
            after.is_window,
            after.process_id,
            after.thread_id,
            result,
            error,
            title,
            args,
        )
        if not after.is_window:
            logger.error(
                "HWND became invalid during operation=%s hwnd=%#x title=%r; "
                "no further Win32 operation will be attempted.",
                operation,
                handle,
                title,
            )
            raise OSError(
                f"HWND {handle:#x} dejó de ser válido durante {operation}."
            )
        if identity is not None and (
            after.process_id != identity[0]
            or after.class_name != identity[1]
        ):
            logger.error(
                "HWND identity changed during operation=%s hwnd=%#x "
                "process_id=%s class_name=%r title=%r.",
                operation,
                handle,
                after.process_id,
                after.class_name,
                title,
            )
            raise OSError(
                f"HWND {handle:#x} cambió de identidad durante {operation}."
            )
        return result, error

    def _configure_functions(self) -> None:
        self.user32.EnumWindows.argtypes = [
            ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
            wintypes.LPARAM,
        ]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindow.restype = wintypes.BOOL
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        self.user32.IsWindowEnabled.restype = wintypes.BOOL
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.IsIconic.restype = wintypes.BOOL
        self.user32.IsZoomed.argtypes = [wintypes.HWND]
        self.user32.IsZoomed.restype = wintypes.BOOL
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetClassNameW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user32.GetWindow.restype = wintypes.HWND
        self.user32.GetParent.argtypes = [wintypes.HWND]
        self.user32.GetParent.restype = wintypes.HWND
        self.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user32.GetAncestor.restype = wintypes.HWND
        self.user32.GetDesktopWindow.restype = wintypes.HWND
        self.user32.GetWindowRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.user32.GetClientRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        self.user32.GetClientRect.restype = wintypes.BOOL
        self.user32.GetWindowPlacement.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(_NativeWindowPlacement),
        ]
        self.user32.GetWindowPlacement.restype = wintypes.BOOL
        self.user32.SetWindowPlacement.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(_NativeWindowPlacement),
        ]
        self.user32.SetWindowPlacement.restype = wintypes.BOOL
        self.user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        self.user32.SetParent.restype = wintypes.HWND
        self.user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self.user32.SetWindowPos.restype = wintypes.BOOL
        self.user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.user32.EnableWindow.restype = wintypes.BOOL
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.ShowWindow.restype = wintypes.BOOL
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

        get_long_ptr = getattr(self.user32, "GetWindowLongPtrW", None)
        set_long_ptr = getattr(self.user32, "SetWindowLongPtrW", None)
        self.get_window_long_ptr = get_long_ptr or self.user32.GetWindowLongW
        self.set_window_long_ptr = set_long_ptr or self.user32.SetWindowLongW
        self.get_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int]
        self.get_window_long_ptr.restype = ctypes.c_ssize_t
        self.set_window_long_ptr.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_ssize_t,
        ]
        self.set_window_long_ptr.restype = ctypes.c_ssize_t

    def enumerate(self) -> list[WindowCandidate]:
        handles: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def collect(handle: int, _parameter: int) -> bool:
            handles.append(int(handle))
            return True

        callback = callback_type(collect)
        ctypes.set_last_error(0)
        if not self.user32.EnumWindows(callback, 0):
            error = ctypes.get_last_error()
            if error:
                raise ctypes.WinError(error)

        candidates: list[WindowCandidate] = []
        for handle in handles:
            if not self.user32.IsWindow(handle):
                logger.warning(
                    "HWND became invalid during enumeration; skipping hwnd=%#x.",
                    handle,
                )
                continue
            if not self.user32.IsWindowVisible(handle):
                continue
            title_length = self.user32.GetWindowTextLengthW(handle)
            if title_length <= 0:
                continue
            title_buffer = ctypes.create_unicode_buffer(title_length + 1)
            if not self.user32.GetWindowTextW(handle, title_buffer, len(title_buffer)):
                continue
            title = title_buffer.value.strip()
            if not title:
                continue

            process_id = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
            class_buffer = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(handle, class_buffer, len(class_buffer))
            candidates.append(
                WindowCandidate(
                    handle=handle,
                    title=title,
                    process_id=process_id.value,
                    process_name=self.process_name(process_id.value),
                    class_name=class_buffer.value,
                )
            )
        return candidates

    def process_name(self, process_id: int) -> str:
        process = self.kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id
        )
        if not process:
            logger.warning("No se pudo consultar el proceso %s.", process_id)
            return f"PID {process_id}"

        try:
            path_buffer = ctypes.create_unicode_buffer(32768)
            path_length = wintypes.DWORD(len(path_buffer))
            if not self.kernel32.QueryFullProcessImageNameW(
                process, 0, path_buffer, ctypes.byref(path_length)
            ):
                error = ctypes.WinError(ctypes.get_last_error())
                logger.warning(
                    "No se pudo obtener el nombre del proceso %s: %s",
                    process_id,
                    error,
                )
                return f"PID {process_id}"
            return os.path.basename(path_buffer.value) or f"PID {process_id}"
        finally:
            self.kernel32.CloseHandle(process)

    def capture(self, candidate: WindowCandidate) -> ExternalWindow:
        handle = candidate.handle
        snapshot = self._inspect_hwnd(handle)
        if not snapshot.is_window:
            logger.warning(
                "HWND became invalid before capture (hwnd=%#x title=%r).",
                handle,
                candidate.title,
            )
            raise OSError(f"La ventana {candidate.title!r} ya no existe.")
        if (
            snapshot.process_id != candidate.process_id
            or snapshot.class_name != candidate.class_name
        ):
            logger.error(
                "HWND identity changed before capture (hwnd=%#x "
                "process_id=%s class_name=%r expected_pid=%s "
                "expected_class=%r title=%r).",
                handle,
                snapshot.process_id,
                snapshot.class_name,
                candidate.process_id,
                candidate.class_name,
                candidate.title,
            )
            raise OSError(f"La ventana {candidate.title!r} ya no existe.")

        style = self._get_window_long_ptr(
            handle,
            self.GWL_STYLE,
            label=candidate.title,
            expected_identity=(candidate.process_id, candidate.class_name),
        )
        extended_style = self._get_window_long_ptr(
            handle,
            self.GWL_EXSTYLE,
            label=candidate.title,
            expected_identity=(candidate.process_id, candidate.class_name),
        )
        rect = wintypes.RECT()
        succeeded, error = self._invoke_hwnd_operation(
            handle,
            "GetWindowRect",
            self.user32.GetWindowRect,
            ctypes.byref(rect),
            label=candidate.title,
            expected_identity=(candidate.process_id, candidate.class_name),
        )
        if not succeeded:
            raise ctypes.WinError(error)
        placement = _NativeWindowPlacement()
        placement.length = ctypes.sizeof(placement)
        succeeded, error = self._invoke_hwnd_operation(
            handle,
            "GetWindowPlacement",
            self.user32.GetWindowPlacement,
            ctypes.byref(placement),
            label=candidate.title,
            expected_identity=(candidate.process_id, candidate.class_name),
        )
        if not succeeded:
            raise ctypes.WinError(error)

        is_child = bool(style & self.WS_CHILD)
        parent = (snapshot.parent_hwnd or 0) if is_child else 0
        owner = (snapshot.owner_hwnd or 0) if not is_child else 0
        if owner and not self.user32.IsWindow(owner):
            logger.warning(
                "Captured invalid original owner; treating it as unowned "
                "(hwnd=%#x owner_hwnd=%#x title=%r).",
                handle,
                owner,
                candidate.title,
            )
            owner = 0
        enabled, _ = self._invoke_hwnd_operation(
            handle,
            "IsWindowEnabled",
            self.user32.IsWindowEnabled,
            window=None,
            label=candidate.title,
            expected_identity=(candidate.process_id, candidate.class_name),
        )
        visible, _ = self._invoke_hwnd_operation(
            handle,
            "IsWindowVisible",
            self.user32.IsWindowVisible,
            window=None,
            label=candidate.title,
            expected_identity=(candidate.process_id, candidate.class_name),
        )
        minimized, _ = self._invoke_hwnd_operation(
            handle,
            "IsIconic",
            self.user32.IsIconic,
            window=None,
            label=candidate.title,
            expected_identity=(candidate.process_id, candidate.class_name),
        )
        maximized, _ = self._invoke_hwnd_operation(
            handle,
            "IsZoomed",
            self.user32.IsZoomed,
            window=None,
            label=candidate.title,
            expected_identity=(candidate.process_id, candidate.class_name),
        )
        captured = ExternalWindow(
            instance_id=str(uuid.uuid4()),
            handle=handle,
            title=candidate.title,
            process_id=candidate.process_id,
            process_name=candidate.process_name,
            class_name=candidate.class_name,
            original_parent=parent,
            original_owner=owner,
            original_style=style,
            original_extended_style=extended_style,
            original_geometry=(rect.left, rect.top, rect.right, rect.bottom),
            original_placement=WindowPlacement(
                flags=placement.flags,
                show_command=placement.showCmd,
                minimum_position=(placement.ptMinPosition.x, placement.ptMinPosition.y),
                maximum_position=(placement.ptMaxPosition.x, placement.ptMaxPosition.y),
                normal_rect=(
                    placement.rcNormalPosition.left,
                    placement.rcNormalPosition.top,
                    placement.rcNormalPosition.right,
                    placement.rcNormalPosition.bottom,
                ),
            ),
            original_enabled=bool(enabled),
            original_visible=bool(visible),
            original_was_minimized=bool(minimized),
            original_was_maximized=bool(maximized),
        )
        logger.warning(
            "Captured external HWND: hwnd=%#x parent_hwnd=%#x owner_hwnd=%#x "
            "is_window=%s thread_id=%s process_id=%s style=%#x exstyle=%#x "
            "geometry=%r placement=%r title=%r.",
            handle,
            parent,
            owner,
            snapshot.is_window,
            snapshot.thread_id,
            snapshot.process_id,
            style,
            extended_style,
            captured.original_geometry,
            captured.original_placement,
            candidate.title,
        )
        return captured

    def adopt(
        self,
        window: ExternalWindow,
        parent: int,
        geometry: tuple[int, int, int, int],
    ) -> None:
        handle = window.handle
        stage = "validar la ventana y el host"
        try:
            if not self.matches_window(window):
                raise OSError(f"La ventana {window.title!r} ya no existe.")
            if not self.user32.IsWindow(parent):
                raise OSError("La superficie anfitriona de MiniFloat ya no existe.")

            stage = "comprobar que la ventana admite modificaciones"
            self._probe_writable(window)

            stage = "restaurar la ventana antes de adoptarla"
            minimized, _ = self._invoke_hwnd_operation(
                handle,
                "IsIconic",
                self.user32.IsIconic,
                window=window,
            )
            maximized, _ = self._invoke_hwnd_operation(
                handle,
                "IsZoomed",
                self.user32.IsZoomed,
                window=window,
            )
            if minimized or maximized:
                self._invoke_hwnd_operation(
                    handle,
                    "ShowWindow(SW_RESTORE)",
                    self.user32.ShowWindow,
                    self.SW_RESTORE,
                    window=window,
                )
                window.applied_steps.add("visibility")
            self._invoke_hwnd_operation(
                handle,
                "ShowWindow(SW_HIDE)",
                self.user32.ShowWindow,
                self.SW_HIDE,
                window=window,
            )
            window.applied_steps.add("visibility")

            stage = "preparar los estilos de ventana"
            if not window.original_style & self.WS_CHILD:
                self._set_owner(handle, 0, window=window)
                window.applied_steps.add("owner")
            child_style = (
                (
                    window.original_style
                    & ~self.WS_POPUP
                    & ~self.EMBEDDED_FRAME_STYLE
                    & ~(self.WS_MINIMIZE | self.WS_MAXIMIZE)
                )
                | self.WS_CHILD
            )
            embedded_extended_style = window.original_extended_style & ~(
                self.WS_EX_APPWINDOW | self.WS_EX_TOPMOST | self.WS_EX_WINDOWEDGE
            )
            self._set_window_long_ptr(
                handle, self.GWL_STYLE, child_style, window=window
            )
            window.applied_steps.add("style")
            self._set_window_long_ptr(
                handle,
                self.GWL_EXSTYLE,
                embedded_extended_style,
                window=window,
            )
            window.applied_steps.add("extended_style")

            stage = "reparentar la ventana en el host"
            self._set_parent(handle, parent, window=window)
            window.applied_steps.add("parent")
            stage = "ajustar la geometría de la ventana adoptada"
            succeeded, error = self._invoke_hwnd_operation(
                handle,
                "SetWindowPos(adopt)",
                self.user32.SetWindowPos,
                self.HWND_TOP,
                *geometry,
                self.SWP_NOACTIVATE | self.SWP_FRAMECHANGED | self.SWP_SHOWWINDOW,
                window=window,
            )
            if not succeeded:
                raise ctypes.WinError(error)
            window.applied_steps.add("geometry")
            self._invoke_hwnd_operation(
                handle,
                "EnableWindow(adopt)",
                self.user32.EnableWindow,
                window.original_enabled,
                window=window,
            )

            stage = "verificar la ventana adoptada"
            self._verify_adopted(
                window,
                parent,
                child_style,
                embedded_extended_style,
                geometry,
            )
        except OSError as error:
            raise OSError(
                f"No se pudo {stage} para {window.title!r}: {error}"
            ) from error

    def _probe_writable(self, window: ExternalWindow) -> None:
        """Reescribe el estilo actual, sin cambiarlo, antes de modificar nada.

        Windows rechaza (ERROR_ACCESS_DENIED, UIPI) las escrituras sobre
        ventanas de procesos con mayor nivel de integridad; detectarlo aquí
        evita iniciar una adopción que no se puede completar ni deshacer.
        """
        current_style = self._get_window_long_ptr(
            window.handle, self.GWL_STYLE, window=window
        )
        try:
            self._set_window_long_ptr(
                window.handle, self.GWL_STYLE, current_style, window=window
            )
        except OSError as error:
            raise OSError(
                "Windows no permite modificar esta ventana (probablemente "
                f"pertenece a un proceso con más privilegios): {error}"
            ) from error

    def client_geometry(self, handle: int) -> tuple[int, int, int, int]:
        rect = wintypes.RECT()
        succeeded, error = self._invoke_hwnd_operation(
            handle,
            "GetClientRect(host)",
            self.user32.GetClientRect,
            ctypes.byref(rect),
        )
        if not succeeded:
            raise ctypes.WinError(error)
        return (0, 0, rect.right - rect.left, rect.bottom - rect.top)

    def set_geometry(
        self, window: ExternalWindow, geometry: tuple[int, int, int, int]
    ) -> None:
        if not self.matches_window(window):
            raise OSError(f"La ventana {window.title!r} ya no existe.")
        succeeded, error = self._invoke_hwnd_operation(
            window.handle,
            "SetWindowPos(resize)",
            self.user32.SetWindowPos,
            None,
            *geometry,
            self.SWP_NOZORDER | self.SWP_NOACTIVATE | self.SWP_NOOWNERZORDER,
            window=window,
        )
        if not succeeded:
            raise ctypes.WinError(error)
        self._verify_window_size(window, geometry)

    def set_enabled(self, window: ExternalWindow, enabled: bool) -> None:
        if self.matches_window(window):
            self._invoke_hwnd_operation(
                window.handle,
                "EnableWindow",
                self.user32.EnableWindow,
                enabled,
                window=window,
            )

    def is_window(self, handle: int) -> bool:
        return bool(self.user32.IsWindow(handle))

    def matches_window(self, window: ExternalWindow) -> bool:
        snapshot = self._inspect_hwnd(window.handle)
        return (
            snapshot.is_window
            and snapshot.process_id == window.process_id
            and snapshot.class_name == window.class_name
        )

    def restore_original(self, window: ExternalWindow) -> bool:
        handle = window.handle
        if not self.matches_window(window):
            return False
        applied = window.applied_steps
        if not applied:
            logger.warning(
                "No adoption step was applied to hwnd=%#x; nothing to restore "
                "(title=%r).",
                handle,
                window.title,
            )
            return True

        stage = "ocultar la ventana"
        try:
            self._invoke_hwnd_operation(
                handle,
                "ShowWindow(SW_HIDE)",
                self.user32.ShowWindow,
                self.SW_HIDE,
                window=window,
            )
            if "parent" in applied:
                stage = "restaurar el parent original"
                self._set_parent(
                    handle, window.original_parent or 0, window=window
                )
                applied.discard("parent")
            if "style" in applied:
                stage = "restaurar el estilo original"
                self._set_window_long_ptr(
                    handle, self.GWL_STYLE, window.original_style, window=window
                )
                applied.discard("style")
            if "extended_style" in applied:
                stage = "restaurar el estilo extendido original"
                self._set_window_long_ptr(
                    handle,
                    self.GWL_EXSTYLE,
                    window.original_extended_style,
                    window=window,
                )
                applied.discard("extended_style")
            if "owner" in applied:
                stage = "restaurar el owner original"
                self._set_owner(handle, window.original_owner, window=window)
                applied.discard("owner")
            stage = "restaurar la geometría y el estado de ventana"
            frame_flags = (
                self.SWP_NOACTIVATE | self.SWP_FRAMECHANGED | self.SWP_NOOWNERZORDER
            )
            placement = _NativeWindowPlacement()
            placement.length = ctypes.sizeof(placement)
            placement.flags = window.original_placement.flags
            placement.showCmd = window.original_placement.show_command
            placement.ptMinPosition = wintypes.POINT(
                *window.original_placement.minimum_position
            )
            placement.ptMaxPosition = wintypes.POINT(
                *window.original_placement.maximum_position
            )
            placement.rcNormalPosition = wintypes.RECT(
                *window.original_placement.normal_rect
            )
            succeeded, error = self._invoke_hwnd_operation(
                handle,
                "SetWindowPlacement",
                self.user32.SetWindowPlacement,
                ctypes.byref(placement),
                window=window,
            )
            if not succeeded:
                raise ctypes.WinError(error)

            if not window.original_was_minimized and not window.original_was_maximized:
                left, top, right, bottom = window.original_geometry
                succeeded, error = self._invoke_hwnd_operation(
                    handle,
                    "SetWindowPos(restore geometry)",
                    self.user32.SetWindowPos,
                    None,
                    left,
                    top,
                    right - left,
                    bottom - top,
                    frame_flags | self.SWP_NOZORDER,
                    window=window,
                )
                if not succeeded:
                    raise ctypes.WinError(error)

            self._invoke_hwnd_operation(
                handle,
                "EnableWindow(restore)",
                self.user32.EnableWindow,
                window.original_enabled,
                window=window,
            )
            stage = "restaurar la visibilidad original"
            if window.original_visible:
                show_command = window.original_placement.show_command or self.SW_SHOWNORMAL
                if window.original_was_minimized:
                    if show_command not in (self.SW_SHOWMINIMIZED, self.SW_SHOWMINNOACTIVE):
                        show_command = self.SW_SHOWMINIMIZED
                elif window.original_was_maximized:
                    show_command = self.SW_SHOWMAXIMIZED
                self._invoke_hwnd_operation(
                    handle,
                    f"ShowWindow({show_command})",
                    self.user32.ShowWindow,
                    show_command,
                    window=window,
                )
                if not window.original_was_minimized:
                    self._invoke_hwnd_operation(
                        handle,
                        "SetForegroundWindow",
                        self.user32.SetForegroundWindow,
                        window=window,
                    )
            else:
                self._invoke_hwnd_operation(
                    handle,
                    "ShowWindow(SW_HIDE)",
                    self.user32.ShowWindow,
                    self.SW_HIDE,
                    window=window,
                )
            stage = "verificar la restauración"
            self._verify_restored(window)
            applied.clear()
        except OSError as error:
            raise OSError(
                f"No se pudo {stage} para {window.title!r}: {error}"
            ) from error
        return True

    def _verify_adopted(
        self,
        window: ExternalWindow,
        parent: int,
        expected_style: int,
        expected_extended_style: int,
        geometry: tuple[int, int, int, int],
    ) -> None:
        if not self.matches_window(window):
            raise OSError(f"La ventana {window.title!r} dejó de existir al adoptarla.")
        actual_parent, _ = self._invoke_hwnd_operation(
            window.handle,
            "GetAncestor(GA_PARENT)",
            self.user32.GetAncestor,
            self.GA_PARENT,
            window=window,
        )
        actual_parent = int(actual_parent or 0)
        actual_style = self._get_window_long_ptr(
            window.handle, self.GWL_STYLE, window=window
        )
        actual_extended_style = self._get_window_long_ptr(
            window.handle, self.GWL_EXSTYLE, window=window
        )
        actual_owner = self._get_owner(window.handle, window)
        if (
            actual_parent != parent
            or actual_owner != 0
            or not actual_style & self.WS_CHILD
            or actual_style & self.EMBEDDED_FRAME_STYLE
            or actual_style != expected_style
            or actual_extended_style != expected_extended_style
        ):
            raise OSError(
                f"No se pudo verificar el estado integrado de {window.title!r}: "
                f"parent={actual_parent:#x} (esperado {parent:#x}), "
                f"owner={actual_owner:#x}, style={actual_style:#x} "
                f"(esperado {expected_style:#x}), "
                f"exstyle={actual_extended_style:#x} "
                f"(esperado {expected_extended_style:#x})."
            )
        self._verify_window_size(window, geometry)

    def _verify_window_size(
        self, window: ExternalWindow, geometry: tuple[int, int, int, int]
    ) -> None:
        rect = wintypes.RECT()
        succeeded, error = self._invoke_hwnd_operation(
            window.handle,
            "GetWindowRect(verify size)",
            self.user32.GetWindowRect,
            ctypes.byref(rect),
            window=window,
        )
        if not succeeded:
            raise ctypes.WinError(error)
        actual_size = (rect.right - rect.left, rect.bottom - rect.top)
        if actual_size != (geometry[2], geometry[3]):
            raise OSError(
                f"No se pudo ajustar {window.title!r} al tamaño completo del workspace."
            )

    def _verify_restored(self, window: ExternalWindow) -> None:
        if not self.matches_window(window):
            raise OSError(f"La ventana {window.title!r} dejó de existir al liberarla.")

        style = self._get_window_long_ptr(
            window.handle, self.GWL_STYLE, window=window
        )
        extended_style = self._get_window_long_ptr(
            window.handle, self.GWL_EXSTYLE, window=window
        )
        actual_parent, _ = self._invoke_hwnd_operation(
            window.handle,
            "GetAncestor(GA_PARENT)",
            self.user32.GetAncestor,
            self.GA_PARENT,
            window=window,
        )
        actual_parent = int(actual_parent or 0)
        expected_parent = (
            window.original_parent
            if window.original_style & self.WS_CHILD
            else int(self.user32.GetDesktopWindow() or 0)
        )
        actual_owner = self._get_owner(window.handle, window)
        expected_owner = (
            window.original_owner
            if not window.original_style & self.WS_CHILD
            else 0
        )
        if expected_owner and not self.user32.IsWindow(expected_owner):
            expected_owner = 0
        visible, _ = self._invoke_hwnd_operation(
            window.handle,
            "IsWindowVisible(verify)",
            self.user32.IsWindowVisible,
            window=window,
        )
        enabled, _ = self._invoke_hwnd_operation(
            window.handle,
            "IsWindowEnabled(verify)",
            self.user32.IsWindowEnabled,
            window=window,
        )
        minimized, _ = self._invoke_hwnd_operation(
            window.handle,
            "IsIconic(verify)",
            self.user32.IsIconic,
            window=window,
        )
        maximized, _ = self._invoke_hwnd_operation(
            window.handle,
            "IsZoomed(verify)",
            self.user32.IsZoomed,
            window=window,
        )
        if (
            style != window.original_style
            or extended_style != window.original_extended_style
            or actual_parent != expected_parent
            or actual_owner != expected_owner
            or bool(visible) != window.original_visible
            or bool(enabled) != window.original_enabled
            or bool(minimized) != window.original_was_minimized
            or bool(maximized) != window.original_was_maximized
        ):
            raise OSError(
                f"La restauración Win32 de {window.title!r} no superó la verificación."
            )

        if not window.original_was_minimized and not window.original_was_maximized:
            rect = wintypes.RECT()
            succeeded, error = self._invoke_hwnd_operation(
                window.handle,
                "GetWindowRect(verify restore)",
                self.user32.GetWindowRect,
                ctypes.byref(rect),
                window=window,
            )
            if not succeeded:
                raise ctypes.WinError(error)
            actual_geometry = (rect.left, rect.top, rect.right, rect.bottom)
            if actual_geometry != window.original_geometry:
                raise OSError(
                    f"No se restauró la geometría original de {window.title!r}."
                )

    def _get_window_long_ptr(
        self,
        handle: int,
        index: int,
        window: ExternalWindow | None = None,
        label: str | None = None,
        expected_identity: tuple[int, str] | None = None,
    ) -> int:
        operation = (
            "GetWindowLongPtrW(GWL_STYLE)"
            if index == self.GWL_STYLE
            else "GetWindowLongPtrW(GWL_EXSTYLE)"
            if index == self.GWL_EXSTYLE
            else f"GetWindowLongPtrW(index={index})"
        )
        value, error = self._invoke_hwnd_operation(
            handle,
            operation,
            self.get_window_long_ptr,
            index,
            window=window,
            label=label,
            expected_identity=expected_identity,
        )
        if value == 0 and error:
            raise OSError(
                f"{operation} falló para hwnd={handle:#x}, index={index}, "
                f"GetLastError={error}: {ctypes.WinError(error)}"
            )
        return int(value)

    def _set_parent(
        self,
        handle: int,
        parent: int,
        window: ExternalWindow | None = None,
    ) -> None:
        previous_parent, error = self._invoke_hwnd_operation(
            handle,
            f"SetParent(parent={self._format_hwnd(parent or 0)})",
            self.user32.SetParent,
            parent or None,
            window=window,
            related_hwnds=(("parent", parent),) if parent else (),
        )
        if not previous_parent and error:
            raise OSError(
                f"SetParent falló para hwnd={handle:#x}, parent={parent:#x}, "
                f"GetLastError={error}: {ctypes.WinError(error)}"
            )

    def _set_window_long_ptr(
        self,
        handle: int,
        index: int,
        value: int,
        window: ExternalWindow | None = None,
    ) -> None:
        if index == self.GWLP_HWNDPARENT:
            raise ValueError(
                "GWLP_HWNDPARENT debe modificarse con _set_owner: su valor de "
                "retorno y GetLastError no indican el resultado."
            )
        name = "GWL_STYLE" if index == self.GWL_STYLE else "GWL_EXSTYLE"
        operation = f"SetWindowLongPtrW({name}, value={value:#x})"
        previous, error = self._invoke_hwnd_operation(
            handle,
            operation,
            self.set_window_long_ptr,
            index,
            value,
            window=window,
        )
        if previous == 0 and error:
            raise OSError(
                f"{operation} falló para hwnd={handle:#x}, "
                f"GetLastError={error}: {ctypes.WinError(error)}"
            )

    def _get_owner(
        self, handle: int, window: ExternalWindow | None = None
    ) -> int:
        owner, _ = self._invoke_hwnd_operation(
            handle,
            "GetWindow(GW_OWNER)",
            self.user32.GetWindow,
            self.GW_OWNER,
            window=window,
        )
        return int(owner or 0)

    def _set_owner(
        self, handle: int, owner: int, window: ExternalWindow | None = None
    ) -> None:
        """Fija el owner de una ventana top-level.

        En la reproducción, SetWindowLongPtrW(GWLP_HWNDPARENT, NULL) dejó
        GetLastError() en 1400 incluso después de cambiar el owner. Además,
        devuelve 0 cuando el owner previo era NULL. Se verifica el owner real
        con GW_OWNER y se omite la llamada si ya coincide.
        """
        if owner and not self.user32.IsWindow(owner):
            logger.warning(
                "Owner HWND %#x no longer exists; using no owner for hwnd=%#x.",
                owner,
                handle,
            )
            owner = 0

        current = self._get_owner(handle, window)
        if current == owner:
            logger.warning(
                "Owner of hwnd=%#x already is %s; SetWindowLongPtrW skipped.",
                handle,
                self._format_hwnd(owner),
            )
            return

        operation = f"SetWindowLongPtrW(GWLP_HWNDPARENT, owner={owner:#x})"
        previous, error = self._invoke_hwnd_operation(
            handle,
            operation,
            self.set_window_long_ptr,
            self.GWLP_HWNDPARENT,
            owner,
            window=window,
            related_hwnds=(("owner", owner),) if owner else (),
        )
        actual = self._get_owner(handle, window)
        if actual != owner:
            raise OSError(
                f"{operation} no cambió el owner de hwnd={handle:#x}: "
                f"actual={actual:#x}, esperado={owner:#x}, "
                f"previo={int(previous):#x}, GetLastError={error}"
            )
        if error:
            logger.warning(
                "%s succeeded (owner %#x -> %#x verified with GW_OWNER) despite "
                "GetLastError=%s.",
                operation,
                current,
                actual,
                error,
            )


@lru_cache(maxsize=1)
def _windows_api() -> _Win32Windows:
    return _Win32Windows()


def place_directly_below(window_handle: int, upper_handle: int) -> None:
    if sys.platform != "win32":
        raise OSError("El modo PIN OFF solo está disponible en Windows.")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_window_pos = user32.SetWindowPos
    set_window_pos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    set_window_pos.restype = wintypes.BOOL
    no_size, no_move, no_activate, no_owner_zorder = 0x0001, 0x0002, 0x0010, 0x0200
    if not set_window_pos(
        window_handle,
        upper_handle,
        0,
        0,
        0,
        0,
        no_size | no_move | no_activate | no_owner_zorder,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
