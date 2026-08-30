"""Generate VEDA Anywhere extension icons (stdlib only, no Pillow).

Reproduces the VEDA favicon mark - a cyan "V" over a dark hard-edged plate with
the small amber status square - at the sizes Chrome needs (16/32/48/128).

    python extension/tools/make_icons.py

Deterministic: re-running produces byte-identical files.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "icons"

BG = (0x0A, 0x0C, 0x0F, 255)
FRAME = (0x23, 0x29, 0x35, 255)
CYAN = (0x45, 0xC8, 0xE8, 255)
AMBER = (0xFF, 0xB0, 0x20, 255)

SS = 4  # supersampling factor


def _seg_distance(px: float, py: float, ax: float, ay: float,
                  bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _blend(base, top):
    ba, ta = base[3] / 255, top[3] / 255
    out_a = ta + ba * (1 - ta)
    if out_a == 0:
        return (0, 0, 0, 0)
    out = tuple(
        round((top[i] * ta + base[i] * ba * (1 - ta)) / out_a) for i in range(3)
    )
    return (out[0], out[1], out[2], round(out_a * 255))


def render(size: int) -> bytes:
    hi = size * SS
    s = hi / 32.0  # scale from the 32-unit design grid
    px = [[BG for _ in range(hi)] for _ in range(hi)]

    # Border frame: 3..29 with ~1px stroke on the design grid.
    f0, f1 = 3.0 * s, 29.0 * s
    stroke = max(1.0, 1.0 * s)
    # V stroke geometry.
    v = [((7.0 * s, 8.0 * s), (16.0 * s, 24.0 * s)),
         ((16.0 * s, 24.0 * s), (25.0 * s, 8.0 * s))]
    v_half = (3.0 * s) / 2.0
    # Amber square 14..18 x 6..10.
    a0x, a1x, a0y, a1y = 14.0 * s, 18.0 * s, 6.0 * s, 10.0 * s

    for y in range(hi):
        fy = y + 0.5
        for x in range(hi):
            fx = x + 0.5
            c = BG
            on_frame = (
                (f0 - stroke <= fx <= f1 + stroke and f0 - stroke <= fy <= f1 + stroke)
                and not (f0 + stroke <= fx <= f1 - stroke and f0 + stroke <= fy <= f1 - stroke)
            )
            if on_frame:
                c = _blend(c, FRAME)
            if a0x <= fx <= a1x and a0y <= fy <= a1y:
                c = _blend(c, AMBER)
            d = min(_seg_distance(fx, fy, *seg[0], *seg[1]) for seg in v)
            if d <= v_half:
                aa = max(0.0, min(1.0, (v_half - d + 0.5)))
                c = _blend(c, (CYAN[0], CYAN[1], CYAN[2], round(255 * aa)))
            px[y][x] = c

    # Box downsample SS x SS -> 1.
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter: none
        for x in range(size):
            r = g = b = a = 0
            for dy in range(SS):
                for dx in range(SS):
                    p = px[y * SS + dy][x * SS + dx]
                    r += p[0]; g += p[1]; b += p[2]; a += p[3]
            n = SS * SS
            raw += bytes((r // n, g // n, b // n, a // n))
    return bytes(raw)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: Path, size: int, raw: bytes) -> None:
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", ihdr)
           + _chunk(b"IDAT", zlib.compress(raw, 9))
           + _chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        write_png(OUT / f"icon-{size}.png", size, render(size))
        print("wrote", OUT / f"icon-{size}.png")


if __name__ == "__main__":
    main()
