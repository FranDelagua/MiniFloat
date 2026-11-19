import ctypes
import subprocess
import sys
import unittest
from ctypes import wintypes
from types import SimpleNamespace
from unittest.mock import patch

from app.windows import (
    ExternalWindow,
    ExternalWindowState,
    ExternalWindowTransitionError,
    ADOPTION_STEPS,
    WindowCandidate,
    WindowPlacement,
    _NativeWindowPlacement,
    _Win32Windows,
)


REAL_WINDOWS_FIXTURE = """
import tkinter
root = tkinter.Tk()
root.title("minifloat-owner-test")
others = [tkinter.Toplevel(root) for _ in range(2)]
root.update()
print(*(int(w.wm_frame(), 16) for w in (others[0], others[1], root)), flush=True)
root.after(60000, root.destroy)
root.mainloop()
"""


def make_window(handle: int = 101) -> ExternalWindow:
    return ExternalWindow(
        instance_id=f"instance-{handle}",
        handle=handle,
        title=f"Window {handle}",
        process_id=handle + 1,
        process_name="app.exe",
        class_name="Window",
        original_parent=0,
        original_owner=77,
        original_style=0x80000000 | 0x10000000,
        original_extended_style=0x00040000,
        original_geometry=(10, 20, 810, 620),
        original_placement=WindowPlacement(
            flags=0,
            show_command=1,
            minimum_position=(-1, -1),
            maximum_position=(-1, -1),
            normal_rect=(10, 20, 810, 620),
        ),
        original_enabled=True,
        original_visible=True,
        original_was_minimized=False,
        original_was_maximized=False,
    )


def fill_process_id(_handle: int, pointer: int) -> int:
    ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = 102
    return 1


class FakeWindowsApi:
    def __init__(self) -> None:
        self.alive: set[int] = set()
        self.identity_matches: set[int] = set()
        self.adopt_errors: list[OSError] = []
        self.restore_errors: list[OSError] = []
        self.restore_results: list[bool] = []
        self.adoptions: list[tuple[int, int, tuple[int, int, int, int]]] = []
        self.restorations: list[ExternalWindow] = []
        self.restoration_states: list[ExternalWindowState] = []
        self.geometries: list[tuple[int, tuple[int, int, int, int]]] = []
        self.enabled: list[tuple[int, bool]] = []
        self.destroy_during_adopt = False
        self.destroy_during_restore = False

    def is_window(self, handle: int) -> bool:
        return handle in self.alive

    def matches_window(self, window: ExternalWindow) -> bool:
        return (
            window.handle in self.alive
            and window.handle in self.identity_matches
        )

    def adopt(
        self, window: ExternalWindow, parent: int, geometry: tuple[int, int, int, int]
    ) -> None:
        self.adoptions.append((window.handle, parent, geometry))
        if self.destroy_during_adopt:
            self.alive.discard(window.handle)
            raise OSError("HWND destroyed during adoption")
        if self.adopt_errors:
            raise self.adopt_errors.pop(0)

    def restore_original(self, window: ExternalWindow) -> bool:
        if window.handle not in self.alive:
            return False
        self.restorations.append(window)
        self.restoration_states.append(window.state)
        if self.destroy_during_restore:
            self.alive.discard(window.handle)
            raise OSError("HWND destroyed during restoration")
        if self.restore_errors:
            raise self.restore_errors.pop(0)
        if self.restore_results:
            return self.restore_results.pop(0)
        return window.handle in self.alive

    def set_geometry(
        self, window: ExternalWindow, geometry: tuple[int, int, int, int]
    ) -> None:
        self.geometries.append((window.handle, geometry))

    def set_enabled(self, window: ExternalWindow, enabled: bool) -> None:
        self.enabled.append((window.handle, enabled))


