from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from src.main import qt_theme

_NODE_COLORS = ["#e8960a", "#d4700a", "#f0b830", "#c85a08", "#f0d060", "#e07820"]
_MAX_DIST = 150.0
_DENSITY = 12000  # one node per this many pixels


@dataclass
class _Node:
    x: float
    y: float
    vx: float
    vy: float
    r: float
    glow: float
    color: QColor
    opacity: float
    pulse: float
    speed: float = field(default=0.01)


class NeuralBackground(QWidget):
    """
    Animated glowing neural-network backdrop, ported from neural-background.html.

    Nodes drift, wrap at the edges, pulse in size, and connect with faint amber
    lines when close. Child widgets are laid on top; translucent cards let the
    animation show through, matching the reference's depth.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nodes: list[_Node] = []
        self._active = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(33)  # ~30 fps

    def set_active(self, active: bool) -> None:
        """Enable/disable the animated background (a plain fill when off)."""
        self._active = active
        if active:
            self.resizeEvent(None)  # repopulate nodes for the current size
            self._timer.start(33)
        else:
            self._timer.stop()
            self._nodes = []
        self.update()

    # ------------------------------------------------------------------

    def _make_node(self) -> _Node:
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        return _Node(
            x=random.uniform(0, w),
            y=random.uniform(0, h),
            vx=random.uniform(-0.45, 0.45),
            vy=random.uniform(-0.45, 0.45),
            r=1.8 + random.random() * 3.2,
            glow=8 + random.random() * 18,
            color=QColor(random.choice(_NODE_COLORS)),
            opacity=0.35 + random.random() * 0.65,
            pulse=random.uniform(0, math.tau),
            speed=0.007 + random.random() * 0.013,
        )

    def resizeEvent(self, event: object) -> None:  # noqa: N802 (Qt override)
        target = max(18, (self.width() * self.height()) // _DENSITY)
        target = min(target, 90)
        while len(self._nodes) < target:
            self._nodes.append(self._make_node())
        del self._nodes[target:]

    def _step(self) -> None:
        w, h = self.width(), self.height()
        for n in self._nodes:
            n.pulse += n.speed
            n.x += n.vx
            n.y += n.vy
            if n.x < -30:
                n.x = w + 30
            elif n.x > w + 30:
                n.x = -30
            if n.y < -30:
                n.y = h + 30
            elif n.y > h + 30:
                n.y = -30
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(qt_theme.BG))

        self._draw_connections(painter)
        self._draw_nodes(painter)

    def _draw_connections(self, painter: QPainter) -> None:
        nodes = self._nodes
        for i in range(len(nodes)):
            a = nodes[i]
            for j in range(i + 1, len(nodes)):
                b = nodes[j]
                dx, dy = a.x - b.x, a.y - b.y
                dist = math.hypot(dx, dy)
                if dist < _MAX_DIST:
                    alpha = (1 - dist / _MAX_DIST) * 0.30
                    pen = QColor(210, 140, 20)
                    pen.setAlphaF(alpha)
                    painter.setPen(pen)
                    painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))

    def _draw_nodes(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        for n in self._nodes:
            scale = 1 + 0.2 * math.sin(n.pulse)
            r = n.r * scale
            glow = n.glow * scale
            center = QPointF(n.x, n.y)

            gradient = QRadialGradient(center, glow)
            c0 = QColor(n.color)
            c0.setAlphaF(min(1.0, n.opacity * 0.7))
            c_mid = QColor(n.color)
            c_mid.setAlphaF(min(1.0, n.opacity * 0.33))
            c_edge = QColor(n.color)
            c_edge.setAlphaF(0.0)
            gradient.setColorAt(0.0, c0)
            gradient.setColorAt(0.45, c_mid)
            gradient.setColorAt(1.0, c_edge)
            painter.setBrush(gradient)
            painter.drawEllipse(center, glow, glow)

            core = QColor(n.color)
            core.setAlphaF(n.opacity)
            painter.setBrush(core)
            painter.drawEllipse(center, r, r)
