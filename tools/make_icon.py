"""Generate app/fpsmonitor.ico - a small performance-meter glyph.

Pure Python (no Pillow): the ICO is written as uncompressed 32-bit BMP images
with an alpha channel. Sizes 16/32/48/64 cover the tray, the taskbar and the
Explorer shortcut.

    python tools\\make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app" / "fpsmonitor.ico"

PLATE = (13, 17, 23, 235)      # #0d1117
PLATE_EDGE = (43, 53, 66, 255)  # #2b3542
BAR_COLORS = [(56, 189, 248, 255), (251, 191, 36, 255), (74, 222, 128, 255)]  # blue, amber, green
BAR_HEIGHTS = (0.34, 0.52, 0.72)
TRANSPARENT = (0, 0, 0, 0)


def _blend(pixel, over):
    """Source-over compositing of two RGBA tuples."""
    sr, sg, sb, sa = over
    if sa == 255:
        return over
    if sa == 0:
        return pixel
    dr, dg, db, da = pixel
    a = sa / 255.0
    return (
        int(sr * a + dr * (1 - a)),
        int(sg * a + dg * (1 - a)),
        int(sb * a + db * (1 - a)),
        max(da, sa),
    )


def render(size: int) -> list[list[tuple[int, int, int, int]]]:
    pixels = [[TRANSPARENT for _ in range(size)] for _ in range(size)]
    radius = max(2, size // 6)

    def in_plate(x: int, y: int) -> bool:
        # rounded rectangle
        for cx, cy in (
            (radius, radius),
            (size - 1 - radius, radius),
            (radius, size - 1 - radius),
            (size - 1 - radius, size - 1 - radius),
        ):
            if (x < radius or x > size - 1 - radius) and (y < radius or y > size - 1 - radius):
                if (x - cx) ** 2 + (y - cy) ** 2 > radius**2:
                    return False
        return True

    for y in range(size):
        for x in range(size):
            if in_plate(x, y):
                edge = (
                    x < 1 or y < 1 or x > size - 2 or y > size - 2
                )
                pixels[y][x] = PLATE_EDGE if edge else PLATE

    # three bars, baseline near the bottom
    bar_width = max(2, size // 7)
    gap = max(1, (size - 3 * bar_width) // 5)
    total = 3 * bar_width + 2 * gap
    start_x = (size - total) // 2
    baseline = size - max(2, size // 8)

    for index, (height_ratio, colour) in enumerate(zip(BAR_HEIGHTS, BAR_COLORS)):
        x0 = start_x + index * (bar_width + gap)
        bar_height = max(2, int(size * height_ratio))
        y0 = baseline - bar_height
        for y in range(y0, baseline):
            for x in range(x0, x0 + bar_width):
                if 0 <= x < size and 0 <= y < size:
                    pixels[y][x] = _blend(pixels[y][x], colour)
    return pixels


def bmp_payload(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    size = len(pixels)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        size,        # biWidth
        size * 2,    # biHeight (XOR + AND)
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression = BI_RGB
        0,           # biSizeImage
        0, 0, 0, 0,  # resolution / palette
    )
    xor = bytearray()
    for y in range(size - 1, -1, -1):  # bottom-up
        for x in range(size):
            r, g, b, a = pixels[y][x]
            xor += bytes((b, g, r, a))
    mask_row = ((size + 31) // 32) * 4  # 1bpp rows padded to 4 bytes
    return header + bytes(xor) + bytes(mask_row * size)


def build_ico(sizes: list[int]) -> bytes:
    images = [bmp_payload(render(size)) for size in sizes]
    count = len(images)
    directory = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = bytearray()
    for size, payload in zip(sizes, images):
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0, 0, 1, 32, len(payload), offset,
        )
        offset += len(payload)
    return directory + bytes(entries) + b"".join(images)


def main() -> int:
    sizes = [16, 32, 48, 64]
    TARGET.write_bytes(build_ico(sizes))
    print(f"wrote {TARGET} ({TARGET.stat().st_size:,} bytes, sizes {sizes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
