#!/usr/bin/env python3
"""OverInk — 화면 위에 그리는 발표/화면공유용 주석 오버레이 (PyQt6, X11 · Windows).

모드
  대기 모드    : 백그라운드 상주. 화면엔 아무것도 없고 트레이 아이콘만 (실행 직후 기본)
  그리기 모드  : 오버레이가 마우스 입력을 받아 그림을 그림
  투과 모드    : 그림은 남기고 클릭/키보드는 아래 앱으로 그대로 전달

설치: Ubuntu ./install.sh [--autostart|--uninstall] · Windows install.bat [--autostart|--uninstall]
실행: ./run.sh (대기 모드로 시작) · ./run.sh --show (바로 그리기 모드로 시작)
      Windows run.bat (바로 그리기 모드) · run.bat --debug (콘솔 창에 오류 표시)

단축키는 모두 바꿀 수 있음: 툴바 ⚙ 또는 트레이 메뉴 → 단축키 설정 (~/.config/overink.json 에 저장)

기본 전역 단축키 (pynput 설치 시, 어느 모드에서든 동작)
  Ctrl+Alt+P  대기 → 그리기 / 그리기 → 대기(그림 지움) / 투과 → 그리기
  Ctrl+Alt+C  전체 지우기
  Ctrl+Alt+H  그림 숨기기/보이기
  Ctrl+Alt+Q  종료

기본 그리기 모드 단축키
  P 펜 · H 형광펜 · A 화살표 · R 사각형 · O 원 · T 텍스트 · E 지우개
  1~6 기본 색 · 7 최근 사용자 색 · I 화면에서 색 추출(스포이드) · [ / ] 굵기 · Ctrl+Z 실행취소 · Ctrl+Shift+Z 다시실행
  C 전체 지우기 · Esc 투과 모드로 전환
  (고정) 휠 굵기 · Shift 누른 채 펜 = 직선 · 우클릭 드래그 지우개
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field

from PyQt6.QtCore import (
    QEvent, QKeyCombination, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QAbstractTextDocumentLayout, QAction, QColor, QCursor, QFont, QGuiApplication, QIcon,
    QKeySequence, QPainter, QPainterPath, QPainterPathStroker, QPalette, QPen, QPixmap, QRegion,
    QTextDocument, QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QColorDialog, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QHBoxLayout, QKeySequenceEdit, QLabel, QMenu, QPushButton, QScrollArea,
    QSystemTrayIcon, QTextEdit, QToolTip, QToolButton, QVBoxLayout, QWidget,
)

PEN, HIGHLIGHT, ARROW, RECT, ELLIPSE, TEXT, ERASER = (
    "pen", "highlight", "arrow", "rect", "ellipse", "text", "eraser")
# 툴팁의 {id} 자리에는 현재 설정된 단축키가 "  [키]" 형태로 들어감
TOOLS = [
    (PEN, "✎", "펜 — 자유롭게 그리기{pen}\nShift 누른 채 그리면 직선"),
    (HIGHLIGHT, "▮", "형광펜 — 반투명 굵은 선으로 강조{highlight}"),
    (ARROW, "➚", "화살표 — 드래그한 방향으로 화살표{arrow}"),
    (RECT, "▭", "사각형 — 드래그해서 영역 표시{rect}"),
    (ELLIPSE, "◯", "원 — 드래그해서 타원 그리기{ellipse}"),
    (TEXT, "T", "텍스트 — 클릭한 곳에 글자 입력{text}\n"
                "한글·특수문자·이모지, 붙여넣기(Ctrl+V) 가능 · Enter 줄바꿈\n"
                "Esc 또는 바깥 클릭으로 완료 · 글자 크기는 굵기(휠·[ ])로 조절"),
    (ERASER, "⌫", "지우개 — 닿은 획을 통째로 지움{eraser}\n우클릭 드래그로도 지울 수 있음"),
]
COLORS = ["#ff3b30", "#ffcc00", "#34c759", "#0a84ff", "#ffffff", "#000000"]
COLOR_NAMES = ["빨강", "노랑", "초록", "파랑", "흰색", "검정"]

# 단축키: (id, 설명, 기본값, 전역 여부). 전역 = 다른 앱을 쓰는 중에도 동작 (pynput)
KEY_ACTIONS = [
    ("toggle", "그리기 시작 / 백그라운드로 숨기기", "Ctrl+Alt+P", True),
    ("clear_any", "전체 지우기", "Ctrl+Alt+C", True),
    ("visible", "그림 숨기기 / 보이기", "Ctrl+Alt+H", True),
    ("quit", "OverInk 종료", "Ctrl+Alt+Q", True),
    (PEN, "펜", "P", False),
    (HIGHLIGHT, "형광펜", "H", False),
    (ARROW, "화살표", "A", False),
    (RECT, "사각형", "R", False),
    (ELLIPSE, "원", "O", False),
    (TEXT, "텍스트", "T", False),
    (ERASER, "지우개", "E", False),
    *[(f"color{i + 1}", f"색: {n}", str(i + 1), False) for i, n in enumerate(COLOR_NAMES)],
    ("color7", "색: 최근 사용자 색", "7", False),
    ("eyedropper", "스포이드 (화면에서 색 추출)", "I", False),
    ("thinner", "펜촉 가늘게", "[", False),
    ("thicker", "펜촉 굵게", "]", False),
    ("undo", "실행 취소", "Ctrl+Z", False),
    ("redo", "다시 실행", "Ctrl+Shift+Z", False),
    ("clear", "전체 지우기", "C", False),
    ("passthrough", "투과 모드로 전환", "Esc", False),
]
GLOBAL_KEYS = {a for a, _, _, g in KEY_ACTIONS if g}
DEFAULT_KEYS = {a: d for a, _, d, _ in KEY_ACTIONS}
KEY_LABELS = {a: l for a, l, _, _ in KEY_ACTIONS}
_PORTABLE = QKeySequence.SequenceFormat.PortableText


def norm_seq(s: str) -> str:
    """키 조합 문자열을 저장용 표준 형태로 ('ctrl+z' → 'Ctrl+Z')."""
    return QKeySequence(s).toString(_PORTABLE) if s else ""


def key_text(s: str) -> str:
    """화면 표시용 키 이름."""
    return QKeySequence(s).toString(QKeySequence.SequenceFormat.NativeText) if s else ""


_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                  Qt.Key.Key_AltGr, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R, Qt.Key.Key_unknown}


def event_seq(e) -> str:
    """키 입력 이벤트 → 설정과 같은 형태의 키 조합 문자열. 수식키만 눌렸으면 ''."""
    try:
        k = Qt.Key(e.key())
    except ValueError:
        return ""
    if k in _MODIFIER_KEYS:
        return ""
    mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier  # 숫자패드도 같은 키로
    return QKeySequence(QKeyCombination(mods, k)).toString(_PORTABLE)
N_CUSTOM = 16  # 팔레트의 '최근 사용자 색' 칸 수 (QColorDialog 사용자 색 칸 = 16)
MIN_W, MAX_W = 1, 60
CONFIG_PATH = Path.home() / ".config" / "overink.json"


def text_px(width: float) -> int:
    """펜 굵기 → 글자 크기(px). 기본 굵기 4 → 24px."""
    return round(12 + width * 3)


def text_font(width: float) -> QFont:
    f = QFont(QGuiApplication.font())
    f.setPixelSize(text_px(width))
    f.setWeight(QFont.Weight.Bold)
    return f


def make_text_doc(text: str, width: float) -> QTextDocument:
    """입력 상자(QTextEdit)와 같은 방식으로 배치한 문서 → 완료 후에도 글자 위치가 그대로."""
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(text_font(width))
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.NoWrap)
    doc.setDefaultTextOption(opt)
    doc.setPlainText(text)
    return doc


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    custom = [QColor(c).name() for c in cfg.get("custom", []) if QColor.isValidColorName(c)]
    cfg["custom"] = [c for c in dict.fromkeys(custom) if c not in COLORS][:N_CUSTOM]
    cfg.pop("slots", None)  # 이전 버전 형식 정리
    keys = dict(DEFAULT_KEYS)
    saved = cfg.get("keys")
    if isinstance(saved, dict):
        for a, s in saved.items():
            if a in keys and isinstance(s, str):
                keys[a] = norm_seq(s)
    cfg["keys"] = keys
    return cfg


def save_config(cfg: dict):
    out = dict(cfg)  # 단축키는 기본값과 다른 것만 저장 (기본값이 바뀌면 따라가도록)
    out["keys"] = {a: s for a, s in cfg.get("keys", {}).items() if s != DEFAULT_KEYS.get(a)}
    if not out["keys"]:
        del out["keys"]
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as ex:
        print(f"[OverInk] 설정 저장 실패: {ex}", file=sys.stderr)


@dataclass
class Stroke:
    tool: str
    color: QColor
    width: float
    points: list[QPointF] = field(default_factory=list)
    text: str = ""
    _path: QPainterPath | None = None
    _hit: QPainterPath | None = None
    _doc: QTextDocument | None = None

    def doc(self) -> QTextDocument:
        if self._doc is None:
            self._doc = make_text_doc(self.text, self.width)
        return self._doc

    # ---- geometry -------------------------------------------------------
    def path(self) -> QPainterPath:
        if self._path is not None:
            return self._path
        p = QPainterPath()
        pts = self.points
        if not pts:
            return p
        a, b = pts[0], pts[-1]
        if self.tool in (PEN, HIGHLIGHT):
            p.moveTo(a)
            if len(pts) == 1:
                p.lineTo(a + QPointF(0.01, 0))
            elif len(pts) == 2:
                p.lineTo(b)
            else:  # 중점 기반 2차 베지어로 부드럽게
                for i in range(1, len(pts) - 1):
                    mid = (pts[i] + pts[i + 1]) / 2
                    p.quadTo(pts[i], mid)
                p.lineTo(b)
        elif self.tool == ARROW:
            p.moveTo(a)
            p.lineTo(b)
            ang = math.atan2(b.y() - a.y(), b.x() - a.x())
            head = max(14.0, self.width * 4)
            for d in (math.radians(150), math.radians(-150)):
                p.moveTo(b)
                p.lineTo(b + QPointF(math.cos(ang + d) * head, math.sin(ang + d) * head))
        elif self.tool == RECT:
            p.addRect(QRectF(a, b).normalized())
        elif self.tool == ELLIPSE:
            p.addEllipse(QRectF(a, b).normalized())
        elif self.tool == TEXT:  # 글자가 차지하는 사각형 (지우개 판정용)
            p.addRect(QRectF(a, self.doc().size()))
        self._path = p
        return p

    def invalidate(self):
        self._path = None
        self._hit = None

    def paint_bounds(self) -> QRect:
        # Include curve control points, pen caps and antialiasing. Repaint the
        # entire active stroke so changing a shape or Shift leaves no trails.
        margin = self.width * (1.5 if self.tool == HIGHLIGHT else 0.5) + 3
        return self.path().controlPointRect().adjusted(
            -margin, -margin, margin, margin).toAlignedRect()

    def hit_shape(self) -> QPainterPath:
        if self._hit is None and self.tool == TEXT:
            self._hit = self.path()  # 테두리가 아니라 글자 상자 안 전체
        if self._hit is None:
            s = QPainterPathStroker()
            s.setWidth(max(self.width, 6))
            self._hit = s.createStroke(self.path())
        return self._hit

    # ---- drawing --------------------------------------------------------
    def paint(self, qp: QPainter):
        color = QColor(self.color)
        if self.tool == TEXT:
            ctx = QAbstractTextDocumentLayout.PaintContext()
            ctx.palette.setColor(QPalette.ColorRole.Text, color)
            qp.save()
            qp.translate(self.points[0])
            self.doc().documentLayout().draw(qp, ctx)
            qp.restore()
            return
        if self.tool == HIGHLIGHT:
            color.setAlpha(90)
            pen = QPen(color, self.width * 3, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin)
        else:
            pen = QPen(color, self.width, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        qp.setPen(pen)
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawPath(self.path())


class TextBox(QTextEdit):
    """오버레이 위에 띄우는 글자 입력 상자. 입력기(한글 등)·붙여넣기는 Qt가 그대로 처리.
    완료하면 Overlay.commit_text()가 같은 배치의 TEXT 획으로 바꿔 넣음."""

    def __init__(self, ov: "Overlay", anchor: QPointF):
        super().__init__(ov)
        self.ov = ov
        self.anchor = anchor
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 0, 0, 0)
        self.document().setDocumentMargin(0)
        self.viewport().setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.document().documentLayout().documentSizeChanged.connect(lambda _: self.fit())
        self.apply_style()

    def apply_style(self):
        c = self.ov.color.name()
        self.setFont(text_font(self.ov.pen_width))
        self.document().setDefaultFont(text_font(self.ov.pen_width))
        self.setCursorWidth(max(2, text_px(self.ov.pen_width) // 12))
        self.setStyleSheet(f"QTextEdit {{ background: transparent; border: none; color: {c};"
                           f" selection-background-color: rgba(10,132,255,150); selection-color: {c}; }}")
        self.fit()

    def fit(self):
        old = self.geometry().adjusted(-8, -8, 8, 8)
        size = self.document().size()
        px = text_px(self.ov.pen_width)
        w = math.ceil(size.width()) + self.cursorWidth() + 2
        h = max(math.ceil(size.height()), math.ceil(px * 1.2))
        self.setGeometry(QRect(self.anchor.toPoint(), QPoint(self.anchor.toPoint()) + QPoint(w - 1, h - 1)))
        self.ov.update(old.united(self.geometry().adjusted(-8, -8, 8, 8)))

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape or (k in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                                      and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            return self.ov.commit_text()
        super().keyPressEvent(e)
        self.ensureCursorVisible()
        self.horizontalScrollBar().setValue(0)  # 상자가 글자에 맞춰 커지므로 스크롤 고정
        self.verticalScrollBar().setValue(0)

    def wheelEvent(self, e):  # 스크롤 대신 글자 크기 조절
        self.ov.change_width(1 if e.angleDelta().y() > 0 else -1)
        e.accept()

    def enterEvent(self, e):  # 상자 위에선 오버레이가 그리는 커서를 감춤 (I-빔 커서 사용)
        self.ov.cursor_in = False
        self.ov.update(self.ov._cursor_rect())
        super().enterEvent(e)


class Overlay(QWidget):
    modeChanged = pyqtSignal(bool)   # True = 그리기 모드
    stateChanged = pyqtSignal()
    keysChanged = pyqtSignal()
    settingsRequested = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | (Qt.WindowType.X11BypassWindowManagerHint if sys.platform.startswith("linux") else Qt.WindowType.Widget))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("OverInk 화면 필기")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.strokes: list[Stroke] = []
        self.undo_stack: list[tuple] = []
        self.redo_stack: list[tuple] = []
        self.current: Stroke | None = None
        self.erased_now: list[tuple[int, Stroke]] = []

        self.config = load_config()
        self.custom: list[str] = self.config["custom"]  # 최근 사용자 색 (최신이 앞)
        self.tool = PEN
        self.color = QColor(COLORS[0])
        self.picking = False                 # 스포이드 모드
        self.pick_img = None                 # 스포이드용으로 얼려 둔 화면 (QImage)
        self._grabbing = False
        self.pen_width = 4.0
        self.drawing_mode = True
        self.ink_visible = True
        self.cursor_pos = QPointF()
        self.cursor_in = False
        self.show_size_label = False
        self._label_timer = QTimer(self, singleShot=True, interval=900)
        self._label_timer.timeout.connect(self._hide_size_label)
        self._cache: QPixmap | None = None
        self.textbox: TextBox | None = None

        self.keys: dict[str, str] = self.config["keys"]
        self._key_actions = {t: (lambda t=t: self.set_tool(t)) for t, _, _ in TOOLS}
        self._key_actions.update({f"color{i + 1}": (lambda c=c: self.set_color(c))
                                  for i, c in enumerate(COLORS)})
        self._key_actions.update(
            color7=lambda: self.custom and self.set_color(self.custom[0]),
            eyedropper=self.start_eyedropper,
            thinner=lambda: self.change_width(-1),
            thicker=lambda: self.change_width(+1),
            undo=self.undo,
            redo=self.redo,
            clear=self.clear,
            passthrough=lambda: self.set_drawing_mode(False),
        )
        self._local_keys: dict[str, str] = {}
        self._rebuild_local_keys()

        self._cover_all_screens()

    # ---- window / mode --------------------------------------------------
    def _cover_all_screens(self):
        rect = QRect()
        for s in QGuiApplication.screens():
            rect = rect.united(s.geometry())
        self.setGeometry(rect)

    def set_drawing_mode(self, on: bool):
        self.drawing_mode = on
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not on)
        self.show()  # 플래그 변경 후 다시 표시해야 적용됨
        if on:
            self.raise_()
            self.activateWindow()
            self.setFocus()
            self.setCursor(Qt.CursorShape.BlankCursor)  # 대신 펜촉 크기 커서를 직접 그림
            self.cursor_pos = QPointF(self.mapFromGlobal(QCursor.pos()))
            self.cursor_in = self.rect().contains(self.cursor_pos.toPoint())
        else:
            self.commit_text()
            self._finish_stroke()
        self.update()
        self.modeChanged.emit(on)

    # ---- 대기(백그라운드) ↔ 호출 -----------------------------------------
    toolbar: "Toolbar | None" = None

    def is_summoned(self) -> bool:
        return self.isVisible()

    def summon(self):
        """대기 상태에서 불러내 바로 그리기 모드로."""
        self.ink_visible = True
        self.set_drawing_mode(True)
        if self.toolbar is not None:
            self.toolbar.show()
            self.toolbar.raise_()

    def dismiss(self):
        """그림을 지우고(Ctrl+Z로 복구 가능) 화면에서 완전히 숨김."""
        self.commit_text()
        self._finish_stroke()
        if self.picking:
            self.end_eyedropper()
        self.clear()
        self.hide()
        if self.toolbar is not None:
            self.toolbar.hide()
            self.toolbar.palette.hide()
        self.modeChanged.emit(False)

    def hotkey_toggle(self):
        if not self.is_summoned():
            self.summon()
        elif self.drawing_mode:
            self.dismiss()
        else:  # 투과 모드 → 다시 그리기
            self.summon()

    def toggle_mode(self):
        self.set_drawing_mode(not self.drawing_mode)

    def toggle_visible(self):
        self.commit_text()
        self.ink_visible = not self.ink_visible
        self.update()
        self.stateChanged.emit()

    # ---- settings -------------------------------------------------------
    def set_tool(self, tool: str):
        self.commit_text()
        self.tool = tool
        self.update()
        self.stateChanged.emit()

    def set_color(self, c: str | QColor, remember: bool = False):
        old_cursor_rect = self._cursor_rect()
        self.color = QColor(c)
        if self.tool == ERASER:
            self.tool = PEN
        if remember:
            self.remember_color(self.color)
        if self.textbox is not None:
            self.textbox.apply_style()
        self.update(old_cursor_rect.united(self._cursor_rect()))
        self.stateChanged.emit()

    def remember_color(self, c: QColor):
        """기본 색이 아니면 '최근 사용자 색' 맨 앞으로."""
        h = QColor(c).name()
        if h in COLORS or (self.custom and self.custom[0] == h):
            return
        if h in self.custom:
            self.custom.remove(h)
        self.custom.insert(0, h)
        del self.custom[N_CUSTOM:]
        save_config(self.config)
        self.stateChanged.emit()

    # ---- 스포이드 -------------------------------------------------------
    def start_eyedropper(self):
        if not self.isVisible() or self.picking:
            return
        self.commit_text()
        self._finish_stroke()
        self._grabbing = True
        self._ink_before_pick = self.ink_visible
        self.ink_visible = False          # 내 그림은 빼고 실제 화면 색만 읽기
        self.repaint()
        if self.toolbar is not None:
            self.toolbar.hide_for_capture()
        QTimer.singleShot(150, self._grab_for_pick)

    def _grab_for_pick(self):
        g = self.geometry()
        pm = self.screen().grabWindow(0, g.x(), g.y(), g.width(), g.height())
        self.pick_img = pm.toImage()
        self._grabbing = False
        self.ink_visible = self._ink_before_pick
        self.picking = True  # 툴바는 돋보기를 가리지 않게 고를 때까지 숨겨 둠
        self.set_drawing_mode(True)

    def _color_at(self, pos: QPointF) -> QColor:
        img = self.pick_img
        x, y = self._img_xy(pos)
        return QColor(img.pixel(x, y))

    def _img_xy(self, pos: QPointF) -> tuple[int, int]:
        img = self.pick_img
        sx, sy = img.width() / max(1, self.width()), img.height() / max(1, self.height())
        x = min(img.width() - 1, max(0, int(pos.x() * sx)))
        y = min(img.height() - 1, max(0, int(pos.y() * sy)))
        return x, y

    def end_eyedropper(self, pick_pos: QPointF | None = None):
        if pick_pos is not None and self.pick_img is not None:
            self.set_color(self._color_at(pick_pos), remember=True)
        self.picking = False
        self.pick_img = None
        if self.toolbar is not None and self.isVisible():
            self.toolbar.restore_after_capture()
        self.update()
        self.stateChanged.emit()

    def change_width(self, delta: float):
        old = self._cursor_rect()
        self.pen_width = max(MIN_W, min(MAX_W, self.pen_width + delta))
        if self.textbox is not None:
            self.textbox.apply_style()
        self.show_size_label = True
        self._label_timer.start()
        self.update(old.united(self._cursor_rect()))
        self.stateChanged.emit()

    # ---- history --------------------------------------------------------
    def _push(self, action: tuple, *, painted: bool = False):
        self.undo_stack.append(action)
        self.redo_stack.clear()
        if painted:
            self.stateChanged.emit()
        else:
            self._dirty()

    def undo(self):
        self.commit_text()
        if not self.undo_stack:
            return
        act = self.undo_stack.pop()
        self._apply(act, reverse=True)
        self.redo_stack.append(act)

    def redo(self):
        self.commit_text()
        if not self.redo_stack:
            return
        act = self.redo_stack.pop()
        self._apply(act, reverse=False)
        self.undo_stack.append(act)

    def _apply(self, act: tuple, reverse: bool):
        kind, payload = act
        if kind == "add":
            if reverse:
                self.strokes.remove(payload)
            else:
                self.strokes.append(payload)
            changed = [payload]
        elif kind == "erase":  # payload: [(index, stroke)] 원래 인덱스 오름차순
            if reverse:
                for idx, s in payload:
                    self.strokes.insert(idx, s)
            else:
                for _, s in reversed(payload):
                    self.strokes.remove(s)
            changed = [s for _, s in payload]
        else:  # clear: 화면 전체가 바뀜
            self.strokes = [] if not reverse else list(payload)
            return self._dirty()
        # 바뀐 획이 차지하던 영역만 캐시에서 다시 그림 (전체 다시 그리기는 큰 화면에서 버벅임)
        dirty = QRegion()
        for s in changed:
            dirty |= QRegion(s.paint_bounds())
        self._repaint_cache(dirty)
        self.stateChanged.emit()

    def _repaint_cache(self, dirty: QRegion):
        """캐시에서 dirty 영역을 비우고, 그 영역에 걸친 획을 순서대로 다시 그림
        (반투명 형광펜이 겹친 모양까지 그대로 유지)."""
        if dirty.isEmpty():
            return
        if self._cache is not None:
            qp = QPainter(self._cache)
            qp.setClipRegion(dirty)
            qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            qp.fillRect(dirty.boundingRect(), Qt.GlobalColor.transparent)
            qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            qp.setRenderHint(QPainter.RenderHint.Antialiasing)
            for s in self.strokes:
                if dirty.intersects(s.paint_bounds()):
                    s.paint(qp)
            qp.end()
        self.update(dirty)

    def clear(self):
        self.commit_text()
        if self.strokes:
            self._push(("clear", list(self.strokes)))
            self.strokes = []
            self._dirty()

    def _dirty(self):
        if self._cache is not None:
            self._spare = self._cache  # 다음 전체 다시 그리기 때 재사용 (큰 이미지 재할당 방지)
        self._cache = None
        self.update()
        self.stateChanged.emit()

    # ---- input ----------------------------------------------------------
    def _rebuild_local_keys(self):
        self._local_keys = {s: a for a, s in self.keys.items() if s and a not in GLOBAL_KEYS}

    def set_keys(self, keys: dict[str, str]):
        self.keys.clear()
        self.keys.update({a: norm_seq(keys.get(a, "")) for a in DEFAULT_KEYS})
        save_config(self.config)
        self._rebuild_local_keys()
        self.keysChanged.emit()

    def key_hint(self, action: str) -> str:
        """툴팁용: '  [Ctrl+Z]' — 단축키가 없으면 ''."""
        s = self.keys.get(action, "")
        return f"  [{key_text(s)}]" if s else ""

    def keyPressEvent(self, e):
        act = self._local_keys.get(event_seq(e))
        if self.picking and (e.key() == Qt.Key.Key_Escape or act == "passthrough"):
            return self.end_eyedropper()
        if act:
            return self._key_actions[act]()
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        self.change_width(1 if e.angleDelta().y() > 0 else -1)

    def mousePressEvent(self, e):
        if not self.drawing_mode:
            return
        pos = e.position()
        if self.picking:  # 좌클릭 = 색 선택, 그 외 = 취소
            self.end_eyedropper(pos if e.button() == Qt.MouseButton.LeftButton else None)
            return
        if self.textbox is not None:  # 입력 중 바깥 클릭 = 입력 완료
            self.commit_text()
        if e.button() == Qt.MouseButton.RightButton:  # 우클릭 = 임시 지우개
            self.erased_now = []
            self._erase_at(pos)
            self._right_erasing = True
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._right_erasing = False
        if self.tool == ERASER:
            self.erased_now = []
            self._erase_at(pos)
            return
        if self.tool == TEXT:
            return self.begin_text(pos)
        self.current = Stroke(self.tool, QColor(self.color), self.pen_width, [pos])
        if self.tool not in (PEN, HIGHLIGHT):
            self.current.points.append(pos)
        self.update(self.current.paint_bounds())

    def enterEvent(self, e):
        self.cursor_in = True
        self.update(self._cursor_rect())

    def leaveEvent(self, e):
        self.cursor_in = False
        self.update(self._cursor_rect())

    def _hide_size_label(self):
        self.show_size_label = False
        self.update(self._cursor_rect())

    def mouseMoveEvent(self, e):
        pos = e.position()
        old_rect = self._cursor_rect()
        self.cursor_pos = pos
        self.cursor_in = True
        if not self.drawing_mode:
            return
        if not e.buttons() and self.current is None:
            # 커서만 움직일 땐 커서 주변만 다시 그림 (대형 화면 성능)
            self.update(old_rect.united(self._cursor_rect()))
            return
        buttons = e.buttons()
        if buttons & Qt.MouseButton.RightButton or (buttons & Qt.MouseButton.LeftButton and self.tool == ERASER):
            self._erase_at(pos)
            self.update(QRegion(old_rect) | QRegion(self._cursor_rect()))
            return
        elif self.current is not None:
            c = self.current
            dirty = QRegion(old_rect) | QRegion(c.paint_bounds())
            if c.tool in (PEN, HIGHLIGHT) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                last = c.points[-1]
                if (pos - last).manhattanLength() >= 1.5:
                    c.points.append(pos)
            else:  # 도형 / Shift 직선: 시작점 + 끝점
                c.points[1:] = [pos]
            c.invalidate()
            dirty |= QRegion(c.paint_bounds()) | QRegion(self._cursor_rect())
            self.update(dirty)
            return
        self.update(old_rect.united(self._cursor_rect()))

    def mouseReleaseEvent(self, e):
        if self.erased_now:
            self._push(("erase", sorted(self.erased_now, key=lambda t: t[0])), painted=True)
            self.erased_now = []
        self._finish_stroke()

    def _finish_stroke(self):
        if self.current is not None:
            s = self.current
            self.current = None
            self.strokes.append(s)
            if self._cache is not None:
                # 새 획은 맨 위에 쌓이므로 캐시 전체를 다시 그리지 않고 덧그리기만 함
                qp = QPainter(self._cache)
                qp.setRenderHint(QPainter.RenderHint.Antialiasing)
                s.paint(qp)
                qp.end()
                self._push(("add", s), painted=True)
                self.update(s.paint_bounds())
            else:
                self._push(("add", s))
            self.remember_color(s.color)

    # ---- 텍스트 ---------------------------------------------------------
    def begin_text(self, pos: QPointF):
        """클릭한 곳이 첫 줄 세로 가운데가 되도록 입력 상자를 띄움."""
        half = text_px(self.pen_width) * 0.6
        # 입력 상자는 정수 좌표에 놓이므로 획 기준점도 맞춰 둠 (완료할 때 글자가 밀리지 않게)
        self.textbox = TextBox(self, QPointF(round(pos.x()), round(pos.y() - half)))
        self.textbox.show()
        self.textbox.setFocus()
        self.cursor_in = False
        self.update(self._cursor_rect().united(self.textbox_rect()))

    def textbox_rect(self) -> QRect:
        """입력 상자 + 점선 테두리 영역."""
        tb = self.textbox
        return tb.geometry().adjusted(-8, -8, 8, 8) if tb is not None else QRect()

    def commit_text(self):
        """입력 중인 글자를 TEXT 획으로 확정 (비어 있으면 그냥 닫음)."""
        tb = self.textbox
        if tb is None:
            return
        self.textbox = None
        text = tb.toPlainText().rstrip()
        area = tb.geometry().adjusted(-8, -8, 8, 8)
        tb.hide()
        tb.deleteLater()
        if self.drawing_mode and self.isVisible():
            self.setFocus()
        self.update(area)
        if text.strip():
            self.current = Stroke(TEXT, QColor(self.color), self.pen_width, [tb.anchor], text=text)
            self._finish_stroke()

    def _erase_at(self, pos: QPointF):
        r = max(self.pen_width * 2, 12)
        probe = QPainterPath()
        probe.addEllipse(pos, r, r)
        dirty = QRegion()
        for i in range(len(self.strokes) - 1, -1, -1):
            s = self.strokes[i]
            # Cheap rejection before constructing the exact stroked path.
            margin = max(s.width, 6) / 2 + 3
            bounds = s.path().controlPointRect().adjusted(-margin, -margin, margin, margin)
            if not bounds.intersects(probe.boundingRect()):
                continue
            if s.hit_shape().intersects(probe):
                self.erased_now.append((self._orig_index(i), s))
                dirty |= QRegion(s.paint_bounds())
                del self.strokes[i]
        self._repaint_cache(dirty)

    def _orig_index(self, cur_idx: int) -> int:
        """현재 리스트 인덱스를 이번 지우기 시작 전 인덱스로 변환."""
        idx = cur_idx
        for j in sorted(j for j, _ in self.erased_now):
            if j <= idx:
                idx += 1
        return idx

    # ---- paint ----------------------------------------------------------
    def _render_cache(self):
        dpr = self.devicePixelRatioF()
        w, h = int(self.width() * dpr), int(self.height() * dpr)
        pm = getattr(self, "_spare", None)
        self._spare = None
        if pm is None or pm.width() != w or pm.height() != h or pm.devicePixelRatio() != dpr:
            pm = QPixmap(w, h)
            pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        for s in self.strokes:
            s.paint(qp)
        qp.end()
        self._cache = pm

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        # 그리기 모드에선 거의 투명한 막을 깔아 X11에서 클릭이 확실히 잡히게 함
        qp.fillRect(self.rect(), QColor(0, 0, 0, 1 if self.drawing_mode else 0))
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.ink_visible:
            if self._cache is None:
                self._render_cache()
            qp.drawPixmap(0, 0, self._cache)
            if self.current is not None:
                qp.setRenderHint(QPainter.RenderHint.Antialiasing)
                self.current.paint(qp)
        if self.textbox is not None:  # 입력 상자 위치 표시 (어떤 배경에서도 보이게 흰/검 점선)
            r = QRectF(self.textbox.geometry()).adjusted(-5, -3, 5, 3)
            qp.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.setPen(QPen(QColor(0, 0, 0, 160), 1))
            qp.drawRect(r)
            qp.setPen(QPen(QColor(255, 255, 255, 220), 1, Qt.PenStyle.DashLine))
            qp.drawRect(r)
        if self.drawing_mode and self.cursor_in and not self._grabbing:
            if self.picking:
                self._paint_magnifier(qp)
            else:
                self._paint_cursor(qp)

    # ---- 펜촉 크기 커서 -----------------------------------------------------
    def _cursor_radius(self) -> float:
        if self.tool == ERASER:
            return max(self.pen_width * 2, 12)
        if self.tool == HIGHLIGHT:
            return self.pen_width * 3 / 2
        if self.tool == TEXT:
            return text_px(self.pen_width) * 0.6
        return self.pen_width / 2

    MAG_N, MAG_CELL = 11, 12  # 돋보기: 11x11 픽셀을 12배 확대

    def _mag_box(self) -> QRectF:
        size = self.MAG_N * self.MAG_CELL
        p = self.cursor_pos
        x = p.x() + 24 if p.x() + 24 + size < self.width() else p.x() - 24 - size
        y = p.y() + 24 if p.y() + 24 + size + 28 < self.height() else p.y() - 24 - size - 28
        return QRectF(x, y, size, size)

    def _paint_magnifier(self, qp: QPainter):
        img = self.pick_img
        if img is None:
            return
        p = self.cursor_pos
        box = self._mag_box()
        n, cell = self.MAG_N, self.MAG_CELL
        cx, cy = self._img_xy(p)
        half = n // 2
        light, dark = QColor(255, 255, 255, 230), QColor(0, 0, 0, 200)

        qp.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        qp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        qp.fillRect(box, QColor(40, 40, 40))
        qp.drawImage(box, img, QRectF(cx - half, cy - half, n, n))
        qp.setPen(QPen(QColor(255, 255, 255, 40), 1))  # 픽셀 격자
        for i in range(1, n):
            qp.drawLine(QPointF(box.x() + i * cell, box.y()), QPointF(box.x() + i * cell, box.bottom()))
            qp.drawLine(QPointF(box.x(), box.y() + i * cell), QPointF(box.right(), box.y() + i * cell))
        center = QRectF(box.x() + half * cell, box.y() + half * cell, cell, cell)
        qp.setPen(QPen(dark, 3)); qp.drawRect(center)
        qp.setPen(QPen(light, 1)); qp.drawRect(center)
        qp.setPen(QPen(light, 2)); qp.setBrush(Qt.BrushStyle.NoBrush); qp.drawRect(box)

        color = QColor(img.pixel(cx, cy))
        lbl = QRectF(box.x(), box.bottom() + 4, box.width(), 24)
        qp.setPen(Qt.PenStyle.NoPen); qp.setBrush(QColor(28, 28, 30, 230))
        qp.drawRoundedRect(lbl, 5, 5)
        qp.setBrush(color); qp.setPen(QPen(light, 1))
        qp.drawRect(QRectF(lbl.x() + 6, lbl.y() + 5, 14, 14))
        qp.setFont(QFont(qp.font().family(), 10, QFont.Weight.Bold))
        qp.drawText(lbl.adjusted(26, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, color.name().upper())

        qp.setRenderHint(QPainter.RenderHint.Antialiasing)  # 실제 커서 위치 표시
        for c, w in ((dark, 3.0), (light, 1.0)):
            qp.setPen(QPen(c, w))
            qp.drawEllipse(p, 5, 5)

    def _cursor_rect(self) -> QRect:
        if self.picking:
            p = self.cursor_pos
            return (self._mag_box().adjusted(-4, -4, 4, 34)
                    .united(QRectF(p.x() - 9, p.y() - 9, 18, 18)).toAlignedRect())
        r = self._cursor_radius() + 12
        p = self.cursor_pos
        rect = QRectF(p.x() - r, p.y() - r, 2 * r, 2 * r)
        rect = rect.united(QRectF(p.x() + r - 4, p.y() + r - 4, 70, 30))  # 크기 라벨 영역
        return rect.toAlignedRect().adjusted(-2, -2, 2, 2)

    def _paint_cursor(self, qp: QPainter):
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        p, r = self.cursor_pos, self._cursor_radius()
        light, dark = QColor(255, 255, 255, 230), QColor(0, 0, 0, 200)

        if self.tool == ERASER:
            qp.setPen(QPen(light, 1.5))
            qp.setBrush(QColor(0, 0, 0, 40))
            qp.drawEllipse(p, r, r)
        elif self.tool == TEXT:  # 글자 높이만 한 I-빔 (현재 색)
            s = max(3.0, r * 0.3)
            for color, w in ((dark, 4.0), (light, 2.5), (QColor(self.color), 1.5)):
                qp.setPen(QPen(color, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                qp.drawLine(p + QPointF(0, -r), p + QPointF(0, r))
                qp.drawLine(p + QPointF(-s, -r), p + QPointF(s, -r))
                qp.drawLine(p + QPointF(-s, r), p + QPointF(s, r))
        else:
            fill = QColor(self.color)
            fill.setAlpha(90 if self.tool == HIGHLIGHT else 220)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(fill)
            if self.tool == HIGHLIGHT:  # 형광펜은 납작한 끝 → 사각형 미리보기
                qp.drawRect(QRectF(p.x() - r, p.y() - r, 2 * r, 2 * r))
            else:
                qp.drawEllipse(p, r, r)
            # 어떤 배경에서도 보이도록 흰/검 이중 테두리
            ring = max(r, 2.5)
            qp.setBrush(Qt.BrushStyle.NoBrush)
            for color, off in ((dark, 1.0), (light, 0.0)):
                qp.setPen(QPen(color, 1.0))
                if self.tool == HIGHLIGHT:
                    qp.drawRect(QRectF(p.x() - ring - off, p.y() - ring - off,
                                       2 * (ring + off), 2 * (ring + off)))
                else:
                    qp.drawEllipse(p, ring + off, ring + off)
            if self.tool in (ARROW, RECT, ELLIPSE):  # 도형 도구는 정확한 기준점 표시
                g = ring + 3
                for color, w in ((dark, 3.0), (light, 1.0)):
                    qp.setPen(QPen(color, w))
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        qp.drawLine(p + QPointF(dx * g, dy * g), p + QPointF(dx * (g + 6), dy * (g + 6)))

        if self.show_size_label:
            qp.setFont(QFont(qp.font().family(), 10, QFont.Weight.Bold))
            text = f"{text_px(self.pen_width) if self.tool == TEXT else int(self.pen_width)}px"
            box = QRectF(p.x() + r + 6, p.y() + r + 4, 48, 20)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QColor(28, 28, 30, 220))
            qp.drawRoundedRect(box, 5, 5)
            qp.setPen(light)
            qp.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class HoverTips(QObject):
    """툴바 창은 활성화되지 않아 Qt 기본 툴팁이 안 뜨므로 직접 띄움."""

    def __init__(self, parent):
        super().__init__(parent)
        self.target: QWidget | None = None
        self.timer = QTimer(self, singleShot=True, interval=450)
        self.timer.timeout.connect(self._show)

    def watch(self, w: QWidget):
        w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Enter:
            self.target = obj
            self.timer.start()
        elif t in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide):
            self.timer.stop()
            self.target = None
            QToolTip.hideText()
        elif t == QEvent.Type.ToolTip:
            return True  # Qt 기본 툴팁과 중복 방지
        return False

    def _show(self):
        w = self.target
        if w is not None and w.toolTip():
            pos = w.mapToGlobal(QPoint(0, w.height() + 6))
            QToolTip.showText(pos, w.toolTip(), w)


class _EmbeddedColorDialog(QColorDialog):
    """창 안에 박아 넣는 QColorDialog. Esc 등으로 닫히지 않고 신호만 보냄."""
    closeRequested = pyqtSignal()

    def done(self, r):
        self.closeRequested.emit()


class Palette(QWidget):
    """색상 팔레트 창: 기본 색 격자 + 색상환 + HEX/RGB 입력."""

    def __init__(self, ov: Overlay):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | (Qt.WindowType.X11BypassWindowManagerHint if sys.platform.startswith("linux") else Qt.WindowType.Widget))
        self.ov = ov
        self.setStyleSheet("""
            Palette, QWidget#pal { background: #2c2c2e; color: #eee; }
            QLabel { color: #eee; }
            QPushButton { background: #3a3a3c; color: #eee; border: 1px solid #555;
                          border-radius: 5px; padding: 4px 10px; }
            QPushButton:hover { background: #48484a; }
            QLineEdit, QSpinBox { background: #1c1c1e; color: #eee; border: 1px solid #555; }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        head = QHBoxLayout()
        title = QLabel("색상 팔레트")
        title.setStyleSheet("font-weight: bold;")
        head.addWidget(title)
        head.addStretch()
        pick = QPushButton("💧 화면에서 추출  (I)")
        pick.clicked.connect(self._eyedropper)
        done = QPushButton("완료")
        done.clicked.connect(self.close_palette)
        head.addWidget(pick)
        head.addWidget(done)
        lay.addLayout(head)

        self.dlg = _EmbeddedColorDialog(self)
        self.dlg.setOptions(QColorDialog.ColorDialogOption.NoButtons
                            | QColorDialog.ColorDialogOption.DontUseNativeDialog)
        self.dlg.setWindowFlags(Qt.WindowType.Widget)
        # 간소화: 기본 색상 격자(툴바에 이미 있음), 'Pick Screen Color'(내 그림까지 찍힘 →
        # 위 스포이드 버튼 사용), '사용자 색에 추가'(쓴 색이 자동으로 쌓임) 숨김
        for b in self.dlg.findChildren(QPushButton):
            b.hide()
        custom_lbl = None
        for lbl in self.dlg.findChildren(QLabel):
            t = lbl.text().replace("&", "").lower()
            if "basic" in t or "기본" in t:
                lbl.hide()
                if lbl.buddy() is not None:
                    lbl.buddy().hide()
            elif "custom" in t or "사용자" in t:
                custom_lbl = lbl
        self.dlg.currentColorChanged.connect(lambda c: self.ov.set_color(c))
        self.dlg.closeRequested.connect(self.close_palette)
        lay.addWidget(self.dlg)
        # '사용자 색' 격자를 다이얼로그 밖(아래)으로 꺼내 → 왼쪽 열이 비어 사라짐
        # (화면이 아주 작으면 Qt가 사용자 색 영역을 아예 만들지 않음)
        if custom_lbl is not None and custom_lbl.buddy() is not None:
            well = custom_lbl.buddy()
            custom_lbl.setText("최근 사용자 색")
            custom_lbl.setStyleSheet("font-weight: bold; margin-top: 4px;")
            lay.addWidget(custom_lbl)
            lay.addWidget(well)
        self._drag: QPoint | None = None

    def open_below(self, anchor: QWidget):
        for i in range(N_CUSTOM):  # 다이얼로그 '사용자 색' 칸 = 최근 사용자 색
            h = self.ov.custom[i] if i < len(self.ov.custom) else "#3a3a3c"
            QColorDialog.setCustomColor(i, QColor(h))
        self.dlg.update()
        self.dlg.blockSignals(True)
        self.dlg.setCurrentColor(self.ov.color)
        self.dlg.blockSignals(False)
        self.adjustSize()
        g = anchor.frameGeometry()
        scr = anchor.screen().availableGeometry()
        x = min(max(scr.left(), g.center().x() - self.width() // 2), scr.right() - self.width())
        self.move(x, g.bottom() + 8)
        self.show()
        self.raise_()
        self.activateWindow()  # HEX 입력을 위해 키보드 포커스

    def close_palette(self):
        if self.isVisible():
            self.hide()
            self.ov.remember_color(self.ov.color)
            if self.ov.drawing_mode and self.ov.isVisible():
                self.ov.activateWindow()
                self.ov.setFocus()

    def _eyedropper(self):
        self.hide()
        self.ov.start_eyedropper()

    # 빈 곳 드래그로 이동
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


class _KeyHints(dict):
    """툴팁 템플릿의 {id} → 현재 단축키 표시."""

    def __init__(self, ov: Overlay):
        super().__init__()
        self.ov = ov

    def __missing__(self, action: str) -> str:
        return self.ov.key_hint(action)


class Toolbar(QWidget):
    """항상 위에 떠 있는 작은 툴바. 투과 모드에서도 클릭 가능 (별도 창)."""

    def __init__(self, ov: Overlay):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | (Qt.WindowType.X11BypassWindowManagerHint if sys.platform.startswith("linux") else Qt.WindowType.Widget))
        self.ov = ov
        self.setWindowTitle("OverInk 도구 모음")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag: QPoint | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)

        self.setStyleSheet("""
            QWidget#bar { background: rgba(28,28,30,230); border-radius: 10px; }
            QToolButton { color: #eee; background: transparent; border: none;
                          border-radius: 6px; font-size: 16px; min-width: 30px; min-height: 30px; }
            QToolButton:hover { background: rgba(255,255,255,30); }
            QToolButton:checked { background: rgba(10,132,255,200); }
            QLabel { color: #aaa; font-size: 12px; padding: 0 4px; }
        """)
        bar = QWidget(self)
        bar.setObjectName("bar")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(bar)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(2)

        grip = QLabel("⋮⋮")
        grip.setToolTip("드래그해서 툴바 이동")
        lay.addWidget(grip)

        self._tip_templates: list[tuple[QWidget, str]] = []  # 단축키가 바뀌면 다시 채움

        def button(text: str, tip: str, **kw) -> QToolButton:
            b = QToolButton(text=text, **kw)
            self._tip_templates.append((b, tip))
            return b

        self.mode_btn = button("✏️", "그리기 ↔ 투과 모드 전환{passthrough}\n"
                                     "투과 모드: 그림은 남기고 클릭은 아래 앱으로 · 다시 그리기{toggle}",
                               checkable=True)
        self.mode_btn.clicked.connect(ov.toggle_mode)
        lay.addWidget(self.mode_btn)

        self.tool_group = QButtonGroup(self)
        self.tool_btns: dict[str, QToolButton] = {}
        for tool, icon, tip in TOOLS:
            b = button(icon, tip, checkable=True)
            b.clicked.connect(lambda _, t=tool: self._pick_tool(t))
            self.tool_group.addButton(b)
            self.tool_btns[tool] = b
            lay.addWidget(b)

        self.palette = Palette(ov)
        self.cur_btn = button("", "현재 색 — 클릭하면 색상 팔레트 열기\n색상환, HEX 입력, 최근 사용자 색")
        self.cur_btn.clicked.connect(self._toggle_palette)
        lay.addWidget(self.cur_btn)
        pick = button("💧", "스포이드 — 화면에서 색 추출{eyedropper}\n클릭으로 선택, Esc·우클릭으로 취소")
        pick.clicked.connect(self._eyedropper)
        lay.addWidget(pick)

        self.color_btns: list[tuple[QToolButton, str]] = []
        for i, c in enumerate(COLORS):
            b = button("", f"{COLOR_NAMES[i]}{{color{i + 1}}}")
            b.clicked.connect(lambda _, c=c: self._pick_color(c))
            self.color_btns.append((b, c))
            lay.addWidget(b)
        self.custom_btn = QToolButton()
        self.custom_btn.clicked.connect(self._pick_custom)
        lay.addWidget(self.custom_btn)

        self.size_lbl = QLabel()
        self.size_lbl.setToolTip("현재 펜촉 굵기 (휠로도 조절)")
        lay.addWidget(self.size_lbl)
        for txt, d, tip in (("−", -1, "펜촉 가늘게{thinner}  · 휠 아래"),
                            ("+", 1, "펜촉 굵게{thicker}  · 휠 위")):
            b = button(txt, tip)
            b.clicked.connect(lambda _, d=d: ov.change_width(d))
            lay.addWidget(b)

        for txt, fn, tip in (("↶", ov.undo, "실행 취소{undo}"),
                             ("↷", ov.redo, "다시 실행{redo}"),
                             ("🗑", ov.clear, "그린 것 전체 지우기{clear}\n실행 취소로 되돌릴 수 있음"),
                             ("👁", ov.toggle_visible, "그림 잠시 숨기기/보이기{visible}"),
                             ("⚙", ov.settingsRequested.emit, "단축키 설정"),
                             ("⌄", ov.dismiss, "백그라운드로 숨기기{toggle}\n"
                                               "그림은 지워지고, 다시 불렀을 때 실행 취소{undo}로 복구 가능"),
                             ("✕", QApplication.quit, "OverInk 완전히 종료{quit}")):
            b = button(txt, tip)
            b.clicked.connect(fn)
            lay.addWidget(b)

        ov.modeChanged.connect(lambda _: self.refresh())
        ov.stateChanged.connect(self.refresh)
        ov.keysChanged.connect(self.apply_key_tips)
        self.apply_key_tips()
        self.refresh()
        self.tips = HoverTips(self)
        for w in bar.findChildren(QWidget):
            if w.toolTip():
                self.tips.watch(w)
        self.adjustSize()
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.center().x() - self.width() // 2, scr.top() + 12)

    def _pick_tool(self, t):
        self.ov.set_tool(t)
        if not self.ov.drawing_mode:
            self.ov.set_drawing_mode(True)
        self.raise_()

    def _toggle_palette(self):
        if self.palette.isVisible():
            self.palette.close_palette()
        else:
            if not self.ov.drawing_mode:
                self.ov.set_drawing_mode(True)
            self.palette.open_below(self)

    def _eyedropper(self):
        self.palette.hide()
        self.ov.start_eyedropper()

    def hide_for_capture(self):
        self._was_visible = self.isVisible()
        self.hide()

    def restore_after_capture(self):
        if getattr(self, "_was_visible", True):
            self.show()
            self.raise_()

    def _pick_custom(self):
        if self.ov.custom:
            self._pick_color(self.ov.custom[0])
        else:
            self._toggle_palette()

    def _pick_color(self, c):
        self.ov.set_color(c)
        if not self.ov.drawing_mode:
            self.ov.set_drawing_mode(True)
        self.raise_()

    def _tip(self, template: str) -> str:
        return template.format_map(_KeyHints(self.ov))

    def apply_key_tips(self):
        for w, t in self._tip_templates:
            w.setToolTip(self._tip(t))
        self.refresh()

    def refresh(self):
        ov = self.ov
        self.mode_btn.setChecked(ov.drawing_mode)
        self.mode_btn.setText("✏️" if ov.drawing_mode else "🖱")
        self.tool_btns[ov.tool].setChecked(True)
        cur = ov.color.name()
        self.cur_btn.setStyleSheet(
            f"QToolButton {{ background:{cur}; border:2px solid #fff; border-radius:6px; "
            f"min-width:26px; max-width:26px; min-height:26px; max-height:26px; margin:2px 4px; }}")
        dot = ("border-radius:11px; min-width:18px; max-width:18px; "
               "min-height:18px; max-height:18px; margin:4px;")
        for b, c in self.color_btns:
            ring = "#0a84ff" if c == cur and ov.tool != ERASER else "rgba(255,255,255,60)"
            b.setStyleSheet(f"QToolButton {{ background:{c}; border:2px solid {ring}; {dot} }}")
        if ov.custom:
            c = ov.custom[0]
            ring = "#0a84ff" if c == cur and ov.tool != ERASER else "rgba(255,255,255,60)"
            self.custom_btn.setText("")
            self.custom_btn.setToolTip(self._tip(f"최근 사용자 색 {c.upper()}{{color7}}\n"
                                                 "팔레트·스포이드로 고른 색이 여기 남음"))
            self.custom_btn.setStyleSheet(f"QToolButton {{ background:{c}; border:2px solid {ring}; {dot} }}")
        else:
            self.custom_btn.setText("+")
            self.custom_btn.setToolTip(self._tip("사용자 색 없음 — 클릭해서 팔레트에서 고르기\n"
                                                 "고른 색이 이 칸에 남음{color7}"))
            self.custom_btn.setStyleSheet(f"QToolButton {{ background:transparent; color:#aaa; font-size:13px; "
                                          f"border:2px dashed rgba(255,255,255,90); padding:0; {dot} }}")
        self.size_lbl.setText(f"글자 {text_px(ov.pen_width)}px" if ov.tool == TEXT else f"{int(ov.pen_width)}px")
        self.raise_()

    # 드래그 이동
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


_PYNPUT_MODS = {"Ctrl": "<ctrl>", "Alt": "<alt>", "Shift": "<shift>", "Meta": "<cmd>"}
_PYNPUT_KEYS = {
    "Esc": "esc", "Space": "space", "Tab": "tab", "Return": "enter", "Enter": "enter",
    "Backspace": "backspace", "Del": "delete", "Ins": "insert", "Home": "home", "End": "end",
    "PgUp": "page_up", "PgDown": "page_down", "Up": "up", "Down": "down", "Left": "left",
    "Right": "right", "Print": "print_screen", "Pause": "pause",
}


def to_pynput(seq: str) -> str | None:
    """'Ctrl+Alt+P' → '<ctrl>+<alt>+p'. 변환할 수 없는 키면 None."""
    mods, rest = [], seq
    while True:
        for m, p in _PYNPUT_MODS.items():
            if rest.startswith(m + "+") and len(rest) > len(m) + 1:
                mods.append(p)
                rest = rest[len(m) + 1:]
                break
        else:
            break
    if len(rest) == 1 and rest != "+":
        key = rest.lower()
    elif rest[:1] == "F" and rest[1:].isdigit():
        key = f"<{rest.lower()}>"
    elif rest in _PYNPUT_KEYS:
        key = f"<{_PYNPUT_KEYS[rest]}>"
    else:
        return None
    return "+".join(mods + [key])


def global_key_error(seq: str) -> str | None:
    """전역 단축키로 쓸 수 없으면 이유를, 괜찮으면 None."""
    if not seq:
        return None
    combo = to_pynput(seq)
    if combo is None:
        return "전역 단축키로 쓸 수 없는 키입니다"
    last = combo.split("+")[-1]
    if not any(m in combo for m in ("<ctrl>", "<alt>", "<cmd>")) and not (
            last.startswith("<f") and last[2:-1].isdigit()):
        return "전역 단축키는 Ctrl·Alt·Super 중 하나와 함께 눌러야 합니다 (F키는 단독 가능)"
    try:
        from pynput import keyboard
        keyboard.HotKey.parse(combo)
    except ImportError:
        pass
    except Exception:
        return "전역 단축키로 쓸 수 없는 키입니다"
    return None


class HotkeyBridge(QObject):
    """pynput 스레드 → Qt 메인 스레드로 전달. start()로 단축키를 (다시) 등록."""
    fired = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.listener = None
        try:
            from pynput import keyboard
            self._kb = keyboard
        except Exception as ex:  # pynput 없거나 X 접근 불가
            self._kb = None
            print(f"[OverInk] 전역 단축키 비활성화: {ex}", file=sys.stderr)

    def start(self, keys: dict[str, str]):
        self.stop()
        if self._kb is None:
            return
        combos = {}
        for a in GLOBAL_KEYS:
            if keys.get(a) and not global_key_error(keys[a]):
                combos[to_pynput(keys[a])] = a
        if not combos:
            return
        try:
            self.listener = self._kb.GlobalHotKeys(
                {c: (lambda a=a: self.fired.emit(a)) for c, a in combos.items()})
        except Exception as ex:
            print(f"[OverInk] 전역 단축키 등록 실패: {ex}", file=sys.stderr)
            return
        self.listener.daemon = True
        self.listener.start()

    def stop(self):
        if self.listener is not None:
            self.listener.stop()
            self.listener = None


class KeySettings(QDialog):
    """단축키 설정 창. 겹치거나 쓸 수 없는 키가 있으면 저장 버튼이 꺼짐."""

    def __init__(self, keys: dict[str, str]):
        super().__init__(None, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("OverInk 단축키 설정")
        self.setWindowIcon(QApplication.windowIcon())
        self.edits: dict[str, QKeySequenceEdit] = {}

        root = QVBoxLayout(self)
        hint = QLabel("입력칸을 클릭한 뒤 원하는 키 조합을 누르세요. 칸 오른쪽 ✕로 지우면 단축키 없음.\n"
                      "휠(굵기) · Shift 누른 채 그리기(직선) · 우클릭 드래그(지우개) · "
                      "스포이드 중 Esc(취소)는 고정입니다.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setColumnStretch(1, 1)
        row = 0
        for title, glob in (("전역 단축키 — 다른 앱을 쓰는 중에도 동작", True),
                            ("그리기 모드 단축키", False)):
            head = QLabel(f"<b>{title}</b>")
            head.setContentsMargins(0, 10 if row else 0, 0, 2)
            grid.addWidget(head, row, 0, 1, 3)
            row += 1
            for a, label, default, g in KEY_ACTIONS:
                if g != glob:
                    continue
                grid.addWidget(QLabel(label), row, 0)
                ed = QKeySequenceEdit(QKeySequence(keys.get(a, "")))
                ed.setMaximumSequenceLength(1)
                ed.setClearButtonEnabled(True)
                ed.keySequenceChanged.connect(self._validate)
                grid.addWidget(ed, row, 1)
                rb = QToolButton(text="↺", toolTip=f"기본값으로: {key_text(default) or '없음'}")
                rb.clicked.connect(lambda _, a=a: self.edits[a].setKeySequence(QKeySequence(DEFAULT_KEYS[a])))
                grid.addWidget(rb, row, 2)
                self.edits[a] = ed
                row += 1
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.err = QLabel()
        self.err.setStyleSheet("color: #d70015;")
        self.err.setWordWrap(True)
        root.addWidget(self.err)

        SB = QDialogButtonBox.StandardButton
        self.buttons = QDialogButtonBox(SB.RestoreDefaults | SB.Cancel | SB.Save)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(SB.RestoreDefaults).clicked.connect(self.restore_defaults)
        root.addWidget(self.buttons)

        self.resize(480, 640)
        self._validate()

    def restore_defaults(self):
        for a, ed in self.edits.items():
            ed.setKeySequence(QKeySequence(DEFAULT_KEYS[a]))

    def result_keys(self) -> dict[str, str]:
        return {a: norm_seq(ed.keySequence().toString(_PORTABLE)) for a, ed in self.edits.items()}

    def _validate(self):
        keys = self.result_keys()
        bad: dict[str, str] = {}
        owner: dict[str, str] = {}
        for a, s in keys.items():
            if not s:
                continue
            if a in GLOBAL_KEYS and (why := global_key_error(s)):
                bad[a] = f"{KEY_LABELS[a]}: {why}"
            if s in owner:
                msg = f"‘{key_text(s)}’ 가 겹칩니다: {KEY_LABELS[owner[s]]} / {KEY_LABELS[a]}"
                bad.setdefault(owner[s], msg)
                bad[a] = msg
            owner.setdefault(s, a)
        for a, ed in self.edits.items():
            ed.setStyleSheet("QLineEdit { background: #ffd7d5; color: #000; }" if a in bad else "")
        self.err.setText("\n".join(dict.fromkeys(bad.values())))
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(not bad)


def render_icon(size: int = 256, background: bool = True) -> QPixmap:
    """앱 아이콘: 둥근 어두운 사각형 위 빨간 잉크 곡선 + 펜촉 점."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    qp.scale(size / 64, size / 64)
    if background:
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QColor("#1c1c1e"))
        qp.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    qp.setPen(QPen(QColor(COLORS[0]), 7 if background else 8, cap=Qt.PenCapStyle.RoundCap))
    path = QPainterPath(QPointF(13, 44))
    path.cubicTo(QPointF(23, 14), QPointF(35, 58), QPointF(50, 20))
    qp.drawPath(path)
    if background:
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QColor(COLORS[1]))
        qp.drawEllipse(QPointF(50, 20), 4.5, 4.5)
    qp.end()
    return pm


def make_icon() -> QIcon:
    return QIcon(render_icon(256))


def write_ico(path: str, sizes=(16, 20, 24, 32, 40, 48, 64, 256)):
    """여러 크기를 담은 .ico 저장 (Windows 바로가기·작업표시줄에서 작은 크기도 선명하게).
    각 크기는 PNG로 넣음 (Vista 이후 지원)."""
    import struct
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    pngs = []
    for s in sizes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        render_icon(s).save(buf, "PNG")
        pngs.append((s, bytes(ba)))
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for s, data in pngs:
        dim = 0 if s >= 256 else s  # 256은 0으로 표기
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    Path(path).write_bytes(head + entries + blobs)


SERVER_NAME = "overink-single-instance"


def forward_to_running_instance(msg: bytes) -> bool:
    """이미 실행 중이면 메시지를 보내고 True. (두 번 실행 방지)"""
    from PyQt6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(msg)
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def listen_single_instance(on_message) -> object:
    from PyQt6.QtNetwork import QLocalServer
    QLocalServer.removeServer(SERVER_NAME)  # 비정상 종료로 남은 소켓 정리
    server = QLocalServer()
    server.listen(SERVER_NAME)

    def accept():
        conn = server.nextPendingConnection()
        def read():
            on_message(bytes(conn.readAll()).decode(errors="ignore").strip())
            conn.deleteLater()
        conn.readyRead.connect(read)
    server.newConnection.connect(accept)
    return server


def _setup_input_method():
    """한글 등 입력기: pip로 받은 PyQt6에는 fcitx용 Qt 플러그인이 없어 fcitx 환경에서
    한글이 안 써짐. fcitx5는 IBus 호환 접속(ibusfrontend)도 받으므로, 플러그인이 없으면
    PyQt6에 들어 있는 ibus 플러그인으로 연결."""
    if not sys.platform.startswith("linux"):
        return
    im = os.environ.get("QT_IM_MODULE", "")
    if not im.startswith("fcitx"):
        return
    from PyQt6.QtCore import QLibraryInfo
    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "platforminputcontexts"
    if not any(plugins.glob("*fcitx*")):
        os.environ["QT_IM_MODULE"] = "ibus"


def main():
    _setup_input_method()
    app = QApplication(sys.argv)
    app.setApplicationName("OverInk")
    app.setQuitOnLastWindowClosed(False)
    from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator
    tr = QTranslator(app)  # 색상 팔레트(QColorDialog) 문구 한국어화
    if tr.load(QLocale(QLocale.Language.Korean), "qtbase", "_",
               QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(tr)
    app.setStyleSheet("QToolTip { color: #eee; background: #1c1c1e; border: 1px solid #444;"
                      " border-radius: 4px; padding: 4px 6px; font-size: 12px; }")
    # 터미널 Ctrl+C로 종료되도록: Qt 루프가 주기적으로 파이썬 시그널 처리 기회를 줌
    import signal
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    app._sigtimer = QTimer(interval=200)
    app._sigtimer.timeout.connect(lambda: None)
    app._sigtimer.start()
    icon = make_icon()
    app.setWindowIcon(icon)

    if "--export-icon" in sys.argv:  # 설치 스크립트용 (.png 또는 Windows용 .ico)
        out = sys.argv[sys.argv.index("--export-icon") + 1]
        if out.lower().endswith(".ico"):
            write_ico(out)
        else:
            render_icon(256).save(out)
        return
    # 이미 실행 중이면: --show 로 실행된 경우 그 인스턴스를 불러내고 종료
    if forward_to_running_instance(b"show" if "--show" in sys.argv else b"ping"):
        print("[OverInk] 이미 실행 중입니다.", file=sys.stderr)
        return

    ov = Overlay()
    bar = Toolbar(ov)
    ov.toolbar = bar
    app._server = listen_single_instance(lambda m: ov.summon() if m == "show" else None)
    if "--show" in sys.argv:
        ov.summon()
    else:
        print(f"[OverInk] 백그라운드 대기 중 — {key_text(ov.keys['toggle']) or '트레이 아이콘'}"
              " 로 그리기 시작", file=sys.stderr)

    hk = HotkeyBridge()
    actions = {
        "toggle": ov.hotkey_toggle,
        "clear_any": ov.clear,
        "visible": ov.toggle_visible,
        "quit": app.quit,
    }
    hk.fired.connect(lambda name: actions[name]())
    hk.start(ov.keys)

    def open_settings():
        dlg = getattr(app, "_settings", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        if ov.isVisible() and ov.drawing_mode:
            ov.set_drawing_mode(False)  # 오버레이가 키 입력을 가로채지 않게
        bar.palette.hide()
        hk.stop()  # 설정 중 누른 키가 전역 단축키로 실행되지 않게
        dlg = app._settings = KeySettings(ov.keys)

        def finished(result):
            if result == QDialog.DialogCode.Accepted:
                ov.set_keys(dlg.result_keys())
            hk.start(ov.keys)
        dlg.finished.connect(finished)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
    ov.settingsRequested.connect(open_settings)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(icon)
        menu = QMenu()
        toggle_act = QAction(menu)
        for act, text, fn in ((toggle_act, None, ov.hotkey_toggle),
                              (None, "전체 지우기", ov.clear),
                              (None, "단축키 설정…", open_settings),
                              (None, "종료", app.quit)):
            act = act or QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        tray.setContextMenu(menu)

        def update_tray_text():
            k = key_text(ov.keys["toggle"])
            toggle_act.setText(f"그리기 시작 / 숨기기  ({k})" if k else "그리기 시작 / 숨기기")
            tray.setToolTip(f"OverInk — {k} 로 그리기" if k else "OverInk — 클릭해서 그리기")
        update_tray_text()
        ov.keysChanged.connect(update_tray_text)
        tray.activated.connect(
            lambda r: ov.hotkey_toggle() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        app._tray = tray  # GC 방지

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
