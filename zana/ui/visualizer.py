"""Animated emerald AI orb: thin glowing rings orbiting a dark central sphere.

The look follows the state: calm and slow when idle, brighter and pulsing while
listening, faster rings while thinking, rings that react to speech while speaking,
and a dimmed orb when paused. Parameters ease toward the target so every change of
state is smooth. The timer only runs while the widget is visible.
"""

import math
import random
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QPainter, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from . import theme


class VisualizerState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    PAUSED = "paused"


@dataclass
class _Look:
    speed: float       # ring rotation speed multiplier
    bright: float      # overall ring/glow brightness 0..1
    pulse: float       # amplitude of the slow breathing/pulse
    pulse_hz: float
    react: float       # how strongly rings follow the audio level


_LOOKS = {
    VisualizerState.IDLE: _Look(0.35, 0.55, 0.020, 0.25, 0.0),
    VisualizerState.LISTENING: _Look(0.80, 0.92, 0.045, 1.10, 0.9),
    VisualizerState.THINKING: _Look(2.60, 0.85, 0.020, 0.50, 0.0),
    VisualizerState.SPEAKING: _Look(1.10, 1.00, 0.030, 0.80, 1.4),
    VisualizerState.PAUSED: _Look(0.06, 0.22, 0.008, 0.15, 0.0),
}

# (relative radius, tilt degrees, thickness, direction, phase offset)
_RINGS = (
    (1.00, 18, 1.4, 1, 0.0),
    (0.90, -34, 1.2, -1, 1.7),
    (0.80, 62, 1.1, 1, 3.1),
    (0.70, -12, 1.0, -1, 4.4),
    (0.60, 80, 0.9, 1, 5.6),
)
_SQUASH = 0.34  # ring ellipse height / width: gives the 3D orbit look
_INTERVAL_MS = {  # frame interval per state
    VisualizerState.IDLE: 50, VisualizerState.PAUSED: 100,
    VisualizerState.LISTENING: 40, VisualizerState.THINKING: 40, VisualizerState.SPEAKING: 40,
}


