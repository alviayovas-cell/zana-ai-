"""QStackedWidget whose pages fade in when you switch screens."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget


class FadeStack(QStackedWidget):
    DURATION_MS = 190

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim: QPropertyAnimation | None = None
        self._fading: QWidget | None = None

    def setCurrentIndex(self, index: int) -> None:  # the index changes immediately; only the fade is animated
        previous = self.currentIndex()
        super().setCurrentIndex(index)
        if index == previous or not self.isVisible():
            return
        self._finish_fade()
        page = self.currentWidget()
        if page is None:
            return
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(self.DURATION_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(self._finish_fade)
        self._anim, self._fading = anim, page
        anim.start()

    def _finish_fade(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if self._fading is not None:
            self._fading.setGraphicsEffect(None)  # full-quality rendering once settled
            self._fading = None
