"""Writes the installer / app icons (ekiw.png, ekiw.ico, ekiw.icns) into imagewise/assets.

If Icon_1.png is in the project folder it is used (a square PNG with a transparent background, 512 x 512
or bigger, gives the best result); otherwise a simple built-in icon is drawn.

Run:  python packaging/make_icons.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "imagewise" / "assets"
ACCENT = (22, 20, 125)  # #16147d


def draw_master(size: int = 1024) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=ACCENT)
    # a photo card, slightly tilted
    card = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    x0, y0, x1, y1 = int(s * .17), int(s * .20), int(s * .83), int(s * .80)
    cd.rounded_rectangle((x0, y0, x1, y1), radius=int(s * .05), fill=(255, 255, 255, 255))
    ix0, iy0, ix1, iy1 = x0 + int(s * .045), y0 + int(s * .045), x1 - int(s * .045), y1 - int(s * .045)
    cd.rounded_rectangle((ix0, iy0, ix1, iy1), radius=int(s * .025), fill=(255, 214, 120, 255))
    # sun and hills inside the photo
    r = int(s * .075)
    cd.ellipse((ix1 - int(s * .20) - r, iy0 + int(s * .05), ix1 - int(s * .20) + r, iy0 + int(s * .05) + 2 * r),
               fill=(255, 255, 255, 255))
    mid = iy1 - int(s * .02)
    cd.polygon([(ix0, iy1), (ix0, iy1 - int(s * .15)), (ix0 + int(s * .17), mid - int(s * .26)),
                (ix0 + int(s * .33), iy1 - int(s * .12)), (ix0 + int(s * .43), iy1 - int(s * .2)),
                (ix1, iy1 - int(s * .06)), (ix1, iy1)], fill=ACCENT + (255,))
    # clip the hills to the inner rounded rectangle
    clip = Image.new("L", (s, s), 0)
    ImageDraw.Draw(clip).rounded_rectangle((ix0, iy0, ix1, iy1), radius=int(s * .025), fill=255)
    base = card.copy()
    base.putalpha(Image.eval(card.getchannel("A"), lambda v: v))
    masked = Image.composite(card, Image.new("RGBA", (s, s), (0, 0, 0, 0)), clip)
    card_final = Image.alpha_composite(
        Image.new("RGBA", (s, s), (0, 0, 0, 0)),
        Image.alpha_composite(base, masked))
    card_final = card_final.rotate(-7, resample=Image.BICUBIC, center=(s // 2, s // 2))
    img = Image.alpha_composite(img, card_final)
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    source = ROOT / "Icon_1.png"
    if source.is_file():
        img = Image.open(source).convert("RGBA")
        side = max(img.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))  # pad to a square, keeping the picture centred
        square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        master = square.resize((1024, 1024), Image.LANCZOS)
        print("Using", source)
    else:
        master = draw_master()
        master.save(ASSETS / "ekiw_master.png")
    master.resize((256, 256), Image.LANCZOS).save(ASSETS / "ekiw.png")
    master.save(ASSETS / "ekiw.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    master.save(ASSETS / "ekiw.icns")  # Pillow writes the standard icon sizes
    print("Icons written to", ASSETS)


if __name__ == "__main__":
    main()
