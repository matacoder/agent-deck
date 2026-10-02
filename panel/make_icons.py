#!/usr/bin/env python3
"""Render the panel's app icons (">_" prompt) as PNGs with pure Python (no Pillow)."""
import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
TOP, BOTTOM = (0x2E, 0x2E, 0x34), (0x15, 0x15, 0x18)
FG = (0xE0, 0x7A, 0x55)
# capsule strokes in unit coordinates: chevron ">" and underscore "_"
STROKES = [((0.28, 0.33), (0.46, 0.50)), ((0.46, 0.50), (0.28, 0.67)), ((0.54, 0.67), (0.74, 0.67))]
HALF_WIDTH = 0.048


def seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size, ss):
    rows = []
    for y in range(size):
        row = bytearray([0])  # PNG filter type 0
        bg = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * y / (size - 1)) for i in range(3))
        for x in range(size):
            cover = 0
            for sy in range(ss):
                for sx in range(ss):
                    u, v = (x + (sx + 0.5) / ss) / size, (y + (sy + 0.5) / ss) / size
                    if min(seg_dist(u, v, a, b) for a, b in STROKES) <= HALF_WIDTH:
                        cover += 1
            k = cover / (ss * ss)
            row += bytes(int(bg[i] + (FG[i] - bg[i]) * k) for i in range(3))
        rows.append(bytes(row))
    return b"".join(rows)


def write_png(path, size, raw):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    for size, ss in ((180, 4), (192, 4), (512, 2)):
        write_png(os.path.join(HERE, f"icon-{size}.png"), size, render(size, ss))
        print(f"icon-{size}.png")
