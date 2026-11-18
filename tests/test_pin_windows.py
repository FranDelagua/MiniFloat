import ctypes
import os
import subprocess
import sys
import time
import unittest
import uuid
from ctypes import wintypes

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QSlider

from ui.desktop import Desktop
from ui.window import MainWindow


@unittest.skipUnless(sys.platform == "win32", "Windows is required")
class PinWindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)
        if cls.application.platformName() != "windows":
            raise unittest.SkipTest("The Windows Qt platform plugin is required")

    def test_selective_input_over_another_process(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = wintypes.BOOL
        user32.mouse_event.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.ULONG
        ]
        user32.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.PostMessageW.restype = wintypes.BOOL

        title = f"MiniFloat test {uuid.uuid4()}"
        click_log = os.path.join(os.environ.get("TEMP", "."), f"{uuid.uuid4()}.txt")
        code = """
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

class Target(QWidget):
    def mousePressEvent(self, event):
        with open(sys.argv[2], "a", encoding="utf-8") as file:
            file.write("click\\n")

app = QApplication([])
window = Target()
window.setWindowTitle(sys.argv[1])
window.setGeometry(30, 30, 1100, 700)
window.setStyleSheet("background: #00ee00")
window.show()
QTimer.singleShot(30000, app.quit)
sys.exit(app.exec())
"""
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "windows"
        process = subprocess.Popen(
            [sys.executable, "-c", code, title, click_log],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        background = None
        window = None
        try:
            for _ in range(100):
                background = user32.FindWindowW(None, title)
                if background:
                    break
                if process.poll() is not None:
                    self.fail(f"Background process exited: {process.stderr.read()!r}")
                time.sleep(0.1)
            self.assertTrue(background, "Background process did not create its window")

            window = MainWindow()
            window.move(150, 100)
            blank = QPoint(10, window.height() - 60)
            probe = window.mapToGlobal(blank)
            underlay = user32.GetAncestor(
                user32.WindowFromPoint(wintypes.POINT(probe.x(), probe.y())), 2
            )
            window.show()
            self.application.processEvents()
            desktop = window.findChild(Desktop)
            bar = window._control_bar
            self.assertIsNotNone(desktop)
            self.assertIsNotNone(bar)
            first = desktop.subWindowList()[0]
            slider_widget = bar.findChild(QSlider, "opacitySlider")

            def root_at(point: QPoint) -> int:
                rect = wintypes.RECT()
                self.assertTrue(user32.GetWindowRect(int(window.winId()), ctypes.byref(rect)))
                scale = window.devicePixelRatioF()
                point = wintypes.POINT(
                    round(rect.left + point.x() * scale),
                    round(rect.top + point.y() * scale),
                )
                hit = user32.WindowFromPoint(point)
                return user32.GetAncestor(hit, 2)

            def describe_handle(handle: int) -> str:
                class_name = ctypes.create_unicode_buffer(256)
                title_text = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(handle, class_name, len(class_name))
                user32.GetWindowTextW(handle, title_text, len(title_text))
                return f"{handle}: {class_name.value!r}/{title_text.value!r}"

            def click_at(point: QPoint) -> None:
                rect = wintypes.RECT()
                self.assertTrue(
                    user32.GetWindowRect(int(window.winId()), ctypes.byref(rect))
                )
                scale = window.devicePixelRatioF()
                x = round(rect.left + point.x() * scale)
                y = round(rect.top + point.y() * scale)
                self.assertTrue(user32.SetCursorPos(x, y))
                time.sleep(0.1)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.05)
                user32.mouse_event(0x0004, 0, 0, 0, 0)

            def drag_at(start: QPoint, end: QPoint) -> None:
                rect = wintypes.RECT()
                self.assertTrue(
                    user32.GetWindowRect(int(window.winId()), ctypes.byref(rect))
                )
                scale = window.devicePixelRatioF()
                start_x = round(rect.left + start.x() * scale)
                start_y = round(rect.top + start.y() * scale)
                end_x = round(rect.left + end.x() * scale)
                end_y = round(rect.top + end.y() * scale)
                self.assertTrue(user32.SetCursorPos(start_x, start_y))
                time.sleep(0.1)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.1)
                self.assertTrue(user32.SetCursorPos(end_x, end_y))
                time.sleep(0.1)
                user32.mouse_event(0x0004, 0, 0, 0, 0)

            tool = window.mapFromGlobal(first.mapToGlobal(QPoint(50, 60)))
            pin = window.mapFromGlobal(bar.pin_button.mapToGlobal(bar.pin_button.rect().center()))
            slider = window.mapFromGlobal(
                slider_widget.mapToGlobal(slider_widget.rect().center())
            )
            title_bar = QPoint(window.width() // 2, 20)
            edge_points = (
                QPoint(1, window.height() // 2),
                QPoint(window.width() - 1, window.height() // 2),
                QPoint(window.width() // 2, 1),
                QPoint(window.width() // 2, window.height() - 1),
                QPoint(1, 1),
                QPoint(window.width() - 1, window.height() - 1),
            )
            self.assertEqual(
                root_at(blank),
                int(window.winId()),
                f"before PIN OFF root={root_at(blank)}, main={int(window.winId())}, "
                f"background={background}, rect={window.frameGeometry()}, "
                f"pos={window.mapToGlobal(blank)}",
            )

            bar.pin_button.click()
            self.application.processEvents()
            self.assertFalse(bar.pin_button.isChecked())
            self.assertEqual(
                root_at(blank),
                underlay,
                f"PIN OFF hit-test root={root_at(blank)}, background={background}, "
                f"main={int(window.winId())}, bar={int(bar.winId())}, "
                f"backdrop={int(window._backdrop.winId())}, "
                f"main_flags={int(window.windowFlags())}, "
                f"bar_mask={bar.mask().boundingRect()}, point={window.mapToGlobal(blank)}, "
                f"hit={describe_handle(user32.WindowFromPoint(wintypes.POINT(160, 320)))}, "
                f"root={describe_handle(root_at(blank))}",
            )
            self.assertEqual(root_at(tool), underlay)
            self.assertEqual(root_at(pin), int(bar.winId()))
            self.assertEqual(root_at(slider), underlay)
            self.assertEqual(root_at(title_bar), underlay)
            for point in edge_points:
                with self.subTest(point=point):
                    self.assertEqual(root_at(point), underlay)

            if underlay != background:
                self.skipTest(
                    "Another application is underneath MiniFloat; skipping synthetic "
                    "mouse input to avoid interacting with it."
                )

            click_at(blank)
            for _ in range(30):
                self.application.processEvents()
                if os.path.exists(click_log):
                    break
                time.sleep(0.05)
            if not os.path.exists(click_log):
                click_at(blank)
                for _ in range(30):
                    self.application.processEvents()
                    if os.path.exists(click_log):
                        break
                    time.sleep(0.05)
            self.assertTrue(
                os.path.exists(click_log),
                "The click-through area did not deliver the click to the other process",
            )
            window_geometry = window.geometry()
            tool_geometry = first.geometry()
            opacity = window.windowOpacity()
            slider_value = slider_widget.value()
            tool_title = window.mapFromGlobal(
                first.mapToGlobal(QPoint(first.width() // 2, 10))
            )
            tool_minimize = window.mapFromGlobal(
                first.mapToGlobal(QPoint(first.width() - 30, 10))
            )
            tool_close = window.mapFromGlobal(
                first.mapToGlobal(QPoint(first.width() - 10, 10))
            )
            off_drag_attempts = (
                (title_bar, QPoint(title_bar.x() + 40, title_bar.y() + 30)),
                (
                    QPoint(1, window.height() // 2),
                    QPoint(35, window.height() // 2),
                ),
                (
                    tool_title,
                    QPoint(tool_title.x() + 35, tool_title.y() + 25),
                ),
                (
                    QPoint(
                        tool.x() + first.width() - 1,
                        tool.y() + first.height() - 1,
                    ),
                    QPoint(
                        tool.x() + first.width() + 30,
                        tool.y() + first.height() + 30,
                    ),
                ),
            )
            for point in (title_bar, tool_minimize, tool_close, slider):
                click_at(point)
            for start, end in off_drag_attempts:
                drag_at(start, end)
            self.application.processEvents()
            self.assertEqual(window.geometry(), window_geometry)
            self.assertEqual(first.geometry(), tool_geometry)
            self.assertTrue(first.isVisible())
            self.assertFalse(first.isMinimized())
            self.assertEqual(slider_widget.value(), slider_value)
            self.assertAlmostEqual(window.windowOpacity(), opacity, delta=0.005)

            window.showMinimized()
            self.application.processEvents()
            self.assertFalse(bar.isVisible())
            self.assertFalse(window._backdrop.isVisible())
            window.showNormal()
            self.application.processEvents()
            self.assertTrue(bar.isVisible())
            self.assertTrue(window._backdrop.isVisible())

            self.assertEqual(root_at(pin), int(bar.winId()))
            bar.pin_button.click()
            self.application.processEvents()
            self.assertTrue(bar.pin_button.isChecked())
            self.assertEqual(root_at(blank), int(window.winId()))
            self.assertEqual(root_at(tool), int(window.winId()))
            self.assertEqual(root_at(slider), int(bar.winId()))
            self.assertEqual(root_at(title_bar), int(window.winId()))
            for value in (25, 50, 75, 100):
                slider_widget.setValue(value)
                self.application.processEvents()
                self.assertAlmostEqual(window.windowOpacity(), value / 100, delta=0.005)
                self.assertAlmostEqual(bar.windowOpacity(), value / 100, delta=0.005)
                self.assertAlmostEqual(
                    window._backdrop.windowOpacity(), value / 100, delta=0.005
                )
                self.assertEqual(root_at(blank), int(window.winId()))
                self.assertEqual(root_at(tool), int(window.winId()))

        finally:
            if window is not None:
                window.close()
                self.application.processEvents()
            if background:
                user32.PostMessageW(background, 0x0010, 0, 0)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
            if process.stderr is not None:
                process.stderr.close()
            if os.path.exists(click_log):
                os.unlink(click_log)
