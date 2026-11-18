import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QSlider, QToolButton

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

        for geometry in (
            (-1000, -1000, 2000, 2000),
            (1000, -1000, 2000, 2000),
            (-1000, 1000, 2000, 2000),
            (1000, 1000, 2000, 2000),
            (0, 0, 2000, 100),
            (0, 0, 100, 2000),
        ):
            with self.subTest(geometry=geometry):
                first.setGeometry(*geometry)
                self.application.processEvents()
                self.assertTrue(self.desktop.viewport().rect().contains(first.geometry()))

    def test_subwindow_state_survives_reducing_and_growing_desktop(self) -> None:
        first, _ = self.desktop.subWindowList()
        first.setGeometry(80, 45, 210, 130)
        self.application.processEvents()
        content = first.widget().text()

        self.window.resize(280, 180)
        self.application.processEvents()
        self.assertLessEqual(first.width(), self.desktop.viewport().width())
        self.assertLessEqual(first.height(), self.desktop.viewport().height())
        self.assertTrue(self.desktop.viewport().rect().contains(first.geometry()))

        first.showMinimized()
        self.application.processEvents()
        first.showNormal()
        self.application.processEvents()
        self.assertTrue(self.desktop.viewport().rect().contains(first.geometry()))
        self.assertIn(first, self.desktop.subWindowList())
        self.assertEqual(first.widget().text(), content)

        self.window.resize(600, 500)
        self.application.processEvents()
        self.assertIn(first, self.desktop.subWindowList())
        self.assertEqual(first.widget().text(), content)
        self.assertTrue(first.isVisible())

    def test_user_resize_below_minimum_keeps_controls_accessible(self) -> None:
        first, _ = self.desktop.subWindowList()
        first.resize(20, 10)
        self.application.processEvents()
        self.assertGreaterEqual(first.width(), 120)
        self.assertGreaterEqual(first.height(), 70)
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

    @patch("ui.window.place_directly_below")
    def test_pin_modes_gate_every_interactive_control(self, place_directly_below) -> None:
        bar = self.window._control_bar
        slider = bar.findChild(QSlider, "opacitySlider")
        opacity_label = bar.findChild(QLabel, "opacityValue")
        buttons = self.window._title_bar.findChildren(QToolButton)
        first, _ = self.desktop.subWindowList()

        self.assertFalse(
            self.window.windowFlags() & Qt.WindowType.WindowTransparentForInput
        )
        self.assertTrue(slider.isEnabled())
        self.assertEqual(opacity_label.text(), "92%")
        self.assertTrue(all(button.isEnabled() for button in buttons))
        self.assertFalse(
            first.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        )

        self.window.move(120, 110)
        self.window.resize(520, 360)
        first.move(30, 25)
        first.resize(200, 145)
        self.application.processEvents()
        self.assertEqual(self.window.pos().x(), 120)
        self.assertEqual(self.window.pos().y(), 110)
        self.assertEqual(first.pos().x(), 30)
        self.assertEqual(first.pos().y(), 25)
        self.assertEqual(first.size().width(), 200)
        self.assertEqual(first.size().height(), 145)
        first.showMinimized()
        self.application.processEvents()
        self.assertTrue(first.isMinimized())
        first.showNormal()
        self.application.processEvents()
        second = next(
            subwindow
            for subwindow in self.desktop.subWindowList()
            if subwindow is not first
        )
        second.close()
        self.application.processEvents()
        self.assertIn(first, self.desktop.subWindowList())
        self.assertNotIn(second, self.desktop.subWindowList())

        slider.setValue(75)
        self.assertAlmostEqual(self.window.windowOpacity(), 0.75, delta=0.005)
        self.assertEqual(opacity_label.text(), "75%")
        geometry = self.window.geometry()
        tool_geometry = first.geometry()

        bar.pin_button.click()
        self.application.processEvents()

        self.assertFalse(bar.pin_button.isChecked())
        self.assertTrue(
            self.window.windowFlags() & Qt.WindowType.WindowTransparentForInput
        )
        self.assertFalse(slider.isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in buttons))
        self.assertTrue(
            first.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        )
        self.assertTrue(bar.mask().contains(bar.pin_button.geometry().center()))
        self.assertFalse(bar.mask().contains(slider.geometry().center()))

        main_position = QPoint(1, self.window.height() // 2)
        main_global = QPointF(self.window.mapToGlobal(main_position))
        self.window.mousePressEvent(
            QMouseEvent(
                QMouseEvent.Type.MouseButtonPress,
                QPointF(main_position),
                QPointF(main_position),
                main_global,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        title_position = QPoint(20, 10)
        title_global = QPointF(self.window._title_bar.mapToGlobal(title_position))
        self.window._title_bar.mousePressEvent(
            QMouseEvent(
                QMouseEvent.Type.MouseButtonPress,
                QPointF(title_position),
                QPointF(title_position),
                title_global,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        slider.setValue(50)
        self.window._set_opacity(25)
        self.assertAlmostEqual(self.window.windowOpacity(), 0.75, delta=0.005)
        self.assertEqual(self.window.geometry(), geometry)
        self.assertEqual(first.geometry(), tool_geometry)
        self.assertTrue(first.isVisible())
        self.assertFalse(first.isMinimized())

        bar.pin_button.click()
        self.application.processEvents()

        self.assertTrue(bar.pin_button.isChecked())
        self.assertFalse(
            self.window.windowFlags() & Qt.WindowType.WindowTransparentForInput
        )
        self.assertTrue(slider.isEnabled())
        self.assertEqual(slider.value(), 75)
        self.assertTrue(all(button.isEnabled() for button in buttons))
        self.assertFalse(
            first.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        )
        self.assertTrue(bar.mask().isEmpty())


if __name__ == "__main__":
    unittest.main()
