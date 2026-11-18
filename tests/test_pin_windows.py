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
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.PostMessageW.restype = wintypes.BOOL

        title = f"MiniFloat test {uuid.uuid4()}"
        code = (
            "import sys; from PySide6.QtCore import QTimer; "
            "from PySide6.QtWidgets import QApplication, QWidget; "
            "app=QApplication([]); w=QWidget(); w.setWindowTitle(sys.argv[1]); "
            "w.setGeometry(30,30,1100,700); w.show(); "
            "QTimer.singleShot(30000, app.quit); sys.exit(app.exec())"
        )
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "windows"
        process = subprocess.Popen(
            [sys.executable, "-c", code, title],
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
            window.show()
            self.application.processEvents()
            desktop = window.findChild(Desktop)
            bar = window._control_bar
            self.assertIsNotNone(desktop)
            self.assertIsNotNone(bar)
            first = desktop.subWindowList()[0]

            def root_at(point: QPoint) -> int:
                rect = wintypes.RECT()
                self.assertTrue(user32.GetWindowRect(int(window.winId()), ctypes.byref(rect)))
                scale = window.devicePixelRatioF()
                point = wintypes.POINT(
                    round(rect.left + point.x() * scale),
                    round(rect.top + point.y() * scale),
                )
                return user32.GetAncestor(user32.WindowFromPoint(point), 2)

            blank = QPoint(10, window.height() - 60)
            tool = window.mapFromGlobal(first.mapToGlobal(QPoint(50, 60)))
            pin = window.mapFromGlobal(bar.pin_button.mapToGlobal(bar.pin_button.rect().center()))
            self.assertEqual(root_at(blank), int(window.winId()))

            bar.pin_button.click()
            self.application.processEvents()
            self.assertFalse(bar.pin_button.isChecked())
            self.assertEqual(root_at(blank), background)
            self.assertEqual(root_at(tool), int(window.winId()))
            self.assertEqual(root_at(pin), int(bar.winId()))

            slider = bar.findChild(QSlider, "opacitySlider")
            for value in (25, 50, 75, 100):
                slider.setValue(value)
                self.application.processEvents()
                self.assertAlmostEqual(window.windowOpacity(), value / 100, delta=0.005)
                self.assertAlmostEqual(bar.windowOpacity(), value / 100, delta=0.005)
                self.assertAlmostEqual(window._backdrop.windowOpacity(), value / 100, delta=0.005)
                self.assertEqual(root_at(blank), background)
                self.assertEqual(root_at(tool), int(window.winId()))

            window.showMinimized()
            self.application.processEvents()
            self.assertFalse(bar.isVisible())
            self.assertFalse(window._backdrop.isVisible())
            window.showNormal()
            self.application.processEvents()
            self.assertTrue(bar.isVisible())
            self.assertTrue(window._backdrop.isVisible())

            bar.pin_button.click()
            self.application.processEvents()
            self.assertTrue(bar.pin_button.isChecked())
            self.assertEqual(root_at(blank), int(window.winId()))
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
