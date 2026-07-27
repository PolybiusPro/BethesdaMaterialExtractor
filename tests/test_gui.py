from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from bme.gui import (
    App,
    DATABASE_EXTENSIONS,
    _accepted_files_text,
    _file_pattern,
)


class GuiDescriptionTests(unittest.TestCase):
    def test_database_description_and_pattern(self) -> None:
        self.assertEqual(
            _accepted_files_text(DATABASE_EXTENSIONS),
            "Accepted files: .ba2",
        )
        self.assertEqual(_file_pattern(DATABASE_EXTENSIONS), "*.ba2")


class WindowDragTests(unittest.TestCase):
    def test_windows_drag_starts_native_window_move(self) -> None:
        app = SimpleNamespace(
            _is_maximized=False,
            _start_windows_move=mock.Mock(),
        )

        with mock.patch("bme.gui.os.name", "nt"):
            App._start_move(app, mock.Mock())

        app._start_windows_move.assert_called_once_with()

    def test_windows_mouse_motion_does_not_update_tk_geometry(self) -> None:
        app = SimpleNamespace(
            _is_maximized=False,
            geometry=mock.Mock(),
        )

        with mock.patch("bme.gui.os.name", "nt"):
            App._move_window(app, mock.Mock())

        app.geometry.assert_not_called()

if __name__ == "__main__":
    unittest.main()
