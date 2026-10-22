"""Draws the app icon (assets/AppIcon.icns and assets/Typofix.ico) with no image libraries.

A blue squircle with a white check mark over a spell-check squiggle. Run it again after
changing the drawing:  python3 scripts/make_icon.py   (the .icns step needs macOS's iconutil).
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


def render(size):
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
            r, g, b = (TOP[k] + (BOTTOM[k] - TOP[k]) * t for k in range(3))
            for points, width, alpha in ((WAVE, 0.022, 0.55), (CHECK, 0.055, 1.0)):
                cover = max(0.0, min(1.0, 0.5 - _stroke(x, y, points, width) / aa)) * alpha
                r, g, b = (c + (255 - c) * cover for c in (r, g, b))
            row += bytes((int(r), int(g), int(b), int(bg * 255)))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def main():
    assets = os.path.join(ROOT, "assets")
    os.makedirs(assets, exist_ok=True)
    pngs = {s: render(s) for s in (16, 32, 48, 64, 128, 256, 512, 1024)}

    entries = [16, 32, 48, 256]  # .ico with PNG images inside (Windows Vista and later)
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset, table, blobs = 6 + 16 * len(entries), b"", b""
    for s in entries:
        data = pngs[s]
        table += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(os.path.join(assets, "Typofix.ico"), "wb") as f:
        f.write(header + table + blobs)

    with open(os.path.join(assets, "icon.png"), "wb") as f:
        f.write(pngs[256])

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
