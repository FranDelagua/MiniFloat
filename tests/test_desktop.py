import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QSlider

from ui.desktop import Desktop
from ui.window import MainWindow


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self) -> None:
        self.window = MainWindow()
        self.window.show()
        self.application.processEvents()
        self.desktop = self.window.findChild(Desktop)
        self.assertIsNotNone(self.desktop)

    def tearDown(self) -> None:
        self.window.close()
        self.application.processEvents()

    def test_subwindows_are_independent(self) -> None:
        first, second = self.desktop.subWindowList()
        self.assertEqual({first.windowTitle(), second.windowTitle()}, {"Test Window", "Test 2"})

        original_second = second.geometry()
        first.setGeometry(40, 35, 200, 150)
        self.desktop.setActiveSubWindow(first)
        self.application.processEvents()
        self.assertEqual(second.geometry(), original_second)
        self.assertIs(self.desktop.activeSubWindow(), first)

        first.close()
        self.application.processEvents()
        self.assertEqual(self.desktop.subWindowList(), [second])
        self.assertTrue(second.isVisible())
        self.assertTrue(self.window.isVisible())

    def test_reducing_desktop_keeps_windows_accessible(self) -> None:
        first, second = self.desktop.subWindowList()
        second.move(260, 100)
        self.window.resize(280, 180)
        self.application.processEvents()
        viewport = self.desktop.viewport().rect()
        for subwindow in (first, second):
            self.assertTrue(viewport.contains(subwindow.geometry().topLeft()))
            self.assertTrue(viewport.contains(subwindow.geometry().topRight()))
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_subwindow_is_constrained_at_all_edges(self) -> None:
        first, _ = self.desktop.subWindowList()
        for x, y in ((-1000, 20), (1000, 20), (20, -1000), (20, 1000), (-1000, -1000), (1000, 1000)):
            with self.subTest(x=x, y=y):
                first.move(x, y)
                self.application.processEvents()
                viewport = self.desktop.viewport().rect()
                self.assertTrue(viewport.contains(first.geometry()))

        first.resize(2000, 2000)
        self.application.processEvents()
        self.assertTrue(self.desktop.viewport().rect().contains(first.geometry()))

    def test_slider_controls_global_opacity(self) -> None:
        slider = self.window.findChild(QSlider, "opacitySlider")
        label = self.window.findChild(QLabel, "opacityValue")
        self.assertIsNotNone(slider)
        self.assertIsNotNone(label)
        self.assertEqual((slider.minimum(), slider.maximum()), (25, 100))
        self.assertEqual(slider.value(), 92)

        for value in (25, 50, 75, 100):
            with self.subTest(value=value):
                slider.setValue(value)
                self.application.processEvents()
                self.assertAlmostEqual(self.window.windowOpacity(), value / 100, delta=0.005)
                self.assertEqual(label.text(), f"{value}%")

    def test_pin_surfaces_follow_window_and_restore_after_minimize(self) -> None:
        bar = self.window._control_bar
        backdrop = self.window._backdrop
        with patch("ui.window.place_directly_below"):
            bar.pin_button.click()
            self.application.processEvents()
            self.assertFalse(bar.pin_button.isChecked())
            self.assertTrue(backdrop.isVisible())
            self.assertTrue(backdrop.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            self.assertTrue(bar.isWindow())

            self.window.move(120, 110)
            self.window.resize(480, 320)
            self.application.processEvents()
            self.assertEqual(backdrop.geometry(), self.window.geometry())
            self.assertEqual(
                bar.pos(), self.window.mapToGlobal(self.window._control_bar_rect().topLeft())
            )

            self.window.showMinimized()
            self.application.processEvents()
            self.assertFalse(bar.isVisible())
            self.assertFalse(backdrop.isVisible())
            self.window.showNormal()
            self.application.processEvents()
            self.assertTrue(bar.isVisible())
            self.assertTrue(backdrop.isVisible())

            bar.pin_button.click()
            self.application.processEvents()
            self.assertTrue(bar.pin_button.isChecked())
            self.assertFalse(backdrop.isVisible())

    def test_pin_failure_restores_interactive_mode(self) -> None:
        bar = self.window._control_bar
        with (
            patch("ui.window.place_directly_below", side_effect=OSError("test failure")),
            patch("ui.window.QMessageBox.critical") as report,
        ):
            bar.pin_button.click()
        self.assertTrue(bar.pin_button.isChecked())
        self.assertFalse(self.window._backdrop.isVisible())
        report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
