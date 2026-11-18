"""Regenerate raster app icons from web-app/public/favicon.svg.

    uv run python scripts/build_icons.py

Outputs (all with a real alpha channel, so the rounded corners stay transparent):
  - dashb/assets/app.ico                    16-256 px PNG frames (exe/taskbar icon)
  - web-app/public/icons/icon-192.png       PWA manifest icon
  - web-app/public/icons/icon-512.png       PWA manifest icon
  - web-app/public/icons/apple-touch-icon.png
        180 px, full-bleed square on purpose: iOS applies its own corner mask
        and renders transparent pixels as black.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SVG = ROOT / "web-app" / "public" / "favicon.svg"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
APPLE_TOUCH_BACKGROUND = "#262c32"  # favicon.svg's rounded-rect fill


def render(renderer: QSvgRenderer, size: int, background: str | None = None) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(background) if background else Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def write_ico(path: Path, frames: list[tuple[int, bytes]]) -> None:
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries, blobs = b"", b""
    for size, blob in frames:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    path.write_bytes(header + entries + blobs)


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - QPainter needs a GUI app
    renderer = QSvgRenderer(str(SOURCE_SVG))
    if not renderer.isValid():
        print(f"Could not load {SOURCE_SVG}", file=sys.stderr)
        return 1

    write_ico(
        ROOT / "dashb" / "assets" / "app.ico",
        [(size, png_bytes(render(renderer, size))) for size in ICO_SIZES],
    )

    icons = ROOT / "web-app" / "public" / "icons"
    render(renderer, 192).save(str(icons / "icon-192.png"))
    render(renderer, 512).save(str(icons / "icon-512.png"))
    render(renderer, 180, APPLE_TOUCH_BACKGROUND).save(
        str(icons / "apple-touch-icon.png")
    )
    print("Icons written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
