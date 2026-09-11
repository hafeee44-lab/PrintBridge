"""A tiny PNG writer, so the printer shows a real icon on the phone
instead of a generic placeholder. No image libraries needed."""

from __future__ import annotations

import struct
import zlib

BG = (31, 41, 51)
BODY = (229, 231, 235)
PAPER = (255, 255, 255)
ACCENT = (56, 189, 172)
SHADOW = (156, 163, 175)


def _rect(px, size, x0, y0, x1, y1, colour, radius=0):
    for y in range(max(0, int(y0)), min(size, int(y1))):
        for x in range(max(0, int(x0)), min(size, int(x1))):
            if radius:
                cx = min(max(x, x0 + radius), x1 - radius)
                cy = min(max(y, y0 + radius), y1 - radius)
                if (x - cx) ** 2 + (y - cy) ** 2 > radius * radius:
                    continue
            px[y][x] = colour


def printer_png(size=128):
    s = float(size)
    px = [[BG for _ in range(size)] for _ in range(size)]
    _rect(px, size, 0, 0, size, size, BG, radius=s * 0.22)

    # sheet coming out of the top
    _rect(px, size, s * 0.30, s * 0.18, s * 0.70, s * 0.42, PAPER)
    _rect(px, size, s * 0.36, s * 0.24, s * 0.64, s * 0.26, SHADOW)
    _rect(px, size, s * 0.36, s * 0.29, s * 0.60, s * 0.31, SHADOW)

    # body
    _rect(px, size, s * 0.18, s * 0.40, s * 0.82, s * 0.68, BODY,
          radius=s * 0.05)
    # output tray
    _rect(px, size, s * 0.28, s * 0.66, s * 0.72, s * 0.82, PAPER,
          radius=s * 0.03)
    # status light
    _rect(px, size, s * 0.66, s * 0.45, s * 0.74, s * 0.49, ACCENT,
          radius=s * 0.02)
    return _encode(px, size)


def _encode(px, size):
    raw = bytearray()
    for row in px:
        raw.append(0)
        for r, g, b in row:
            raw += bytes((r, g, b))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


_cache = {}


def get(size):
    if size not in _cache:
        _cache[size] = printer_png(size)
    return _cache[size]