class VoiceVisualizer(QWidget):
    """Driven by a state and an audio level in 0..1.

    Call ``set_level`` with real microphone/TTS amplitude. While ``simulate_levels``
    is True a synthetic level is generated for LISTENING/SPEAKING (UI previews).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.simulate_levels = True
        self._state = VisualizerState.IDLE
        self._level = 0.0
        self._target = 0.0
        self._phase = 0.0      # accumulates "ring time" (speed-weighted)
        self._clock_t = 0.0    # real seconds, for pulses
        # smoothed copies of the current look
        look = _LOOKS[VisualizerState.IDLE]
        self._speed, self._bright = look.speed, look.bright
        self._pulse, self._pulse_hz, self._react = look.pulse, look.pulse_hz, look.react
        rnd = random.Random(7)
        self._sparks = [(rnd.random() * math.tau, rnd.randint(0, len(_RINGS) - 1),
                         rnd.uniform(0.6, 1.4)) for _ in range(7)]
        self._clock = QElapsedTimer()
        self._clock.start()
        self._last_ms = 0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.CoarseTimer)
        self._timer.timeout.connect(self._tick)
        self._cache: OrderedDict = OrderedDict()   # pre-rendered glow / sphere layers
        self._timer.start(_INTERVAL_MS[VisualizerState.IDLE])

    # -- public API ---------------------------------------------------------
    @property
    def state(self) -> VisualizerState:
        return self._state

    def set_state(self, state: VisualizerState) -> None:
        self._state = state
        # Slow states move slowly, so they need far fewer frames (saves CPU).
        self._timer.setInterval(_INTERVAL_MS.get(state, 33))

    def set_level(self, level: float) -> None:
        self._target = max(0.0, min(1.0, level))

    # -- run only while visible (no CPU use in the tray) ------------------------
    def showEvent(self, e) -> None:
        self._last_ms = self._clock.elapsed()
        if not self._timer.isActive():
            self._timer.start(_INTERVAL_MS.get(self._state, 33))
        super().showEvent(e)

    def hideEvent(self, e) -> None:
        self._timer.stop()
        super().hideEvent(e)

    # -- animation ----------------------------------------------------------
    def _tick(self) -> None:
        now = self._clock.elapsed()
        dt = min(max((now - self._last_ms) / 1000.0, 0.0), 0.1)
        self._last_ms = now
        self._clock_t += dt
        look = _LOOKS[self._state]
        k = min(1.0, dt * 4.0)  # easing: states blend over ~0.25 s
        self._speed += (look.speed - self._speed) * k
        self._bright += (look.bright - self._bright) * k
        self._pulse += (look.pulse - self._pulse) * k
        self._pulse_hz += (look.pulse_hz - self._pulse_hz) * k
        self._react += (look.react - self._react) * k
        self._phase += dt * self._speed

        if self.simulate_levels:
            t = self._clock_t
            if self._state in (VisualizerState.LISTENING, VisualizerState.SPEAKING):
                self._target = 0.30 + 0.35 * abs(math.sin(t * 2.3) * math.sin(t * 0.7 + 1))
            elif self._state is VisualizerState.THINKING:
                self._target = 0.15
            elif self._state is VisualizerState.PAUSED:
                self._target = 0.0
            else:
                self._target = 0.04 + 0.02 * math.sin(t * 1.4)
        self._level += (self._target - self._level) * min(1.0, dt * 9)
        self.update()

    # -- painting -----------------------------------------------------------
    @staticmethod
    def _col(hex_color: str, alpha: float) -> QColor:
        c = QColor(hex_color)
        c.setAlpha(max(0, min(255, int(alpha * 255))))
        return c

    # -- cached layers: the glow and the sphere barely change between frames ------------
    def _cached(self, key, make) -> QPixmap:
        px = self._cache.get(key)
        if px is None:
            px = make()
            self._cache[key] = px
            while len(self._cache) > 12:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
        return px

    def _draw_glow(self, p: QPainter, c: QPointF, r: float, level: float) -> None:
        """Soft ambient light. A smooth gradient, so it is rendered small and scaled up."""
        side = max(8, int(2 * r * 1.15 * 0.30))
        bq, lq = round(self._bright * 24), round(level * 12)
        key = ("glow", side, bq, lq)

        def make() -> QPixmap:
            px = QPixmap(side, side)
            px.fill(Qt.transparent)
            q = QPainter(px)
            q.setRenderHint(QPainter.Antialiasing)
            ctr, rad = QPointF(side / 2, side / 2), side / 2
            bright, lv = bq / 24, lq / 12
            g = QRadialGradient(ctr, rad)
            g.setColorAt(0.0, self._col(theme.GREEN, 0.20 * bright + 0.10 * lv))
            g.setColorAt(0.45, self._col(theme.GREEN, 0.07 * bright))
            g.setColorAt(1.0, self._col(theme.GREEN, 0.0))
            q.setPen(Qt.NoPen)
            q.setBrush(QBrush(g))
            q.drawEllipse(ctr, rad, rad)
            q.end()
            return px

        px = self._cached(key, make)
        d = 2 * r * 1.15
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF(c.x() - d / 2, c.y() - d / 2, d, d), px, QRectF(px.rect()))

    def _draw_sphere(self, p: QPainter, c: QPointF, core_r: float) -> None:
        """Dark central sphere with a faint emerald rim light and a soft highlight."""
        cr = round(core_r * 2) / 2
        side = int(cr * 2) + 6
        dpr = self.devicePixelRatioF()
        bq = round(self._bright * 24)
        key = ("sphere", cr, bq, dpr)

        def make() -> QPixmap:
            px = QPixmap(int(side * dpr), int(side * dpr))
            px.setDevicePixelRatio(dpr)
            px.fill(Qt.transparent)
            q = QPainter(px)
            q.setRenderHint(QPainter.Antialiasing)
            ctr, bright = QPointF(side / 2, side / 2), bq / 24
            body = QRadialGradient(QPointF(ctr.x() - cr * 0.30, ctr.y() - cr * 0.35), cr * 1.35)
            body.setColorAt(0.0, QColor("#16241E"))
            body.setColorAt(0.55, QColor("#07100C"))
            body.setColorAt(1.0, QColor("#020504"))
            q.setPen(Qt.NoPen)
            q.setBrush(QBrush(body))
            q.drawEllipse(ctr, cr, cr)
            rim = QRadialGradient(ctr, cr)
            rim.setColorAt(0.80, self._col(theme.GREEN, 0.0))
            rim.setColorAt(1.0, self._col(theme.GREEN, 0.38 * bright))
            q.setBrush(QBrush(rim))
            q.drawEllipse(ctr, cr, cr)
            spec = QRadialGradient(QPointF(ctr.x() - cr * 0.35, ctr.y() - cr * 0.42), cr * 0.55)
            spec.setColorAt(0.0, self._col(theme.MINT, 0.17 * bright))
            spec.setColorAt(1.0, self._col(theme.MINT, 0.0))
            q.setBrush(QBrush(spec))
            q.drawEllipse(ctr, cr, cr)
            q.end()
            return px

        px = self._cached(key, make)
        p.drawPixmap(QPointF(c.x() - side / 2, c.y() - side / 2), px)

    def _draw_ring(self, p: QPainter, c: QPointF, r: float, ring, front: bool) -> None:
        rel, tilt, thick, direction, offset = ring
        pulse = 1.0 + self._pulse * math.sin(self._clock_t * math.tau * self._pulse_hz + offset)
        scale = pulse * (1.0 + 0.05 * self._level * self._react)
        rx = r * rel * scale
        ry = rx * _SQUASH
        p.save()
        p.translate(c)
        p.rotate(tilt)
        # Each ring is drawn as two half-arcs: the upper half behind the sphere, the lower in front.
        rect = QRectF(-rx, -ry, 2 * rx, 2 * ry)
        start = (180 if front else 0) * 16
        angle = math.degrees(self._phase * direction * 1.2 + offset)
        grad = QConicalGradient(QPointF(0, 0), angle)
        head = self._col(theme.GLOW, self._bright)
        tail = self._col(theme.GREEN, self._bright * 0.10)
        grad.setColorAt(0.0, head)
        grad.setColorAt(0.22, self._col(theme.GREEN, self._bright * 0.55))
        grad.setColorAt(0.6, tail)
        grad.setColorAt(1.0, head)
        # soft halo under the crisp line
        halo_c = QColor(theme.GREEN)
        halo_c.setAlpha(int(34 * self._bright))
        p.setPen(QPen(halo_c, thick * 3.4))
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, start, 180 * 16)
        p.setPen(QPen(QBrush(grad), thick, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, start, 180 * 16)
        p.restore()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        r = min(w, h) / 2 * 0.90
        level = self._level * self._react
        core_r = r * (0.36 + 0.025 * level + 0.01 * math.sin(self._clock_t * math.tau * self._pulse_hz))

        self._draw_glow(p, c, r, level)

        for ring in _RINGS:                       # back halves
            self._draw_ring(p, c, r, ring, front=False)

        self._draw_sphere(p, c, core_r)

        for ring in _RINGS:                       # front halves pass over the sphere
            self._draw_ring(p, c, r, ring, front=True)

        # a few tiny sparks riding the rings
        p.setPen(Qt.NoPen)
        for base, idx, speed in self._sparks:
            rel, tilt, _t, direction, offset = _RINGS[idx]
            a = base + self._phase * direction * 1.2 * speed
            rx = r * rel
            x, y = rx * math.cos(a), rx * _SQUASH * math.sin(a)
            tr = math.radians(tilt)
            px = c.x() + x * math.cos(tr) - y * math.sin(tr)
            py = c.y() + x * math.sin(tr) + y * math.cos(tr)
            behind = math.sin(a) < 0
            alpha = self._bright * (0.35 if behind else 0.95)
            p.setBrush(self._col(theme.MINT, alpha))
            p.drawEllipse(QPointF(px, py), 1.7, 1.7)
            p.setBrush(self._col(theme.GREEN, alpha * 0.25))
            p.drawEllipse(QPointF(px, py), 4.5, 4.5)
        p.end()
