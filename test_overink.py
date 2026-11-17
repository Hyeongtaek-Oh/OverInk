import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

import overink


class ConfigTests(unittest.TestCase):
    def test_invalid_shapes_fall_back_to_defaults(self):
        for value in ([], None, 123, "settings", {"custom": None},
                      {"custom": 123}, {"custom": "red"},
                      {"custom": [123, None, {}, [], "invalid"]}):
            with self.subTest(value=value), patch.object(
                    overink.Path, "read_text", return_value=json.dumps(value)):
                cfg = overink.load_config()
                self.assertEqual(cfg["custom"], [])
                self.assertEqual(cfg["keys"], overink.DEFAULT_KEYS)

    def test_valid_settings_survive_invalid_entries(self):
        value = {"custom": [None, "#123456", "#123456", "#ff3b30"],
                 "keys": {"undo": "Alt+Z", "redo": 123}}
        with patch.object(overink.Path, "read_text", return_value=json.dumps(value)):
            cfg = overink.load_config()
        self.assertEqual(cfg["custom"], ["#123456"])
        self.assertEqual(cfg["keys"]["undo"], "Alt+Z")
        self.assertEqual(cfg["keys"]["redo"], overink.DEFAULT_KEYS["redo"])


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(overink.Path, "read_text", return_value="{}"):
            self.ov = overink.Overlay()
        self.stroke = overink.Stroke(overink.PEN, QColor("red"), 4,
                                      [QPointF(50, 50), QPointF(100, 50)])
        self.ov.strokes = [self.stroke]
        self.ov.undo_stack = [("add", self.stroke)]
        self.ov._erase_at(QPointF(50, 50))

    def tearDown(self):
        self.ov.close()

    def test_undo_mid_erase_then_redo_and_release(self):
        self.ov.undo()
        self.assertEqual(self.ov.strokes, [self.stroke])
        self.assertEqual(self.ov.erased_now, [])
        self.ov.mouseReleaseEvent(None)
        self.assertEqual(len(self.ov.undo_stack), 1)
        self.ov.redo()
        self.assertEqual(self.ov.strokes, [])
        self.ov.undo()
        self.ov.undo()
        self.assertEqual(self.ov.strokes, [])

    def test_mode_change_commits_pending_erase(self):
        self.ov.set_drawing_mode(False)
        self.assertEqual(self.ov.erased_now, [])
        self.ov.undo()
        self.assertEqual(self.ov.strokes, [self.stroke])

    def test_clear_during_erase_keeps_history_valid(self):
        self.ov.clear()
        self.ov.undo()
        self.assertEqual(self.ov.strokes, [self.stroke])

    def test_overlapping_erase_buttons_preserve_history(self):
        left, right = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton
        for first, second in ((left, right), (right, left)):
            with self.subTest(first=first):
                a = self.stroke
                b = overink.Stroke(overink.PEN, QColor("red"), 4,
                                   [QPointF(200, 50), QPointF(250, 50)])
                self.ov.strokes = [a, b]
                self.ov.undo_stack = [("add", a), ("add", b)]
                self.ov.redo_stack = []
                self.ov.erased_now = []
                self.ov.tool = overink.ERASER
                for button, pos, buttons in (
                        (first, QPointF(50, 50), first),
                        (second, QPointF(200, 50), left | right)):
                    event = Mock()
                    event.button.return_value = button
                    event.buttons.return_value = buttons
                    event.position.return_value = pos
                    self.ov.mousePressEvent(event)
                self.ov.mouseReleaseEvent(None)
                self.ov.mouseReleaseEvent(None)
                self.assertEqual(self.ov.strokes, [])
                self.ov.undo()
                self.assertEqual(self.ov.strokes, [b])
                self.ov.undo()
                self.assertEqual(self.ov.strokes, [a, b])
                self.ov.redo()
                self.ov.redo()
                self.assertEqual(self.ov.strokes, [])
                for _ in range(4):
                    self.ov.undo()
                self.assertEqual(self.ov.strokes, [])


if __name__ == "__main__":
    unittest.main()
