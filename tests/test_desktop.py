import unittest

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

    def test_reducing_desktop_preserves_geometry_and_enables_scrolling(self) -> None:
        first, second = self.desktop.subWindowList()
        second.move(260, 100)
        self.application.processEvents()
        positions = [subwindow.geometry() for subwindow in (first, second)]

        self.window.resize(280, 180)
        self.application.processEvents()
        self.assertEqual([subwindow.geometry() for subwindow in (first, second)], positions)
        self.assertGreater(self.desktop.horizontalScrollBar().maximum(), 0)
        self.assertGreater(self.desktop.verticalScrollBar().maximum(), 0)
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_partially_outside_window_can_be_reached_by_scrolling(self) -> None:
        first, _ = self.desktop.subWindowList()
        first.move(-70, -50)
        self.application.processEvents()
        self.assertLess(self.desktop.horizontalScrollBar().minimum(), 0)
        self.assertLess(self.desktop.verticalScrollBar().minimum(), 0)

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


if __name__ == "__main__":
    unittest.main()
