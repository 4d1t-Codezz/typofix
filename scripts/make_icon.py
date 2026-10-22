"""Draws the icons with no image libraries.

The app icon is a blue squircle with a white check mark over a spell-check squiggle
(assets/AppIcon.icns, assets/icon.png). The app itself also needs, in typofix/data: a small icon
for its window, a black "template" check for the Mac menu bar, and blue and grey (paused) .ico
files for the Windows tray. Run it again after changing the drawing:
    python3 scripts/make_icon.py   (the .icns step needs macOS's iconutil)
"""

import math
import os
import shutil
import struct
import subprocess
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP, BOTTOM = (90, 150, 255), (88, 86, 214)
GREY_TOP, GREY_BOTTOM = (150, 150, 150), (110, 110, 115)


def _segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _squircle(x, y):
    """Signed distance-ish value: negative inside a rounded square filling 0.1..0.9."""
    qx, qy = abs(x - 0.5) - 0.4 + 0.18, abs(y - 0.5) - 0.4 + 0.18
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - 0.18


CHECK = [(0.30, 0.46), (0.44, 0.60), (0.71, 0.32)]
WAVE = [(0.28 + i * 0.44 / 24, 0.73 + 0.025 * math.sin(i / 24 * 4 * math.pi)) for i in range(25)]


def _stroke(x, y, points, width):
    return min(_segment(x, y, *points[i], *points[i + 1]) for i in range(len(points) - 1)) - width


def _png(size, rows):
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def render_template(size):
    """Just the check and squiggle in black on transparent; macOS recolors it for the menu bar."""
    rows = []
    aa = 1.0 / size
    for j in range(size):
        y = (j + 0.5) / size * 0.8 + 0.1
        row = bytearray([0])
        for i in range(size):
            x = (i + 0.5) / size * 0.8 + 0.1
            cover = 0.0
            for points, width, alpha in ((WAVE, 0.035, 0.8), (CHECK, 0.07, 1.0)):
                cover = max(cover, max(0.0, min(1.0, 0.5 - _stroke(x, y, points, width) / (aa * 0.8))) * alpha)
            row += bytes((0, 0, 0, int(cover * 255)))
        rows.append(bytes(row))
    return _png(size, rows)


def render(size, top=TOP, bottom=BOTTOM):
    rows = []
    aa = 1.0 / size
    for j in range(size):
        y = (j + 0.5) / size
        row = bytearray([0])
        for i in range(size):
            x = (i + 0.5) / size
            bg = max(0.0, min(1.0, 0.5 - _squircle(x, y) / aa))
            if bg <= 0:
                row += b"\0\0\0\0"
                continue
            t = (y - 0.1) / 0.8
            r, g, b = (top[k] + (bottom[k] - top[k]) * t for k in range(3))
            for points, width, alpha in ((WAVE, 0.022, 0.55), (CHECK, 0.055, 1.0)):
                cover = max(0.0, min(1.0, 0.5 - _stroke(x, y, points, width) / aa)) * alpha
                r, g, b = (c + (255 - c) * cover for c in (r, g, b))
            row += bytes((int(r), int(g), int(b), int(bg * 255)))
        rows.append(bytes(row))
    return _png(size, rows)


def write_ico(path, pngs, sizes):
    """An .ico with PNG images inside (Windows Vista and later)."""
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset, table, blobs = 6 + 16 * len(sizes), b"", b""
    for s in sizes:
        data = pngs[s]
        table += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + table + blobs)


def main():
    assets = os.path.join(ROOT, "assets")
    os.makedirs(assets, exist_ok=True)
    pngs = {s: render(s) for s in (16, 32, 48, 64, 128, 256, 512, 1024)}

    write_ico(os.path.join(assets, "Typofix.ico"), pngs, [16, 32, 48, 256])
    with open(os.path.join(assets, "icon.png"), "wb") as f:
        f.write(pngs[256])

    data = os.path.join(ROOT, "typofix", "data")
    write_ico(os.path.join(data, "Typofix.ico"), pngs, [16, 32, 48])
    grey = {s: render(s, GREY_TOP, GREY_BOTTOM) for s in (16, 32, 48)}
    write_ico(os.path.join(data, "TypofixPaused.ico"), grey, [16, 32, 48])
    with open(os.path.join(data, "icon.png"), "wb") as f:
        f.write(pngs[64])
    with open(os.path.join(data, "menubar.png"), "wb") as f:
        f.write(render_template(36))

    if shutil.which("iconutil"):
        tmp = tempfile.mkdtemp()
        iconset = os.path.join(tmp, "AppIcon.iconset")
        os.makedirs(iconset)
        for s in (16, 32, 128, 256, 512):
            with open(os.path.join(iconset, f"icon_{s}x{s}.png"), "wb") as f:
                f.write(pngs[s])
            with open(os.path.join(iconset, f"icon_{s}x{s}@2x.png"), "wb") as f:
                f.write(pngs[s * 2])
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(assets, "AppIcon.icns")], check=True)
        shutil.rmtree(tmp)
    print("Wrote icons to", assets)


if __name__ == "__main__":
    main()
