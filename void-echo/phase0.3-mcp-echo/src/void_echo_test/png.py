"""Pure-stdlib PNG renderer for VOID ECHO Phase 0.4 (triple-signal edition).

No Pillow, no network: the encoder is written directly against ISO/IEC 15948
(PNG) using zlib + struct, so `frame()` output is byte-for-byte reproducible.

Three INDEPENDENT signals exist only in the pixels and never in any text block:

  1. top-RIGHT thick bars        count 1-3        (3 states)
  2. colour of those bars        6-colour palette (6 states)
  3. bottom-CENTRE slash panel   "\", "/", "-"    (3 states)

3 x 6 x 3 = 54, so a client that cannot see the image has ~1/54 chance of
guessing all three correctly in one call.

Base scene per spec: light background, one red ellipse, one blue rectangle.
Top-LEFT dark bars encode the frame index; that value IS written in the tool's
text, so it proves nothing and exists only as a sanity anchor.
"""

from __future__ import annotations

import struct
import zlib

WIDTH = 360
HEIGHT = 240
_SUPERSAMPLE = 2

# Base palette
BG = (245, 245, 250)
RED = (220, 40, 60)
BLUE = (30, 90, 200)
DARK = (25, 25, 35)
PANEL_BG = (228, 228, 238)

# Six clearly distinct accent colours
ACCENTS = {
    "teal": (18, 168, 132),
    "orange": (240, 150, 30),
    "purple": (150, 60, 200),
    "pink": (232, 92, 152),
    "lime": (140, 200, 60),
    "sky": (70, 160, 240),
}

SLASHES = ("backslash", "slash", "horizontal")  # "\"  "/"  "-"

# Slash panel geometry (bottom-centre, clear of ellipse and rectangle)
PX0, PY0, PX1, PY1 = 150, 178, 250, 228
SLASH_T = 6.0


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rgb: bytearray) -> bytes:
    """Encode an RGB8 buffer (row-major, no padding) as a valid PNG."""
    assert len(rgb) == width * height * 3, "buffer size mismatch"
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None)
        start = y * stride
        raw += rgb[start : start + stride]
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def _in_ellipse(px, py, cx, cy, rx, ry) -> bool:
    dx = (px - cx) / rx
    dy = (py - cy) / ry
    return dx * dx + dy * dy <= 1.0


def _in_rect(px, py, x0, y0, x1, y1) -> bool:
    return x0 <= px <= x1 and y0 <= py <= y1


def _near_segment(px, py, ax, ay, bx, by, tol) -> bool:
    """Distance from point to segment <= tol (cheap, exact enough here)."""
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    length2 = vx * vx + vy * vy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / length2))
    dx, dy = wx - t * vx, wy - t * vy
    return dx * dx + dy * dy <= tol * tol


def _slash_endpoints(kind: str):
    """Return ((ax, ay), (bx, by)) for the requested slash inside the panel."""
    if kind == "backslash":      # top-left -> bottom-right  "\"
        return (PX0, PY0), (PX1, PY1)
    if kind == "slash":          # bottom-left -> top-right  "/"
        return (PX0, PY1), (PX1, PY0)
    my = (PY0 + PY1) / 2.0       # horizontal "-"
    return (PX0, my), (PX1, my)


def render_frame(
    index: int,
    secret: int = 0,
    accent: str = "teal",
    slash: str = "backslash",
    width: int = WIDTH,
    height: int = HEIGHT,
) -> bytes:
    """Render one frame. `secret` (1-3), `accent` (6 colours) and `slash`
    (backslash / slash / horizontal) are the three pixel-only signals."""
    idx = max(0, int(index))
    bars = idx + 1
    sec = max(0, min(3, int(secret)))
    accent_rgb = ACCENTS.get(str(accent).lower(), ACCENTS["teal"])
    kind = slash if slash in SLASHES else "backslash"
    (sax, say), (sbx, sby) = _slash_endpoints(kind)
    tol = SLASH_T / 2.0

    cx = 0.28 * width + (idx % 5) * 0.035 * width
    cy = 0.55 * height
    rx, ry = 0.16 * width, 0.30 * height
    rx0, ry0, rx1, ry1 = 0.58 * width, 0.32 * height, 0.90 * width, 0.72 * height

    ss = _SUPERSAMPLE
    step = 1.0 / ss
    pixels = bytearray(width * height * 3)

    for py in range(height):
        row = py * width * 3
        for px in range(width):
            acc_r = acc_g = acc_b = 0
            for sy in range(ss):
                for sx in range(ss):
                    fx = px + sx * step + step * 0.5
                    fy = py + sy * step + step * 0.5

                    r, g, b = BG

                    # 1) blue rectangle, then red ellipse on top
                    if _in_rect(fx, fy, rx0, ry0, rx1, ry1):
                        r, g, b = BLUE
                    if _in_ellipse(fx, fy, cx, cy, rx, ry):
                        r, g, b = RED

                    # 2) slash panel (drawn over the base scene, own background)
                    if _in_rect(fx, fy, PX0 - 2, PY0 - 2, PX1 + 2, PY1 + 2):
                        r, g, b = PANEL_BG
                        if _near_segment(fx, fy, sax, say, sbx, sby, tol):
                            r, g, b = DARK

                    # 3) top-LEFT dark bars = index + 1 (also in the text)
                    if 8.0 <= fy <= 34.0 and fx >= 12.0:
                        rel = fx - 12.0
                        slot = int(rel // 14)
                        if slot < bars and (rel - slot * 14.0) <= 6.0:
                            r, g, b = DARK

                    # 4) top-RIGHT accent bars = `secret` (pixel-only)
                    #    Must stay left of the 14px right margin: otherwise rel
                    #    goes negative, slot becomes -1 and an extra phantom bar
                    #    is painted (this shifted every count by +1 once already).
                    if 6.0 <= fy <= 46.0 and sec > 0 and fx <= width - 14.0:
                        rel = (width - 14.0) - fx
                        slot = int(rel // 20.0)
                        if slot < sec and (rel - slot * 20.0) <= 12.0:
                            r, g, b = accent_rgb

                    acc_r += r
                    acc_g += g
                    acc_b += b

            n = ss * ss
            o = row + px * 3
            pixels[o] = acc_r // n
            pixels[o + 1] = acc_g // n
            pixels[o + 2] = acc_b // n

    return encode_png(width, height, pixels)
