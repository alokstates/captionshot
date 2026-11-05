"""Draws assets/header.png, the README header. The caption bar in it comes from the app's own compose().

Run from the repo root, using the build environment:
    .venv-build\\Scripts\\python.exe assets\\make_header.py     (Windows)
    .venv-build/bin/python assets/make_header.py              (macOS)
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QApplication

import captionshot as cs

W, H = 1920, 640                     # final size
S = 2                                # drawn at double size, then scaled down for clean edges
BLUE = QColor(cs.ACCENT)             # the icon's blue
WHITE = QColor("#ffffff")
INK = QColor("#1c2733")
MUTED = QColor("#7b8794")
RULE = QColor("#e7ebf0")
RED = QColor(cs.SWATCHES[0])
YELLOW = QColor(cs.SWATCHES[2])
GREEN = QColor(cs.SWATCHES[3])


def font(px, bold=False):
    f = QFont("Mukta")
    f.setPixelSize(int(px))
    f.setBold(bold)
    return f


def rounded(p, rect, r, color):
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(rect, r, r)


def dashes(p, x, y, w, h, thick, color):
    """The selection marks from the app icon, drawn as the outline of a rectangle."""
    pen = QPen(color, thick, Qt.SolidLine, Qt.RoundCap)
    pen.setDashPattern([3.2, 1.9])
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(x, y, w, h), thick * 1.1, thick * 1.1)


def mock_screenshot(w, h):
    """A made-up invoice page: something worth annotating, with no real data in it."""
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(WHITE)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    m = 44 * S
    p.setFont(font(34 * S, True))
    p.setPen(INK)
    p.drawText(QPointF(m, 66 * S), "Invoice #2048")
    p.setFont(font(21 * S))
    p.setPen(MUTED)
    p.drawText(QPointF(m, 100 * S), "Paid by bank transfer")
    y = 128 * S
    for name, amount in (("Design work", "₹18,000"), ("Hosting, 1 year", "₹6,500")):
        p.setPen(QPen(RULE, S))
        p.drawLine(QPointF(m, y), QPointF(w - m, y))
        p.setFont(font(24 * S))
        p.setPen(INK)
        p.drawText(QPointF(m, y + 40 * S), name)
        p.drawText(QRectF(m, y + 8 * S, w - 2 * m, 44 * S), Qt.AlignRight | Qt.AlignVCenter, amount)
        y += 60 * S
    p.setPen(QPen(RULE, S))
    p.drawLine(QPointF(m, y), QPointF(w - m, y))

    # the marker tool over the total
    rounded(p, QRectF(m - 8 * S, y + 12 * S, 318 * S, 46 * S), 6 * S, QColor(253, 216, 53, 150))
    p.setFont(font(27 * S, True))
    p.setPen(INK)
    p.drawText(QPointF(m, y + 45 * S), "Total paid: ₹24,500")

    # the rectangle tool around the status, and the arrow tool pointing at it
    box = QRectF(w - m - 134 * S, y + 12 * S, 134 * S, 46 * S)
    p.setFont(font(23 * S, True))
    p.setPen(GREEN)
    p.drawText(box, Qt.AlignCenter, "PAID")
    p.setPen(QPen(RED, 4.5 * S))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(box, 6 * S, 6 * S)
    tip = QPointF(box.left() - 8 * S, box.center().y())
    tail = QPointF(tip.x() - 150 * S, tip.y() - 62 * S)
    arrow = QPainterPath(tail)
    arrow.quadTo(QPointF(tip.x() - 90 * S, tip.y() - 4 * S), QPointF(tip.x() - 16 * S, tip.y()))
    p.setPen(QPen(RED, 5 * S, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawPath(arrow)
    p.setPen(Qt.NoPen)
    p.setBrush(RED)
    p.drawPolygon(QPolygonF([tip, QPointF(tip.x() - 22 * S, tip.y() - 12 * S), QPointF(tip.x() - 22 * S, tip.y() + 12 * S)]))
    p.end()
    return img


def main():
    app = QApplication(sys.argv)
    cs.load_fonts()

    canvas = QImage(W * S, H * S, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)

    # Full-width blue with rounded corners, so it sits well on GitHub's light and dark themes.
    rounded(p, QRectF(0, 0, W * S, H * S), 28 * S, BLUE)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, W * S, H * S), 28 * S, 28 * S)
    p.setClipPath(clip)

    # The icon's dashed selection, large and faint, behind the wordmark.
    dashes(p, -90 * S, 72 * S, 960 * S, 496 * S, 26 * S, QColor(255, 255, 255, 30))

    # Wordmark
    x = 96 * S
    p.setPen(WHITE)
    p.setFont(font(112 * S, True))
    p.drawText(QPointF(x, 306 * S), "CaptionShot")
    rounded(p, QRectF(x + 3 * S, 334 * S, 186 * S, 14 * S), 7 * S, WHITE)     # the icon's caption bar
    p.setPen(WHITE)
    p.setFont(font(40 * S))
    p.drawText(QPointF(x, 416 * S), "Screenshots that explain themselves.")
    p.setFont(font(27 * S))
    p.setPen(QColor(255, 255, 255, 215))
    p.drawText(QPointF(x, 466 * S), "Free and open source  ·  Windows and macOS")

    # The "screenshot": mock page + the app's real caption bar
    card_w = 740 * S
    shot = mock_screenshot(card_w, 372 * S)
    final = cs.compose(shot, "भुगतान मिल गया, रसीद भेज दी", "05 Nov 2026, 10:42  ·  Invoice #2048", float(S), 30)
    cx, cy = 1088 * S, (H * S - final.height()) // 2

    # Soft shadow
    for i in range(22, 0, -1):
        rounded(p, QRectF(cx - i * S, cy - i * S + 16 * S, card_w + 2 * i * S, final.height() + 2 * i * S),
                (16 + i) * S, QColor(0, 40, 110, 5))

    card = QPainterPath()
    card.addRoundedRect(QRectF(cx, cy, card_w, final.height()), 16 * S, 16 * S)
    p.save()
    p.setClipPath(card, Qt.IntersectClip)
    p.drawImage(cx, cy, final)
    p.restore()
    p.end()

    out = os.path.join(ROOT, "assets", "header.png")
    canvas.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).save(out, "PNG")
    print("wrote", out)
    return app


if __name__ == "__main__":
    main()
