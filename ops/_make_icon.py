"""Generate the Market AI Lab app icon (window / tray / exe / launcher).

Run once to (re)create the icon(s):
    python ops/_make_icon.py          # writes ops/MarketAILab.ico (Windows)
    python ops/_make_icon.py --png    # also writes ops/MarketAILab.png (Linux)
"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "MarketAILab.ico")
OUT_PNG = os.path.join(HERE, "MarketAILab.png")

BG = (13, 17, 23, 255)        # GitHub-dark background
ACCENT = (46, 160, 67, 255)   # green up-trend
GRID = (48, 54, 61, 255)


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG)
    d = ImageDraw.Draw(img)
    pad = max(2, size // 10)
    # rounded-ish border
    d.rectangle([pad, pad, size - pad, size - pad], outline=GRID,
                width=max(1, size // 32))
    # an up-and-to-the-right line chart
    pts = [
        (pad + (size * 0.05), size - pad - (size * 0.12)),
        (pad + (size * 0.22), size - pad - (size * 0.34)),
        (pad + (size * 0.40), size - pad - (size * 0.24)),
        (pad + (size * 0.58), size - pad - (size * 0.52)),
        (pad + (size * 0.78), size - pad - (size * 0.74)),
    ]
    d.line(pts, fill=ACCENT, width=max(2, size // 16), joint="curve")
    # arrowhead
    ax, ay = pts[-1]
    h = max(3, size // 12)
    d.polygon([(ax, ay), (ax - h, ay + h * 0.3), (ax - h * 0.3, ay + h)],
              fill=ACCENT)
    return img


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = render(256)
    imgs = [render(s) for s in sizes]
    base.save(OUT, format="ICO",
              sizes=[(s, s) for s in sizes], append_images=imgs)
    print(f"wrote {OUT}")
    # The Linux .desktop launcher uses a PNG icon (256x256 is plenty).
    if "--png" in sys.argv or os.name != "nt":
        base.save(OUT_PNG, format="PNG")
        print(f"wrote {OUT_PNG}")


if __name__ == "__main__":
    main()
