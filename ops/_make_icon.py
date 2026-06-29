"""Generate ops/MarketAILab.ico (window / tray / exe icon).

Run once to (re)create the icon. Output: ops/MarketAILab.ico (multi-size).
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "MarketAILab.ico")

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


if __name__ == "__main__":
    main()
