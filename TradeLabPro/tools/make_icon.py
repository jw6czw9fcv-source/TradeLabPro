"""Draw the app icon: resources/tradelab.ico (plus a PNG preview).

Generated rather than checked in as an opaque binary, so the design can be
adjusted by editing numbers here instead of hunting for whatever tool made it.

    python tools/make_icon.py

The motif is three ascending candlesticks — the app charts candlesticks, and it
is the one trading symbol that still reads at 16x16 in a taskbar. Colours come
from the app's own palette (tradelab/ui/theme.py) so the icon, the chart and the
P&L columns all use the same green.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT_ICO = ROOT / "resources" / "tradelab.ico"
OUT_PNG = ROOT / "resources" / "tradelab_preview.png"

# Windows picks the nearest size, so ship the full set rather than let it
# rescale a big one badly for the taskbar.
SIZES = [16, 24, 32, 48, 64, 128, 256]

# Everything is drawn at this multiple of the target size and downsampled, which
# is what gives clean edges on the rounded corners and thin wicks.
SUPERSAMPLE = 8

BG_TOP = (26, 33, 43)          # slate, a touch lighter at the top
BG_BOTTOM = (13, 17, 23)
EDGE = (48, 58, 70)
GREEN_DARK = (47, 157, 69)
GREEN_MID = (55, 171, 75)
GREEN_BRIGHT = (63, 185, 80)   # theme.UP
BASELINE = (38, 48, 57)

# (centre x, body top, body bottom, wick top, wick bottom, colour) as fractions
# of the canvas, low to high so the eye reads left-to-right as a rising market.
CANDLES = [
    (0.265, 0.600, 0.760, 0.530, 0.820, GREEN_DARK),
    (0.500, 0.430, 0.640, 0.355, 0.710, GREEN_MID),
    (0.735, 0.235, 0.500, 0.170, 0.570, GREEN_BRIGHT),
]
BODY_W = 0.150
WICK_W = 0.042


def _gradient(size: int) -> Image.Image:
    """Vertical slate gradient — a flat fill looks dead at large sizes."""
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(
            round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)))
    return grad.resize((size, size))


def render(size: int) -> Image.Image:
    # Below about 32px the wicks are thinner than a pixel and the baseline sits
    # a pixel from the candle feet, so both turn to grey mush. The small sizes
    # drop them and fatten the bodies instead - the shape still reads as three
    # rising candles, which is all that survives at taskbar scale anyway.
    small = size <= 24
    s = size * SUPERSAMPLE
    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Rounded-square plate, masked so the corners stay transparent.
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1),
                                           radius=int(s * 0.22), fill=255)
    plate = _gradient(s).convert("RGBA")
    icon.paste(plate, (0, 0), mask)

    draw = ImageDraw.Draw(icon)
    if not small:
        inset = s * 0.012
        draw.rounded_rectangle((inset, inset, s - 1 - inset, s - 1 - inset),
                               radius=int(s * 0.21), outline=EDGE,
                               width=max(1, int(s * 0.012)))
        # A faint baseline gives the candles something to stand on.
        draw.line((s * 0.20, s * 0.845, s * 0.80, s * 0.845),
                  fill=BASELINE, width=max(1, int(s * 0.018)))

    body_w = s * (BODY_W * 1.45 if small else BODY_W)
    wick_w = s * WICK_W
    radius = max(1, int(body_w * 0.22))
    for cx, top, bottom, wick_top, wick_bottom, colour in CANDLES:
        x = cx * s
        if not small:
            draw.rounded_rectangle(
                (x - wick_w / 2, wick_top * s, x + wick_w / 2, wick_bottom * s),
                radius=max(1, int(wick_w * 0.5)), fill=colour)
        else:
            # Reclaim the wick's vertical reach so the small icon keeps the same
            # overall rhythm rather than looking squat.
            top -= 0.03
            bottom += 0.03
        draw.rounded_rectangle(
            (x - body_w / 2, top * s, x + body_w / 2, bottom * s),
            radius=radius, fill=colour)

    return icon.resize((size, size), Image.LANCZOS)


def build() -> Path:
    frames = [render(n) for n in SIZES]
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    # Pillow writes every provided size into the one .ico file.
    frames[-1].save(OUT_ICO, format="ICO",
                    sizes=[(n, n) for n in SIZES], append_images=frames[:-1])

    # A side-by-side preview so the small sizes can actually be judged, which is
    # where an icon design usually falls apart.
    pad, scale = 16, 2
    strip_w = sum(n * scale + pad for n in SIZES) + pad
    strip = Image.new("RGBA", (strip_w, 256 * scale + pad * 2), (24, 26, 30, 255))
    x = pad
    for n, frame in zip(SIZES, frames):
        big = frame.resize((n * scale, n * scale), Image.NEAREST)
        strip.paste(big, (x, strip.height - pad - big.height), big)
        x += n * scale + pad
    strip.save(OUT_PNG)

    print(f"wrote {OUT_ICO.relative_to(ROOT)} ({OUT_ICO.stat().st_size:,} bytes, "
          f"{len(SIZES)} sizes)")
    print(f"wrote {OUT_PNG.relative_to(ROOT)} (preview)")
    return OUT_ICO


if __name__ == "__main__":
    build()
