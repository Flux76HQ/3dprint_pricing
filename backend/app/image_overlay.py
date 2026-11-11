"""The fixed templates that turn a generated picture into an advertising poster: the product texts and the logo, drawn here.

The model is asked for a picture *without* text (it cannot be trusted to spell) and to keep part of it calm; the texts are then
laid over the photo by this module, so they are exactly what was typed. The photo stays the whole poster: there is no panel or box,
only a soft shade under the texts that fades into the picture. A poster has one loud thing and the rest is quiet: a short accent
bar, the product name as a large headline in a display typeface, a thin rule, the specifications as a plain list and the extra
text on a tilted label. Only one picture of the four is made a poster (the others stay photos, so a carousel is not four times
the same text).

Each purpose has its own typeface and accent (`TEMPLATES`); where the texts go depends on the shape of the picture (`LAYOUTS`).
**The colours follow the photo**: under a dark or busy picture the texts are white on a dark shade, under a light one (a studio
picture) they are dark on a light shade, decided by measuring the picture where the texts come, so they are always readable.
Nothing here is random: the same texts on the same picture give the same poster. Sizes follow the picture, and a text that does
not fit is made smaller, then cut. The typefaces are in `app/fonts`, each with its licence (SIL Open Font License)."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

FONTS = Path(__file__).parent / "fonts"
BODY, BODY_BOLD = "OpenSans-Regular.ttf", "OpenSans-Bold.ttf"
# purpose -> the headline's typeface (`scale` evens out how large the typefaces run, `caps` sets it in capitals), and the accent
# with the colour of the text on the label, for a dark and for a light picture
TEMPLATES = {
    "marktplaats": {"display": "BebasNeue-Regular.ttf", "scale": 1.32, "caps": True,
                    "dark": ((255, 122, 26), (24, 24, 27)), "light": ((224, 82, 6), (255, 255, 255))},
    "social": {"display": "Anton-Regular.ttf", "scale": 1.08, "caps": True,
               "dark": ((255, 214, 10), (17, 17, 20)), "light": ((255, 214, 10), (17, 17, 20))},
    "webshop": {"display": "DMSerifDisplay-Regular.ttf", "scale": 1.06, "caps": False,
                "dark": ((147, 197, 253), (15, 23, 42)), "light": ((29, 78, 216), (255, 255, 255))},
}
# what the texts look like on a dark and on a light picture: the headline, the list, the shade and how strong it gets (of 255)
INK = {"dark": {"ink": (255, 255, 255), "soft": (240, 240, 244), "shade": (6, 6, 10), "strength": 158},
       "light": {"ink": (15, 23, 42), "soft": (51, 65, 85), "shade": (255, 255, 255), "strength": 190}}
LIGHT_FROM = 150                                          # mean brightness (0-255) of the picture under the texts from which it counts as light
# shape of the picture -> where the texts go: along the bottom, or in the left part of a wide picture
LAYOUTS = {"square": "bottom", "portrait": "bottom", "context": "bottom", "studio": "bottom", "detail": "bottom", "landscape": "left"}
# what the model is told, so that the object is not where the texts come
ROOM = {
    "bottom": "Compose the picture so that the object sits in the upper part and the bottom third stays calm and uncluttered: a caption is put there afterwards. ",
    "left": "Compose the picture so that the object sits in the right half and the left 40% stays calm and uncluttered: a caption is put there afterwards. ",
}
HEADLINE = (0.118, 0.104, 0.092, 0.08, 0.07, 0.06, 0.052)   # sizes tried for the headline, largest first (times the unit)
SCALES = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)                   # the whole block is made smaller, step by step, until it fits its room
SMOOTH = 3                                                # the label is drawn this much larger and scaled down, so its edges are not jagged
TILT = 3                                                  # degrees the label leans


def room(variant: str) -> str:
    return ROOM[LAYOUTS[variant]]


def _font(name: str, size: float):
    return ImageFont.truetype(str(FONTS / name), max(8, round(size)))


def _covers(name: str, text: str) -> bool:
    """Whether the typeface has every character of the text (a display typeface has fewer than the one for running text)."""
    font = _font(name, 40)
    missing = font.getmask("￿")
    blank = (missing.size, bytes(missing))
    return all((lambda m: (m.size, bytes(m)) != blank)(font.getmask(char)) for char in set(text) if not char.isspace())


def _wrap(text: str, font, width: float, max_lines: int) -> "tuple[list, bool]":
    """(the lines, whether the text had to be damaged to fit): at most `max_lines` lines no wider than `width`. A word that is too
    long on its own is broken, and what is left over ends in an ellipsis."""
    lines, line, damaged = [], "", False
    for word in text.split():
        if font.getlength(word) > width:
            damaged = True
            if line:
                lines.append(line)
            line = ""
            for char in word:
                if line and font.getlength(line + char) > width:
                    lines.append(line)
                    line = ""
                line += char
            continue
        candidate = f"{line} {word}" if line else word
        if font.getlength(candidate) <= width:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        damaged = True
        last = lines[max_lines - 1]
        while last and font.getlength(last + "...") > width:
            last = last[:-1]
        lines = lines[:max_lines - 1] + [last.rstrip() + "..."]
    return lines, damaged


def _label(text: str, accent: tuple, label_ink: tuple, unit: float, width: float):
    """The extra text on a slanted, slightly tilted label of the accent colour."""
    font = _font(BODY_BOLD, unit * 0.04)
    pad_x, pad_y, lean = unit * 0.03, unit * 0.014, unit * 0.022
    lines, _ = _wrap(text, font, width * 0.93 - 2 * pad_x - lean, 2)
    line_height = font.size * 1.25
    w = round(max(font.getlength(line) for line in lines) + 2 * pad_x + lean)
    h = round(len(lines) * line_height + 2 * pad_y)
    big = Image.new("RGBA", (w * SMOOTH, h * SMOOTH), (0, 0, 0, 0))
    ImageDraw.Draw(big).polygon([(lean * SMOOTH, 0), (w * SMOOTH, 0), ((w - lean) * SMOOTH, h * SMOOTH), (0, h * SMOOTH)], fill=accent + (255,))
    label = big.resize((w, h), Image.LANCZOS)
    draw = ImageDraw.Draw(label)
    for n, line in enumerate(lines):
        draw.text((pad_x + lean / 2, pad_y + n * line_height + line_height / 2), line, font=font, fill=label_ink, anchor="lm")
    return label.rotate(TILT, resample=Image.BICUBIC, expand=True)


def _block(text: dict, style: dict, tone: str, unit: float, width: int):
    """The texts as one transparent picture `width` wide: bar, headline, rule, list, label."""
    ink, (accent, label_ink) = INK[tone], style[tone]
    name = text["product_name"].upper() if style["caps"] else text["product_name"]
    face = style["display"] if _covers(style["display"], name) else BODY_BOLD      # a character the display typeface lacks: the plain one
    scale = style["scale"] if face == style["display"] else 0.8
    steps, rules, y = [], [], 0.0
    bar = (unit * 0.13, unit * 0.017)
    y += bar[1] + unit * 0.034
    for size in HEADLINE:                                            # the largest size at which the name fits whole
        head_font = _font(face, unit * size * scale)
        head, damaged = _wrap(name, head_font, width, 3)
        if not damaged:
            break
    box = head_font.getbbox("Hdl" if not style["caps"] else "H", anchor="ls")       # how far the letters rise above the line they stand on
    rise, advance = -box[1], (-box[1]) * (1.2 if style["caps"] else 1.32)
    for n, line in enumerate(head):
        steps.append((line, head_font, ink["ink"], 0, y + rise + n * advance))
    y += rise + (len(head) - 1) * advance + (head_font.size * 0.24 if not style["caps"] else 0)
    y += unit * 0.04
    rules.append(y)
    y += unit * 0.03
    spec_font = _font(BODY, unit * 0.037)
    indent, bullets = unit * 0.042, []
    spec_rise = -spec_font.getbbox("H", anchor="ls")[1]
    for spec in text["specs"]:
        bullets.append(y + spec_rise / 2)
        for line in _wrap(spec, spec_font, width - indent, 2)[0]:
            steps.append((line, spec_font, ink["soft"], indent, y + spec_rise))
            y += spec_font.size * 1.38
    y += unit * 0.026
    label = _label(text["extra_text"], accent, label_ink, unit, width)
    block = Image.new("RGBA", (width, round(y + label.height) + 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(block)
    draw.rectangle((0, 0, bar[0], bar[1]), fill=accent)
    for top in rules:
        draw.rectangle((0, top, min(width, unit * 0.46), top + max(1, round(unit * 0.003))), fill=ink["ink"] + (120,))
    for line, font, colour, x, baseline in steps:
        draw.text((x, baseline), line, font=font, fill=colour, anchor="ls")
    side = spec_font.size * 0.3
    for middle in bullets:                                           # drawn, so a bullet never depends on a glyph
        draw.rectangle((0, middle - side / 2, side, middle + side / 2), fill=accent)
    block.alpha_composite(label, (0, round(y)))
    return block


def _fitting(text: dict, style: dict, tone: str, base: int, width: int, limit: float):
    for scale in SCALES:
        block = _block(text, style, tone, base * scale, width)
        if block.height <= limit:
            break
    return block


def _tone(image, box: tuple) -> str:
    """Light or dark: how bright the picture is where the texts come."""
    region = image.crop(tuple(max(0, round(v)) for v in box)).convert("L")
    return "light" if ImageStat.Stat(region).mean[0] >= LIGHT_FROM else "dark"


def _ramp(length: int, start: float, full: float, strength: int):
    """A strip of `length` values: nothing up to `start`, then rising smoothly to `strength` at `full`, and staying there."""
    span = max(1.0, full - start)
    values = []
    for n in range(length):
        t = min(1.0, max(0.0, (n - start) / span))
        values.append(round(strength * t * t * (3 - 2 * t)))
    return values


def _shade(image, tone: str, mask) -> None:
    colour = Image.new("RGBA", image.size, INK[tone]["shade"] + (255,))
    colour.putalpha(mask)
    image.alpha_composite(colour)


def _place(image, block, position: tuple, tone: str, unit: int) -> None:
    """The texts on the picture; on a dark picture with a soft shadow, which keeps white letters sharp on a pale spot."""
    if tone == "dark":
        shadow = Image.new("RGBA", block.size, (0, 0, 0, 0))
        shadow.putalpha(block.getchannel("A").filter(ImageFilter.GaussianBlur(max(1, unit * 0.008))).point(lambda v: v * 150 // 255))
        image.alpha_composite(shadow, (position[0], position[1] + max(1, round(unit * 0.004))))
    image.alpha_composite(block, position)


def _bottom(image, style: dict, text: dict) -> None:
    """The texts along the bottom, left-aligned; the picture darkens (or lightens) towards them."""
    width, height = image.size
    base = min(width, height)
    pad = round(base * 0.055)
    tone = _tone(image, (0, height * 0.6, width, height))
    block = _fitting(text, style, tone, base, min(width - 2 * pad, round(width * 0.9)), height * 0.48)
    top = height - pad - block.height
    column = Image.new("L", (1, height))
    column.putdata(_ramp(height, top - base * 0.34, top + base * 0.08, INK[tone]["strength"]))
    _shade(image, tone, column.resize((width, height)))
    _place(image, block, (pad, top), tone, base)


def _left(image, style: dict, text: dict) -> None:
    """The texts in the left part of a wide picture; the picture darkens (or lightens) towards the left."""
    width, height = image.size
    base = min(width, height)
    pad = round(base * 0.055)
    tone = _tone(image, (0, 0, width * 0.45, height))
    block = _fitting(text, style, tone, base, round(width * 0.4), height * 0.7)
    row = Image.new("L", (width, 1))                                  # full on the left, gone at 68% of the width
    row.putdata(_ramp(width, width * 0.32, width * 0.62, INK[tone]["strength"])[::-1])
    _shade(image, tone, row.resize((width, height)))
    _place(image, block, (pad, height - pad - block.height), tone, base)


def _logo(image, logo: bytes) -> None:
    """The logo at the top left, on a white plate so it stays readable whatever is behind it."""
    width, height = image.size
    base = min(width, height)
    pad, inner = round(base * 0.04), round(base * 0.016)
    with Image.open(BytesIO(logo)) as opened:
        mark = opened.convert("RGBA")
    mark.thumbnail((max(1, round(width * 0.24)), max(1, round(height * 0.11))), Image.LANCZOS)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((pad, pad, pad + mark.width + 2 * inner, pad + mark.height + 2 * inner),
                                            radius=round(base * 0.014), fill=(255, 255, 255, 240))
    layer.alpha_composite(mark, (pad + inner, pad + inner))
    image.alpha_composite(layer)


def compose(content: bytes, purpose: str, variant: str, *, text: "dict | None" = None, logo: "bytes | None" = None) -> bytes:
    """The picture (a JPEG we wrote ourselves) with the texts of `text` (product_name, specs, extra_text) and the logo on it, as JPEG."""
    with Image.open(BytesIO(content)) as opened:
        image = opened.convert("RGBA")
    if text:
        {"bottom": _bottom, "left": _left}[LAYOUTS[variant]](image, TEMPLATES[purpose], text)
    if logo:
        _logo(image, logo)
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()
