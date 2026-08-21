"""
Draws the app icon into assets/: icon.ico (Windows), icon.icns (macOS) and
icon.png (Linux). Run it after changing the design: python tools/make_icons.py

The colours follow the GUI's accent. Everything is drawn at four times the
size and scaled down to smooth the edges.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"

SIZE = 1024
SCALE = 4

TOP = (242, 116, 66)
BOTTOM = (196, 66, 22)
GLYPH = (255, 255, 255)


def _gradient(size: int) -> Image.Image:
    column = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    return column.resize((size, size))


def _stroke(draw: ImageDraw.ImageDraw, a: tuple[float, float], b: tuple[float, float], width: float) -> None:
    draw.line([a, b], fill=GLYPH, width=round(width))
    r = width / 2
    for x, y in (a, b):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=GLYPH)


def _arrow(draw: ImageDraw.ImageDraw, y: float, x0: float, x1: float, width: float, head: float) -> None:
    direction = 1 if x1 > x0 else -1
    _stroke(draw, (x0, y), (x1, y), width)
    back = x1 - direction * head
    _stroke(draw, (x1, y), (back, y - head), width)
    _stroke(draw, (x1, y), (back, y + head), width)


def draw(size: int = SIZE, *, margin: float = 0.06) -> Image.Image:
    big = size * SCALE
    inset = round(big * margin)
    radius = round((big - 2 * inset) * 0.235)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, big - inset - 1, big - inset - 1], radius=radius, fill=255
    )
    tile = _gradient(big).convert("RGBA")
    tile.putalpha(mask)

    glyph = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    g = ImageDraw.Draw(glyph)
    width = big * 0.075
    head = big * 0.105
    left, right = big * 0.285, big * 0.715
    _arrow(g, big * 0.39, left, right, width, head)
    _arrow(g, big * 0.61, right, left, width, head)

    # A faint shadow keeps the arrows readable against the lighter top edge.
    shadow = glyph.split()[3].filter(ImageFilter.GaussianBlur(big * 0.012))
    shadow_layer = Image.new("RGBA", (big, big), (120, 40, 10, 0))
    shadow_layer.putalpha(shadow.point(lambda a: a * 0.35))
    shadow_layer = shadow_layer.transform(
        shadow_layer.size, Image.AFFINE, (1, 0, 0, 0, 1, -big * 0.008)
    )
    tile = Image.alpha_composite(tile, shadow_layer)
    tile = Image.alpha_composite(tile, glyph)

    return tile.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    full = draw()
    full.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    full.save(
        OUT / "icon.ico",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    # macOS icons leave more space around the tile than Windows icons do.
    draw(margin=0.1).save(OUT / "icon.icns")
    print(f"wrote {', '.join(p.name for p in sorted(OUT.iterdir()))}")


if __name__ == "__main__":
    main()