class NativeWindowApiTests(unittest.TestCase):
    def test_client_geometry_uses_native_client_rect(self) -> None:
        api = object.__new__(_Win32Windows)

        def get_client_rect(_handle: int, pointer: int) -> int:
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = (0, 0, 579, 286)
            return 1

        api.user32 = SimpleNamespace(
            IsWindow=lambda _handle: True,
            GetClientRect=get_client_rect,
        )
        self.assertEqual(api.client_geometry(101), (0, 0, 579, 286))

    def test_trace_records_owner_validity_identity_and_immediate_error(self) -> None:
        api = object.__new__(_Win32Windows)
        window = make_window()
        api.user32 = SimpleNamespace(
            IsWindow=lambda handle: handle in (101, 500),
            GetParent=lambda _handle: 500,
            GetWindow=lambda _handle, _command: 0,
            GetWindowThreadProcessId=fill_process_id,
            GetClassNameW=lambda _handle, buffer, _length: (
                setattr(buffer, "value", "Window") or 6
            ),
        )

        def fail(_handle: int, _index: int, _value: int) -> int:
            ctypes.set_last_error(1400)
            return 0

        api.set_window_long_ptr = fail
        with self.assertLogs("app.windows", level="WARNING") as logs:
            with self.assertRaises(OSError):
                api._set_window_long_ptr(
                    101, _Win32Windows.GWL_STYLE, 42, window=window
                )

        before, after = logs.output
        self.assertIn("is_window(hwnd)=True", before)
        self.assertIn("parent_hwnd=0x1f4 is_window(parent)=True", before)
        self.assertIn("owner_hwnd=0x0 is_window(owner)=False", before)
        self.assertIn("original_owner=0x4d is_window(original_owner)=False", before)
        self.assertIn("pid=102 thread_id=1", before)
        self.assertIn("result=0 GetLastError=1400", after)

    def test_invalid_hwnd_is_never_passed_to_a_mutating_operation(self) -> None:
        api = object.__new__(_Win32Windows)
        calls: list[tuple] = []
        api.user32 = SimpleNamespace(IsWindow=lambda _handle: False)

        with self.assertRaisesRegex(OSError, "se omitió la llamada Win32"):
            api._invoke_hwnd_operation(
                101,
                "SetParent",
                lambda handle, parent: calls.append((handle, parent)),
                500,
            )

        self.assertEqual(calls, [])

    def test_hwnd_destroyed_by_operation_stops_following_win32_calls(self) -> None:
        api = object.__new__(_Win32Windows)
        alive = [True]
        calls: list[tuple] = []
        api.user32 = SimpleNamespace(IsWindow=lambda _handle: alive[0])

        def destroy_window(handle: int, command: int) -> int:
            calls.append(("ShowWindow", handle, command))
            alive[0] = False
            return 1

        with self.assertRaisesRegex(OSError, "dejó de ser válido durante"):
            api._invoke_hwnd_operation(
                101,
                "ShowWindow(SW_HIDE)",
                destroy_window,
                _Win32Windows.SW_HIDE,
            )
            api._invoke_hwnd_operation(
                101,
                "SetWindowLongPtrW(GWL_STYLE)",
                lambda handle, *_args: calls.append(("SetWindowLongPtrW", handle)),
            )

        self.assertEqual(calls, [("ShowWindow", 101, _Win32Windows.SW_HIDE)])

    def test_style_setter_refuses_gwlp_hwndparent(self) -> None:
        api = object.__new__(_Win32Windows)
        api.user32 = SimpleNamespace(IsWindow=lambda _handle: True)
        api.set_window_long_ptr = lambda *_args: self.fail("must not be called")

        with self.assertRaises(ValueError):
            api._set_window_long_ptr(101, _Win32Windows.GWLP_HWNDPARENT, 0)

    def make_owner_api(
        self,
        owner: int,
        alive: tuple[int, ...] = (101, 77),
        fails: bool = False,
    ) -> tuple[_Win32Windows, list[int], list[tuple]]:
        """Modelo de user32 con la semántica medida en Windows.

        GWLP_HWNDPARENT=NULL deja GetLastError=1400 aunque tenga éxito; un
        HWND inexistente da 87 y no cambia nada.
        """
        api = object.__new__(_Win32Windows)
        state = [owner]
        calls: list[tuple] = []
        live = set(alive)

        def set_long(handle: int, index: int, value: int) -> int:
            calls.append((handle, index, value))
            previous = state[0]
            if fails:
                ctypes.set_last_error(5 if value else 1400)
                return 0
            if value and value not in live:
                ctypes.set_last_error(87)
                return 0
            state[0] = value
            ctypes.set_last_error(1400 if value == 0 else 0)
            return previous

        api.user32 = SimpleNamespace(
            IsWindow=lambda handle: handle in live,
            GetWindow=lambda _handle, _command: state[0],
            GetParent=lambda _handle: 0,
            GetWindowThreadProcessId=fill_process_id,
            GetClassNameW=lambda _handle, buffer, _length: (
                setattr(buffer, "value", "Window") or 6
            ),
        )
        api.set_window_long_ptr = set_long
        return api, state, calls

    def test_clearing_an_owner_that_is_already_null_makes_no_win32_call(self) -> None:
        api, state, calls = self.make_owner_api(owner=0)

        api._set_owner(101, 0, window=make_window())

        self.assertEqual(calls, [])
        self.assertEqual(state, [0])

    def test_clearing_a_real_owner_succeeds_despite_spurious_error_1400(self) -> None:
        api, state, calls = self.make_owner_api(owner=77)

        with self.assertLogs("app.windows", level="WARNING") as logs:
            api._set_owner(101, 0, window=make_window())

        self.assertEqual(calls, [(101, _Win32Windows.GWLP_HWNDPARENT, 0)])
        self.assertEqual(state, [0])
        self.assertTrue(
            any(
                "verified with GW_OWNER) despite GetLastError=1400" in line
                for line in logs.output
            )
        )

    def test_setting_a_valid_owner_is_verified_with_gw_owner(self) -> None:
        api, state, calls = self.make_owner_api(owner=0)

        api._set_owner(101, 77, window=make_window())

        self.assertEqual(calls, [(101, _Win32Windows.GWLP_HWNDPARENT, 77)])
        self.assertEqual(state, [77])

    def test_restoring_the_current_owner_makes_no_win32_call(self) -> None:
        api, state, calls = self.make_owner_api(owner=77)

        api._set_owner(101, 77, window=make_window())

        self.assertEqual(calls, [])
        self.assertEqual(state, [77])

    def test_destroyed_owner_is_replaced_by_no_owner_without_using_it(self) -> None:
        api, state, calls = self.make_owner_api(owner=0, alive=(101,))

        api._set_owner(101, 77, window=make_window())

        self.assertEqual(calls, [])
        self.assertEqual(state, [0])

    def test_destroyed_owner_is_cleared_when_the_window_still_has_it(self) -> None:
        api, state, calls = self.make_owner_api(owner=55, alive=(101, 55))

        api._set_owner(101, 77, window=make_window())

        self.assertEqual(calls, [(101, _Win32Windows.GWLP_HWNDPARENT, 0)])
        self.assertEqual(state, [0])

    def test_owner_change_that_does_not_happen_is_an_error_even_with_1400(self) -> None:
        for target in (0, 77):
            with self.subTest(target=target):
                api, state, _calls = self.make_owner_api(owner=88, alive=(101, 77, 88), fails=True)

                with self.assertRaisesRegex(OSError, "no cambió el owner"):
                    api._set_owner(101, target, window=make_window())

                self.assertEqual(state, [88])

    def test_owner_operation_on_destroyed_hwnd_makes_no_win32_call(self) -> None:
        api, _state, calls = self.make_owner_api(owner=77, alive=(77,))

        with self.assertRaisesRegex(OSError, "se omitió la llamada Win32"):
            api._set_owner(101, 0, window=make_window())

        self.assertEqual(calls, [])

    @unittest.skipUnless(sys.platform == "win32", "requiere Windows")
    def test_real_top_level_windows_from_another_process(self) -> None:
        """Verifica contra Win32 real, con ventanas de otro proceso."""
        child = subprocess.Popen(
            [sys.executable, "-c", REAL_WINDOWS_FIXTURE],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(child.wait, 10)
        self.addCleanup(child.kill)
        line = child.stdout.readline().split()
        if len(line) != 3:
            self.skipTest("tkinter no disponible para crear ventanas reales")

        api = _Win32Windows()
        owned, other, owner = (int(value) for value in line)
        for handle in (owned, other, owner):
            self.assertTrue(api.user32.IsWindow(handle))
        window = api._inspect_hwnd(owned)
        external = make_window(owned)
        external.process_id = window.process_id
        external.class_name = window.class_name or ""

        self.assertEqual(api._get_owner(owned, external), 0)
        api._set_owner(owned, 0, window=external)  # NULL -> NULL: antes daba 1400
        self.assertEqual(api._get_owner(owned, external), 0)
        api._set_owner(owned, owner, window=external)
        self.assertEqual(api._get_owner(owned, external), owner)
        api._set_owner(owned, other, window=external)
        self.assertEqual(api._get_owner(owned, external), other)
        api._set_owner(owned, 0, window=external)  # owner real -> NULL: 1400 espurio
        self.assertEqual(api._get_owner(owned, external), 0)
        self.assertEqual(api.user32.GetParent(owned) or 0, 0)

    def test_capture_saves_all_original_window_state(self) -> None:
        api = object.__new__(_Win32Windows)
        style = _Win32Windows.WS_POPUP | 0x10000000
        extended_style = (
            _Win32Windows.WS_EX_APPWINDOW
            | _Win32Windows.WS_EX_TOPMOST
            | 0x00000080
        )
        api.get_window_long_ptr = lambda _handle, index: {
            _Win32Windows.GWL_STYLE: style,
            _Win32Windows.GWL_EXSTYLE: extended_style,
        }[index]

        def fill_rect(_handle: int, pointer: int) -> int:
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = 10, 20, 810, 620
            return 1

        def fill_placement(_handle: int, pointer: int) -> int:
            placement = ctypes.cast(
                pointer, ctypes.POINTER(_NativeWindowPlacement)
            ).contents
            placement.flags = 3
            placement.showCmd = _Win32Windows.SW_SHOW
            placement.ptMinPosition = wintypes.POINT(1, 2)
            placement.ptMaxPosition = wintypes.POINT(3, 4)
            placement.rcNormalPosition = wintypes.RECT(10, 20, 810, 620)
            return 1

        api.user32 = SimpleNamespace(
            IsWindow=lambda candidate_handle: candidate_handle == 101,
            GetWindowThreadProcessId=lambda _handle, pointer: (
                setattr(
                    ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents,
                    "value",
                    202,
                )
                or 1
            ),
            GetClassNameW=lambda _handle, buffer, _length: (
                setattr(buffer, "value", "Chrome_WidgetWin") or 16
            ),
            GetWindowRect=fill_rect,
            GetWindowPlacement=fill_placement,
            GetParent=lambda _handle: 999,
            GetWindow=lambda _handle, _command: 777,
            IsWindowEnabled=lambda _handle: False,
            IsWindowVisible=lambda _handle: True,
            IsIconic=lambda _handle: True,
            IsZoomed=lambda _handle: False,
        )
        candidate = WindowCandidate(101, "Chrome", 202, "chrome.exe", "Chrome_WidgetWin")

        captured = api.capture(candidate)

        self.assertEqual(captured.original_parent, 0)
        self.assertEqual(captured.original_owner, 0)
        self.assertEqual(captured.original_style, style)
        self.assertEqual(captured.original_extended_style, extended_style)
        self.assertEqual(captured.original_geometry, (10, 20, 810, 620))
        self.assertEqual(
            captured.original_placement,
            WindowPlacement(3, 5, (1, 2), (3, 4), (10, 20, 810, 620)),
        )
        self.assertFalse(captured.original_enabled)
        self.assertTrue(captured.original_visible)
        self.assertTrue(captured.original_was_minimized)
        self.assertFalse(captured.original_was_maximized)

    def test_adoption_applies_child_styles_parent_and_full_geometry(self) -> None:
        api = object.__new__(_Win32Windows)
        calls: list[tuple] = []
        window = make_window()
        window.original_extended_style |= _Win32Windows.WS_EX_WINDOWEDGE
        styles = {
            _Win32Windows.GWL_STYLE: window.original_style,
            _Win32Windows.GWL_EXSTYLE: window.original_extended_style,
        }
        owner = [window.original_owner]

        def fill_rect(_handle: int, pointer: int) -> int:
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = 100, 200, 1000, 800
            return 1

        def set_style(_handle: int, index: int, value: int) -> int:
            calls.append(("style", _handle, index, value))
            if index == _Win32Windows.GWLP_HWNDPARENT:
                previous, owner[0] = owner[0], value
                if value == 0:
                    ctypes.set_last_error(1400)
                return previous
            previous = styles.get(index, 0)
            styles[index] = value
            return previous

        api.user32 = SimpleNamespace(
            IsWindow=lambda _handle: True,
            GetWindowThreadProcessId=fill_process_id,
            GetClassNameW=lambda _handle, buffer, _length: (
                setattr(buffer, "value", "Window") or 6
            ),
            GetAncestor=lambda _handle, _kind: 500,
            GetWindowRect=fill_rect,
            GetWindow=lambda _handle, _command: owner[0],
            IsIconic=lambda _handle: False,
            IsZoomed=lambda _handle: False,
            ShowWindow=lambda handle, command: calls.append(
                ("show", handle, command)
            )
            or 1,
            SetParent=lambda handle, parent: calls.append(
                ("parent", handle, parent)
            )
            or 999,
            SetWindowPos=lambda *args: calls.append(("geometry", *args)) or 1,
            EnableWindow=lambda handle, enabled: calls.append(
                ("enable", handle, enabled)
            )
            or 1,
        )
        api.get_window_long_ptr = lambda _handle, index: styles[index]
        api.set_window_long_ptr = set_style

        api.adopt(window, 500, (0, 0, 900, 600))
        self.assertEqual(window.applied_steps, ADOPTION_STEPS)
        self.assertIn(
            (
                "style",
                101,
                _Win32Windows.GWL_STYLE,
                (
                    window.original_style
                    & ~_Win32Windows.WS_POPUP
                    & ~_Win32Windows.EMBEDDED_FRAME_STYLE
                )
                | _Win32Windows.WS_CHILD,
            ),
            calls,
        )
        self.assertIn(
            ("parent", 101, 500),
            calls,
        )
        self.assertIn(
            (
                "style",
                101,
                _Win32Windows.GWL_EXSTYLE,
                window.original_extended_style
                & ~_Win32Windows.WS_EX_APPWINDOW
                & ~_Win32Windows.WS_EX_TOPMOST
                & ~_Win32Windows.WS_EX_WINDOWEDGE,
            ),
            calls,
        )
        self.assertIn(
            ("style", 101, _Win32Windows.GWLP_HWNDPARENT, 0),
            calls,
        )
        geometry_call = next(call for call in calls if call[0] == "geometry")
        self.assertEqual(geometry_call[3:7], (0, 0, 900, 600))

    def make_adoption_api(
        self, window: ExternalWindow, deny_style: bool = False, deny_parent: bool = False
    ) -> tuple[_Win32Windows, list[tuple]]:
        """user32 con estado mínimo; los accesos denegados reproducen UIPI."""
        api = object.__new__(_Win32Windows)
        calls: list[tuple] = []
        styles = {
            _Win32Windows.GWL_STYLE: window.original_style,
            _Win32Windows.GWL_EXSTYLE: window.original_extended_style,
        }
        owner = [window.original_owner]

        def set_long(handle: int, index: int, value: int) -> int:
            calls.append(("set_long", handle, index, value))
            if index == _Win32Windows.GWLP_HWNDPARENT:
                previous, owner[0] = owner[0], value
                ctypes.set_last_error(1400 if value == 0 else 0)
                return previous
            if deny_style:
                ctypes.set_last_error(5)
                return 0
            previous = styles[index]
            styles[index] = value
            return previous

        def set_parent(handle: int, parent: int | None) -> int:
            calls.append(("parent", handle, parent))
            if deny_parent:
                ctypes.set_last_error(5)
                return 0
            return 999

        def rect(_handle: int, pointer: int) -> int:
            area = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            area.left, area.top, area.right, area.bottom = 10, 20, 810, 620
            return 1

        api.user32 = SimpleNamespace(
            IsWindow=lambda _handle: True,
            GetWindowThreadProcessId=fill_process_id,
            GetClassNameW=lambda _handle, buffer, _length: (
                setattr(buffer, "value", "Window") or 6
            ),
            GetWindow=lambda _handle, _command: owner[0],
            GetAncestor=lambda _handle, _kind: 0,
            GetDesktopWindow=lambda: 0,
            GetWindowRect=rect,
            IsIconic=lambda _handle: False,
            IsZoomed=lambda _handle: False,
            IsWindowVisible=lambda _handle: True,
            IsWindowEnabled=lambda _handle: True,
            ShowWindow=lambda handle, command: calls.append(("show", handle, command)) or 1,
            SetParent=set_parent,
            SetWindowPos=lambda *args: calls.append(("geometry", *args)) or 1,
            SetWindowPlacement=lambda *args: calls.append(("placement", args[0])) or 1,
            EnableWindow=lambda handle, enabled: calls.append(("enable", handle, enabled)) or 1,
            SetForegroundWindow=lambda handle: calls.append(("foreground", handle)) or 1,
        )
        api.get_window_long_ptr = lambda _handle, index: styles[index]
        api.set_window_long_ptr = set_long
        return api, calls

    def test_adoption_does_not_restore_minimized_or_maximized_style(self) -> None:
        for state_bit in (_Win32Windows.WS_MAXIMIZE, _Win32Windows.WS_MINIMIZE):
            with self.subTest(state_bit=state_bit):
                window = make_window()
                window.original_style = 0x16CF0000 | state_bit
                window.original_was_maximized = state_bit == _Win32Windows.WS_MAXIMIZE
                window.original_was_minimized = state_bit == _Win32Windows.WS_MINIMIZE
                styles = {
                    _Win32Windows.GWL_STYLE: window.original_style,
                    _Win32Windows.GWL_EXSTYLE: window.original_extended_style,
                }
                api, calls = self.make_adoption_api(window)
                api.user32.GetAncestor = lambda _handle, _kind: 500
                api.user32.IsZoomed = lambda _handle: window.original_was_maximized
                api.user32.IsIconic = lambda _handle: window.original_was_minimized

                def set_style(handle: int, index: int, value: int) -> int:
                    if index == _Win32Windows.GWLP_HWNDPARENT:
                        return 0
                    previous = styles[index]
                    styles[index] = value
                    calls.append(("set_long", handle, index, value))
                    return previous

                def show_window(_handle: int, command: int) -> int:
                    if command == _Win32Windows.SW_RESTORE:
                        styles[_Win32Windows.GWL_STYLE] &= ~state_bit
                    return 1

                def set_position(*_args: object) -> int:
                    styles[_Win32Windows.GWL_STYLE] &= ~state_bit
                    return 1

                window.original_owner = 0
                api.user32.GetWindow = lambda _handle, _command: 0
                api.user32.ShowWindow = show_window
                api.user32.SetWindowPos = set_position
                api.get_window_long_ptr = lambda _handle, index: styles[index]
                api.set_window_long_ptr = set_style

                api.adopt(window, 500, (0, 0, 800, 600))

                child_style = next(
                    call[3]
                    for call in calls
                    if call[0] == "set_long"
                    and call[2] == _Win32Windows.GWL_STYLE
                    and call[3] & _Win32Windows.WS_CHILD
                )
                self.assertEqual(child_style, 0x56000000)
                self.assertEqual(window.original_style, 0x16CF0000 | state_bit)

    def test_window_that_cannot_be_modified_is_rejected_before_any_change(self) -> None:
        window = make_window()
        api, calls = self.make_adoption_api(window, deny_style=True)

        with self.assertRaisesRegex(OSError, "no permite modificar"):
            api.adopt(window, 500, (0, 0, 900, 600))

        self.assertEqual(window.applied_steps, set())
        self.assertEqual({call[0] for call in calls}, {"set_long"})
        self.assertEqual(len(calls), 1)

        calls.clear()
        self.assertTrue(api.restore_original(window))
        self.assertEqual(calls, [])

    def test_rollback_only_undoes_the_steps_that_were_applied(self) -> None:
        window = make_window()
        api, calls = self.make_adoption_api(window, deny_parent=True)

        with self.assertRaisesRegex(OSError, "reparentar"):
            api.adopt(window, 500, (0, 0, 900, 600))

        self.assertEqual(
            window.applied_steps, {"visibility", "owner", "style", "extended_style"}
        )
        calls.clear()
        self.assertTrue(api.restore_original(window))

        self.assertNotIn("parent", {call[0] for call in calls})
        self.assertIn(("set_long", 101, _Win32Windows.GWL_STYLE, window.original_style), calls)
        self.assertIn(
            ("set_long", 101, _Win32Windows.GWLP_HWNDPARENT, window.original_owner), calls
        )
        self.assertEqual(window.applied_steps, set())

    def test_resize_positions_external_window_to_workspace_geometry(self) -> None:
        api = object.__new__(_Win32Windows)
        calls: list[tuple] = []
        window = make_window()
        geometry = [100, 200, 1000, 800]

        def set_geometry(*args) -> int:
            calls.append(args)
            geometry[:] = (
                args[2],
                args[3],
                args[2] + args[4],
                args[3] + args[5],
            )
            return 1

        def get_rect(_handle: int, pointer: int) -> int:
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = geometry
            return 1

        api.user32 = SimpleNamespace(
            IsWindow=lambda _handle: True,
            GetWindowThreadProcessId=fill_process_id,
            GetClassNameW=lambda _handle, buffer, _length: (
                setattr(buffer, "value", "Window") or 6
            ),
            SetWindowPos=set_geometry,
            GetWindowRect=get_rect,
        )

        api.set_geometry(window, (0, 0, 900, 600))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1:6], (None, 0, 0, 900, 600))
        self.assertEqual(
            calls[0][6],
            api.SWP_NOZORDER | api.SWP_NOACTIVATE | api.SWP_NOOWNERZORDER,
        )

    def test_restore_reparents_styles_geometry_placement_and_show_state(self) -> None:
        api = object.__new__(_Win32Windows)
        calls: list[tuple] = []
        window = make_window()
        styles = {
            _Win32Windows.GWL_STYLE: window.original_style,
            _Win32Windows.GWL_EXSTYLE: window.original_extended_style,
        }
        geometry = list(window.original_geometry)
        owner = [0]
        visible = [window.original_visible]
        enabled = [window.original_enabled]

        def set_style(_handle: int, index: int, value: int) -> int:
            if index == _Win32Windows.GWLP_HWNDPARENT:
                previous = owner[0]
                owner[0] = value
                if value == 0:
                    ctypes.set_last_error(1400)
            else:
                previous = styles.get(index, 0)
                styles[index] = value
            calls.append(("style", _handle, index, value))
            return previous

        def set_geometry(*args) -> int:
            calls.append(("geometry", *args))
            geometry[:] = (
                args[2],
                args[3],
                args[2] + args[4],
                args[3] + args[5],
            )
            return 1

        def get_rect(_handle: int, pointer: int) -> int:
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = geometry
            return 1

        def save_placement(handle: int, pointer: int) -> int:
            placement = ctypes.cast(
                pointer, ctypes.POINTER(_NativeWindowPlacement)
            ).contents
            calls.append(
                (
                    "placement",
                    handle,
                    placement.showCmd,
                    placement.rcNormalPosition.left,
                    placement.rcNormalPosition.top,
                    placement.rcNormalPosition.right,
                    placement.rcNormalPosition.bottom,
                )
            )
            return 1

        api.user32 = SimpleNamespace(
            IsWindow=lambda _handle: True,
            GetWindowThreadProcessId=fill_process_id,
            GetClassNameW=lambda _handle, buffer, _length: (
                setattr(buffer, "value", "Window") or 6
            ),
            GetAncestor=lambda _handle, _kind: 1,
            GetDesktopWindow=lambda: 1,
            GetWindow=lambda _handle, _command: owner[0],
            GetWindowRect=get_rect,
            IsWindowVisible=lambda _handle: visible[0],
            IsWindowEnabled=lambda _handle: enabled[0],
            IsIconic=lambda _handle: False,
            IsZoomed=lambda _handle: False,
            ShowWindow=lambda handle, command: calls.append(
                ("show", handle, command)
            ) or visible.__setitem__(0, command != _Win32Windows.SW_HIDE) or 1,
            SetParent=lambda handle, parent: calls.append(
                ("parent", handle, parent)
            )
            or 500,
            SetWindowPos=set_geometry,
            SetWindowPlacement=save_placement,
            EnableWindow=lambda handle, enabled: calls.append(
                ("enable", handle, enabled)
            )
            or 1,
            SetForegroundWindow=lambda handle: calls.append(
                ("foreground", handle)
            )
            or 1,
        )
        api.get_window_long_ptr = lambda _handle, index: styles[index]
        api.set_window_long_ptr = set_style
        window.applied_steps = set(ADOPTION_STEPS)

        self.assertTrue(api.restore_original(window))
        self.assertEqual(window.applied_steps, set())

        self.assertIn(("parent", 101, None), calls)
        self.assertIn(
            ("style", 101, _Win32Windows.GWL_STYLE, window.original_style),
            calls,
        )
        self.assertIn(
            (
                "style",
                101,
                _Win32Windows.GWL_EXSTYLE,
                window.original_extended_style,
            ),
            calls,
        )
        self.assertIn(
            (
                "style",
                101,
                _Win32Windows.GWLP_HWNDPARENT,
                window.original_owner,
            ),
            calls,
        )
        geometry_call = next(call for call in calls if call[0] == "geometry")
        self.assertEqual(geometry_call[3:7], (10, 20, 800, 600))
        placement_call = next(call for call in calls if call[0] == "placement")
        self.assertEqual(placement_call, ("placement", 101, 1, 10, 20, 810, 620))
        self.assertLess(calls.index(placement_call), calls.index(geometry_call))
        self.assertIn(("show", 101, 1), calls)
        self.assertIn(("foreground", 101), calls)


class ExternalWindowLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeWindowsApi()
        self.window = make_window()
        self.api.alive.add(self.window.handle)
        self.api.identity_matches.add(self.window.handle)
        self.api_patch = patch("app.windows._windows_api", return_value=self.api)
        self.api_patch.start()
        self.addCleanup(self.api_patch.stop)

    def test_adoption_and_resize_use_host_geometry(self) -> None:
        geometry = (0, 0, 1200, 700)
        self.window.adopt(500, geometry)
        self.window.set_geometry((0, 0, 900, 600))

        self.assertEqual(self.window.state, ExternalWindowState.ADOPTED)
        self.assertEqual(self.window.adopted_parent, 500)
        self.assertEqual(self.window.adopted_geometry, (0, 0, 900, 600))
        self.assertEqual(self.api.adoptions, [(101, 500, geometry)])
        self.assertEqual(self.api.geometries, [(101, (0, 0, 900, 600))])

    def test_release_restores_original_snapshot(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))

        self.assertTrue(self.window.release())

        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)
        self.assertIsNone(self.window.adopted_parent)
        self.assertEqual(self.api.restorations, [self.window])

    def test_partial_adoption_rollback_requires_a_live_window(self) -> None:
        self.api.adopt_errors.append(OSError("partial adoption failed"))
        self.api.restore_results.append(False)

        with self.assertRaisesRegex(OSError, "partial adoption failed"):
            self.window.adopt(500, (0, 0, 1200, 700))

        self.assertEqual(self.window.state, ExternalWindowState.RECOVERY_REQUIRED)
        self.assertEqual(self.api.restorations, [self.window])
        self.assertEqual(self.window.original_owner, 77)
        self.assertEqual(self.window.original_style, 0x90000000)
        self.assertEqual(self.window.original_geometry, (10, 20, 810, 620))

    def test_double_adoption_is_rejected_without_win32_calls(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))

        with self.assertRaises(ExternalWindowTransitionError):
            self.window.adopt(500, (0, 0, 1200, 700))

        self.assertEqual(len(self.api.adoptions), 1)
        self.assertEqual(self.window.state, ExternalWindowState.ADOPTED)

    def test_double_release_does_not_touch_the_window_again(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))
        self.assertTrue(self.window.release())

        self.assertFalse(self.window.release())

        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)
        self.assertEqual(len(self.api.restorations), 1)
        with self.assertRaises(ExternalWindowTransitionError):
            self.window.adopt(500, (0, 0, 1200, 700))

    def test_closed_window_is_discarded_without_restoration(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))
        self.api.alive.remove(self.window.handle)

        self.assertFalse(self.window.release())

        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)
        self.assertEqual(self.api.restorations, [])

    def test_invalid_hwnd_fails_before_adoption(self) -> None:
        self.api.alive.clear()

        with self.assertRaises(OSError):
            self.window.adopt(500, (0, 0, 1200, 700))

        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)
        self.assertEqual(self.api.adoptions, [])

    def test_hwnd_destroyed_during_adoption_skips_rollback(self) -> None:
        self.api.destroy_during_adopt = True

        with self.assertRaisesRegex(OSError, "destroyed during adoption"):
            self.window.adopt(500, (0, 0, 1200, 700))

        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)
        self.assertIsNone(self.window.adopted_parent)
        self.assertEqual(self.api.restorations, [])

    def test_hwnd_destroyed_during_release_skips_readoption(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))
        self.api.destroy_during_restore = True

        self.assertFalse(self.window.release())

        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)
        self.assertIsNone(self.window.adopted_parent)
        self.assertEqual(len(self.api.adoptions), 1)
        self.assertEqual(
            self.api.restoration_states, [ExternalWindowState.RELEASING]
        )

    def test_reused_hwnd_with_different_identity_is_not_restored(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))
        self.api.identity_matches.clear()

        self.assertFalse(self.window.is_alive())
        self.assertFalse(self.window.release())
        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)
        self.assertEqual(self.api.restorations, [])

    def test_failed_adoption_rolls_back_original_state(self) -> None:
        self.api.adopt_errors.append(OSError("adoption failed"))

        with self.assertRaisesRegex(OSError, "adoption failed"):
            self.window.adopt(500, (0, 0, 1200, 700))

        self.assertEqual(self.window.state, ExternalWindowState.NOT_ADOPTED)
        self.assertIsNone(self.window.adopted_parent)
        self.assertEqual(self.api.restorations, [self.window])
        self.assertEqual(
            self.api.restoration_states, [ExternalWindowState.ROLLING_BACK]
        )

    def test_failed_adoption_and_rollback_retains_recovery_state(self) -> None:
        self.api.adopt_errors.append(OSError("adoption failed"))
        self.api.restore_errors.append(OSError("rollback failed"))

        with self.assertRaisesRegex(
            ExternalWindowTransitionError,
            "rollback failed.*error original: adoption failed",
        ):
            self.window.adopt(500, (0, 0, 1200, 700))

        self.assertEqual(self.window.state, ExternalWindowState.RECOVERY_REQUIRED)
        self.assertTrue(self.window.release())
        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)

    def test_failed_release_rolls_back_to_adopted_state(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))
        self.api.restore_errors.append(OSError("release failed"))

        with self.assertRaisesRegex(OSError, "release failed"):
            self.window.release()

        self.assertEqual(self.window.state, ExternalWindowState.ADOPTED)
        self.assertEqual(len(self.api.adoptions), 2)
        self.assertEqual(self.window.adopted_parent, 500)

        self.assertTrue(self.window.release())

    def test_unverified_release_rolls_back_to_adopted_state(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))
        self.api.restore_results.append(False)

        with self.assertRaisesRegex(OSError, "verificar la liberación"):
            self.window.release()

        self.assertEqual(self.window.state, ExternalWindowState.ADOPTED)
        self.assertEqual(len(self.api.adoptions), 2)
        self.assertTrue(self.window.release())

    def test_failed_release_and_rollback_retains_recovery_state(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))
        self.api.restore_errors.append(OSError("release failed"))
        self.api.adopt_errors.append(OSError("re-adoption failed"))

        with self.assertRaises(ExternalWindowTransitionError):
            self.window.release()

        self.assertEqual(self.window.state, ExternalWindowState.RECOVERY_REQUIRED)
        self.assertTrue(self.window.release())
        self.assertEqual(self.window.state, ExternalWindowState.RELEASED)

    def test_interactive_state_is_applied_to_external_window(self) -> None:
        self.window.adopt(500, (0, 0, 1200, 700))

        self.window.set_interactive(False)
        self.window.set_interactive(True)

        self.assertEqual(self.api.enabled, [(101, False), (101, True)])

    def test_multiple_external_windows_keep_independent_lifecycles(self) -> None:
        second = make_window(202)
        self.api.alive.add(second.handle)
        self.api.identity_matches.add(second.handle)

        self.window.adopt(500, (0, 0, 1200, 700))
        second.adopt(600, (0, 0, 800, 600))
        self.assertTrue(second.release())
        self.assertEqual(self.window.state, ExternalWindowState.ADOPTED)
        self.assertEqual(second.state, ExternalWindowState.RELEASED)
        self.assertEqual(
            self.api.adoptions,
            [(101, 500, (0, 0, 1200, 700)), (202, 600, (0, 0, 800, 600))],
        )


if __name__ == "__main__":
    unittest.main()
