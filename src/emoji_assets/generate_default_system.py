"""Render the 50 animal emojis using the Windows system emoji font (Segoe UI Emoji)
into 512x512 transparent-background PNGs.

This produces a local asset folder (default_system/) that the EmojiRenderer can
use instead of painting emoji characters with QPainter at runtime, which avoids
ClearType fringing / halo artifacts on Windows.

Usage:
    python generate_default_system.py
"""

import os
import sys

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QFont, QImage, QPainter
from PyQt5.QtWidgets import QApplication

# Same 50 animal codepoints used everywhere in the project.
CODES = [
    "1f436", "1f431", "1f42d", "1f430", "1f994",
    "1f98a", "1f43b", "1f43c", "1f428", "1f42f",
    "1f981", "1f42e", "1f437", "1f438", "1f435",
    "1f414", "1f427", "1f426", "1f424", "1f986",
    "1f989", "1f987", "1f43a", "1f417", "1f434",
    "1f984", "1f41d", "1f41b", "1f98b", "1f40c",
    "1f41e", "1f422", "1f40d", "1f98e", "1f996",
    "1f995", "1f419", "1f991", "1f990", "1f99e",
    "1f980", "1f421", "1f420", "1f41f", "1f42c",
    "1f433", "1f40a", "1f993", "1f992", "1f9ac",
]

SIZE = 512
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_system")


def render_emoji_png(char: str, path: str):
    """Render a single emoji character to a 512x512 transparent PNG."""
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))

    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

    # Use the Windows color emoji font.  Fall back to platform default if
    # Segoe UI Emoji is unavailable (e.g. on macOS / Linux).
    font = QFont("Segoe UI Emoji", 1)
    # Use pixel size so we fill most of the 512px canvas.
    font.setPixelSize(int(SIZE * 0.85))
    painter.setFont(font)

    # Draw centered
    rect = QRectF(0, 0, SIZE, SIZE)
    painter.drawText(rect, Qt.AlignCenter, char)
    painter.end()

    # Crop to visible content, then re-center on a clean 512x512 canvas so
    # every glyph is consistently sized and centered.
    cropped = _crop_to_content(img)
    if cropped is not None and not cropped.isNull():
        final = QImage(SIZE, SIZE, QImage.Format_ARGB32_Premultiplied)
        final.fill(QColor(0, 0, 0, 0))
        p2 = QPainter(final)
        # Scale cropped glyph to fit with a small margin
        margin = int(SIZE * 0.04)
        avail = SIZE - 2 * margin
        cw, ch = cropped.width(), cropped.height()
        scale = min(avail / max(cw, 1), avail / max(ch, 1))
        sw = int(cw * scale)
        sh = int(ch * scale)
        dx = (SIZE - sw) // 2
        dy = (SIZE - sh) // 2
        target = QRectF(dx, dy, sw, sh)
        p2.drawImage(target, cropped)
        p2.end()
        img = final

    img.save(path, "PNG")


def _crop_to_content(img: QImage):
    """Return the smallest sub-image that contains all non-transparent pixels."""
    w, h = img.width(), img.height()
    min_x, min_y, max_x, max_y = w, h, 0, 0
    for y in range(h):
        for x in range(w):
            if QColor.fromRgba(img.pixel(x, y)).alpha() > 0:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if max_x < min_x or max_y < min_y:
        return None
    return img.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    os.makedirs(OUT_DIR, exist_ok=True)

    for code in CODES:
        char = chr(int(code, 16))
        dest = os.path.join(OUT_DIR, f"{code}.png")
        render_emoji_png(char, dest)
        print(f"  {code}.png")

    print(f"\nDone — {len(CODES)} PNGs saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
