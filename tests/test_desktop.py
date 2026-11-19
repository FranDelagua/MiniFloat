import unittest
from unittest.mock import call, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMdiArea, QSlider, QToolButton, QWidget

from app.windows import (
    ExternalWindow,
    ExternalWindowState,
    ExternalWindowTransitionError,
    WindowCandidate,
    WindowPlacement,
)
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

    @staticmethod
    def _external(handle: int = 101) -> ExternalWindow:
        return ExternalWindow(
            instance_id=f"instance-{handle}",
            handle=handle,
            title="Test Window",
            process_id=handle + 1,
            process_name="app.exe",
            class_name="Window",
            original_parent=0,
            original_owner=0,
            original_style=0,
            original_extended_style=0,
            original_geometry=(10, 20, 410, 320),
            original_placement=WindowPlacement(
                0, 1, (-1, -1), (-1, -1), (10, 20, 410, 320)
            ),
            original_enabled=True,
            original_visible=True,
            original_was_minimized=False,
            original_was_maximized=False,
        )

    def test_external_workspace_is_not_mdi(self) -> None:
        self.assertIsInstance(self.desktop, QWidget)
        self.assertNotIsInstance(self.desktop, QMdiArea)

    def test_control_surfaces_follow_main_window_topmost_state(self) -> None:
        bar = self.window._control_bar
        overlay = bar._pin_overlay

        self.assertTrue(bar.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

        self.window.set_always_on_top(False)
        self.assertFalse(bar.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertFalse(overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

        self.window.set_always_on_top(True)
        self.assertTrue(bar.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_external_host_fills_and_tracks_workspace(self) -> None:
        candidate = WindowCandidate(101, "Test Window", 102, "app.exe", "Window")
        external = self._external()
        with (
            patch("ui.desktop.ExternalWindow.capture", return_value=external),
            patch.object(ExternalWindow, "adopt") as adopt,
            patch.object(ExternalWindow, "set_geometry") as set_geometry,
            patch.object(ExternalWindow, "is_alive", return_value=True),
            patch.object(ExternalWindow, "set_interactive"),
            patch.object(ExternalWindow, "release", return_value=True) as release,
            patch(
                "ui.desktop.native_client_geometry",
                side_effect=lambda _handle: (
                    0, 0, round(self.desktop.width() * 1.5),
                    round(self.desktop.height() * 1.5),
                ),
            ),
        ):
            instance_id = self.desktop.add_external_window(candidate)
            host = self.desktop._external_windows[instance_id]
            self.application.processEvents()

            self.assertEqual(host.geometry(), self.desktop.rect())
            self.assertTrue(host.testAttribute(Qt.WidgetAttribute.WA_NativeWindow))
            adopt.assert_called_once_with(
                host.native_parent_handle,
                (0, 0, round(host.width() * 1.5), round(host.height() * 1.5)),
            )
            self.assertIn(
                call((0, 0, round(self.desktop.width() * 1.5),
                      round(self.desktop.height() * 1.5))),
                set_geometry.call_args_list,
            )

            self.window.resize(620, 420)
            self.application.processEvents()
            self.assertEqual(host.geometry(), self.desktop.rect())
            self.assertIn(
                call((0, 0, round(self.desktop.width() * 1.5),
                      round(self.desktop.height() * 1.5))),
                set_geometry.call_args_list,
            )
            self.assertTrue(self.desktop.release_external_window(instance_id))
            release.assert_called_once()
            self.assertIsNone(host.external)

        self.assertFalse(self.desktop.managed_handles)

    def test_release_failure_keeps_recovery_window_accessible(self) -> None:
        candidate = WindowCandidate(101, "Recoverable", 102, "app.exe", "Window")
        external = self._external()
        external.state = ExternalWindowState.RECOVERY_REQUIRED
        external.adopted_parent = 500
        external.adopted_geometry = (0, 0, 400, 300)

        with (
            patch("ui.desktop.ExternalWindow.capture", return_value=external),
            patch.object(ExternalWindow, "adopt"),
            patch("ui.desktop.native_client_geometry", return_value=(0, 0, 400, 300)),
            patch.object(ExternalWindow, "is_alive", return_value=True),
            patch.object(
                ExternalWindow,
                "release",
                side_effect=ExternalWindowTransitionError("restore failed"),
            ),
            patch("ui.window.QMessageBox.critical"),
        ):
            instance_id = self.desktop.add_external_window(candidate)
            host = self.desktop._external_windows[instance_id]

            self.assertFalse(self.desktop.release_external_window(instance_id))
            self.application.processEvents()

            self.assertIn(instance_id, self.desktop._external_windows)
            self.assertIs(self.desktop._external_windows[instance_id], host)
            self.assertTrue(host.isVisible())
            self.assertIsNotNone(host.external)

    def test_closed_external_window_is_removed_without_restoration(self) -> None:
        candidate = WindowCandidate(101, "Closed", 102, "app.exe", "Window")
        external = self._external()
        with (
            patch("ui.desktop.ExternalWindow.capture", return_value=external),
            patch.object(ExternalWindow, "adopt"),
            patch("ui.desktop.native_client_geometry", return_value=(0, 0, 400, 300)),
            patch.object(ExternalWindow, "is_alive", side_effect=(True, False)),
            patch.object(ExternalWindow, "release") as release,
        ):
            instance_id = self.desktop.add_external_window(candidate)
            host = self.desktop._external_windows[instance_id]
            self.desktop._remove_closed_windows()

            self.assertNotIn(instance_id, self.desktop._external_windows)
            self.assertFalse(self.desktop.managed_handles)
            self.assertIsNone(host.external)
            release.assert_not_called()

    def test_opacity_control_updates_all_surfaces(self) -> None:
        slider = self.window.findChild(QSlider, "opacitySlider")
        self.assertIsNotNone(slider)
        for value in (25, 50, 75, 100):
            with self.subTest(value=value):
                slider.setValue(value)
                self.application.processEvents()
                opacity = value / 100
                self.assertAlmostEqual(self.window.windowOpacity(), opacity, delta=0.005)
                self.assertAlmostEqual(
                    self.window._control_bar.windowOpacity(), opacity, delta=0.005
                )
                self.assertAlmostEqual(
                    self.window._backdrop.windowOpacity(), opacity, delta=0.005
                )

    def test_pin_off_keeps_control_bar_visible_and_only_pin_interactive(self) -> None:
        bar = self.window._control_bar
        slider = bar.findChild(QSlider, "opacitySlider")
        title_buttons = self.window._title_bar.findChildren(QToolButton)
        with patch("ui.window.place_directly_below"):
            bar.pin_button.click()
            self.application.processEvents()

            self.assertFalse(bar.pin_button.isChecked())
            self.assertTrue(bar.isVisible())
            self.assertTrue(bar._pin_only_mode)
            self.assertTrue(bar.mask().isEmpty())
            self.assertTrue(bar.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            self.assertTrue(bar._pin_slot.isVisible())
            self.assertTrue(bar._pin_overlay.isVisible())
            self.assertTrue(slider.isEnabled())
            self.assertTrue(all(not button.isEnabled() for button in title_buttons))
            self.assertTrue(
                self.window.windowFlags() & Qt.WindowType.WindowTransparentForInput
            )

            previous_opacity = self.window.windowOpacity()
            slider.setValue(50)
            self.window._set_opacity(25)
            self.assertAlmostEqual(
                self.window.windowOpacity(), previous_opacity, delta=0.005
            )

            bar._pin_overlay.click()
            self.application.processEvents()
            self.assertTrue(bar.pin_button.isChecked())
            self.assertFalse(bar._pin_only_mode)
            self.assertFalse(bar.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            self.assertFalse(bar._pin_overlay.isVisible())
            self.assertTrue(all(button.isEnabled() for button in title_buttons))

    def test_surfaces_hide_and_restore_when_minimized(self) -> None:
        bar = self.window._control_bar
        with patch("ui.window.place_directly_below"):
            bar.pin_button.click()
            self.application.processEvents()
            self.assertTrue(bar.isVisible())
            self.assertTrue(bar._pin_overlay.isVisible())

            self.window.showMinimized()
            self.application.processEvents()
            self.assertFalse(bar.isVisible())
            self.assertFalse(bar._pin_overlay.isVisible())
            self.assertFalse(self.window._backdrop.isVisible())

            self.window.showNormal()
            self.application.processEvents()
            self.assertTrue(bar.isVisible())
            self.assertTrue(bar._pin_overlay.isVisible())
            self.assertTrue(self.window._backdrop.isVisible())

    def test_pin_failure_restores_interactive_mode(self) -> None:
        bar = self.window._control_bar
        with (
            patch("ui.window.place_directly_below", side_effect=OSError("test failure")),
            patch("ui.window.QMessageBox.critical") as report,
        ):
            bar.pin_button.click()
        self.assertTrue(bar.pin_button.isChecked())
        self.assertFalse(self.window._backdrop.isVisible())
        self.assertFalse(bar._pin_only_mode)
        report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
