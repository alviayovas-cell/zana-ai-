"""Render assets/zana.ico (the visualizer orb) with Qt. Run: python tools/make_icon.py"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen, QRadialGradient

app = QGuiApplication([])
size = 256
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
c = QPointF(size / 2, size / 2)
bg = QRadialGradient(c, size / 2)
bg.setColorAt(0, QColor("#1a1636")); bg.setColorAt(1, QColor("#06070d"))
p.setPen(Qt.NoPen); p.setBrush(QBrush(bg)); p.drawEllipse(c, 124, 124)
p.setPen(QPen(QColor("#4da3ff"), 8)); p.setBrush(Qt.NoBrush); p.drawEllipse(c, 112, 112)
p.setPen(QPen(QColor("#9b6bff"), 5)); p.drawEllipse(c, 92, 92)
orb = QRadialGradient(QPointF(c.x() - 24, c.y() - 24), 90)
orb.setColorAt(0, QColor("#8fd0ff")); orb.setColorAt(0.55, QColor("#9b6bff")); orb.setColorAt(1, QColor("#1a1636"))
p.setPen(Qt.NoPen); p.setBrush(QBrush(orb)); p.drawEllipse(c, 66, 66)
p.end()
out = Path(__file__).resolve().parent.parent / "assets" / "zana.ico"
print("saved:", img.save(str(out), "ICO"), out)
