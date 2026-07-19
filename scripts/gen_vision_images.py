#!/usr/bin/env python3
"""Generate CC0 vision-benchmark test images for llm-autobench.

Pillow-free: writes minimal valid PNGs using only stdlib (zlib). Two
deterministic, public-domain test images committed to the repo (PUBLIC) so the
benchmark is self-contained and reproducible offline. No private screenshots.

Run:  python scripts/gen_vision_images.py
"""
from __future__ import annotations

import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tasks", "images")
os.makedirs(OUT, exist_ok=True)

# Palette of colors we use
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (220, 40, 40)
BLUE = (40, 80, 220)
GREEN = (40, 180, 60)
ORANGE = (240, 150, 30)
MAGENTA = (220, 40, 220)
GREY = (128, 128, 128)


def _write_png(path: str, w: int, h: int, pixels: list[list[tuple[int, int, int]]]) -> None:
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0 (none) per scanline
        for x in range(w):
            r, g, b = pixels[y][x]
            raw += bytes((r, g, b))
    compressor = zlib.compressobj(9)
    compressed = compressor.compress(bytes(raw)) + compressor.flush()
    # CRC helper
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit, color type 2 (RGB)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", compressed))
        f.write(chunk(b"IEND", b""))


def _blank(w, h, color=WHITE):
    return [[color for _ in range(w)] for _ in range(h)]


def _rect(px, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(len(px), y1)):
        for x in range(max(0, x0), min(len(px[0]), x1)):
            px[y][x] = color


def _text(px, x0, y0, text, color, scale=1):
    """Crude 5x7 bitmap font for A-Z, 0-9, '-'. Draws at scale px per cell."""
    FONT = {
        'A': ["01110","10001","10011","11111","10001","10001","10001"],
        'B': ["11110","10001","11110","10001","10001","10001","11110"],
        'C': ["01110","10001","10000","10000","10000","10001","01110"],
        'D': ["11110","10001","10001","10001","10001","10001","11110"],
        'E': ["11111","10000","11110","10000","10000","10000","11111"],
        'F': ["11111","10000","11110","10000","10000","10000","10000"],
        'G': ["01110","10001","10000","10111","10001","10001","01111"],
        'H': ["10001","10001","11111","10001","10001","10001","10001"],
        'I': ["11111","00100","00100","00100","00100","00100","11111"],
        'J': ["00111","00010","00010","00010","00010","10010","01100"],
        'K': ["10001","10010","10100","11000","10100","10010","10001"],
        'L': ["10000","10000","10000","10000","10000","10000","11111"],
        'M': ["10001","11011","10101","10101","10001","10001","10001"],
        'N': ["10001","11001","10101","10011","10001","10001","10001"],
        'O': ["01110","10001","10001","10001","10001","10001","01110"],
        'P': ["11110","10001","10001","11110","10000","10000","10000"],
        'Q': ["01110","10001","10001","10001","10101","10010","01101"],
        'R': ["11110","10001","10001","11110","10100","10010","10001"],
        'S': ["01111","10000","10000","01110","00001","00001","11110"],
        'T': ["11111","00100","00100","00100","00100","00100","00100"],
        'U': ["10001","10001","10001","10001","10001","10001","01110"],
        'V': ["10001","10001","10001","10001","10001","01010","00100"],
        'W': ["10001","10001","10001","10101","10101","11011","10001"],
        'X': ["10001","10001","01010","00100","01010","10001","10001"],
        'Y': ["10001","10001","01010","00100","00100","00100","00100"],
        'Z': ["11111","00001","00010","00100","01000","10000","11111"],
        '0': ["01110","10011","10101","10101","11001","11001","01110"],
        '1': ["00100","01100","00100","00100","00100","00100","01110"],
        '2': ["01110","10001","00001","00010","00100","01000","11111"],
        '3': ["11110","00001","00001","01110","00001","00001","11110"],
        '4': ["00010","00110","01010","10010","11111","00010","00010"],
        '5': ["11111","10000","11110","00001","00001","10001","01110"],
        '6': ["00110","01000","10000","11110","10001","10001","01110"],
        '7': ["11111","00001","00010","00100","01000","01000","01000"],
        '8': ["01110","10001","10001","01110","10001","10001","01110"],
        '9': ["01110","10001","10001","01111","00001","00010","01100"],
        '-': ["00000","00000","00000","11111","00000","00000","00000"],
    }
    cx = x0
    for ch in text.upper():
        glyph = FONT.get(ch, FONT['-'])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == '1':
                    _rect(px, cx + gx * scale, y0 + gy * scale,
                          cx + (gx + 1) * scale, y0 + (gy + 1) * scale, color)
        cx += (5 + 1) * scale  # 1 cell spacing


def ocr_card() -> None:
    px = _blank(400, 240)
    _rect(px, 20, 20, 120, 120, RED)
    _text(px, 150, 40, "HELLO", BLACK, scale=4)
    _text(px, 150, 120, "123", BLACK, scale=4)
    _text(px, 20, 170, "READ-THE-TEXT", BLACK, scale=2)
    _write_png(os.path.join(OUT, "ocr_card.png"), 400, 240, px)


def shapes() -> None:
    px = _blank(400, 300)
    # blue circle (filled ellipse approx)
    cx, cy, r = 95, 95, 65
    for y in range(400):
        for x in range(400):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                px[y][x] = BLUE
    _rect(px, 220, 40, 360, 170, GREEN)
    # orange triangle
    for y in range(180, 261):
        t = (y - 180) / (260 - 180)
        half = int(80 * t)
        mid = 140
        _rect(px, mid - half, y, mid + half, y + 1, ORANGE)
    _text(px, 20, 275, "THREE SHAPES ABOVE", BLACK, scale=2)
    _write_png(os.path.join(OUT, "shapes.png"), 400, 300, px)


def gradient_png() -> None:
    """Baseline (non-progressive) image stand-in: a grey gradient + magenta text.
    Saved as PNG so it needs no JPEG encoder; used to show non-progressive
    ingestion works (contrast with the progressive-JPEG failure mode)."""
    w, h = 320, 200
    px = _blank(w, h)
    for x in range(w):
        s = int(255 * (x / w))
        for y in range(h):
            px[y][x] = (s, s, s)
    _text(px, 10, 10, "GRADIENT-TEST", MAGENTA, scale=2)
    _write_png(os.path.join(OUT, "gradient_baseline.png"), w, h, px)


if __name__ == "__main__":
    ocr_card()
    shapes()
    gradient_png()
    print("wrote:", sorted(os.listdir(OUT)))
