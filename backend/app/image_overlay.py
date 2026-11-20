"""The fixed templates that turn a generated picture into an advertising poster: the product texts and the logo, drawn here.

The model is asked for a picture *without* text (it cannot be trusted to spell) and to keep part of it calm; the texts are then
laid over the photo by this module, so they are exactly what was typed. The photo stays the whole poster: there is no panel or box,
only a soft shade under the texts that fades into the picture. A poster has one loud thing and the rest is quiet: a short accent
bar, the product name as a large headline in a display typeface, a thin rule, the specifications as a plain list and the extra
text on a tilted label. Only one picture of the four is made a poster (the others stay photos, so a carousel is not four times
the same text).

Each purpose has its own typeface and accent (`TEMPLATES`); where the texts go depends on the shape of the picture (`LAYOUTS`).
**By default the colours follow the photo**: under a dark or busy picture the texts are white on a dark shade, under a light one (a studio
picture) they are dark on a light shade, decided by measuring the picture where the texts come, so they are always readable.
The owner may choose the colour of the texts and of the accent (the bar, the bullets and the label) to go with the item (`look`, `_paint`):
the shade under the texts is then the one the chosen text colour stands out against most (and stronger when that goes against the photo),
and the words on the label are white or near-black, whichever reads better on the chosen accent. So a chosen colour never makes a poster
unreadable. The extra text sits on a label of one of `LABEL_STYLES`: the quiet tilted label, or a shape that stands out more.
Nothing here is random: the same texts on the same picture give the same poster. Sizes follow the picture, and a text that does
not fit is made smaller, then cut. The typefaces are in `app/fonts`, each with its licence (SIL Open Font License)."""
import math
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
# the shapes the extra text can stand on: the quiet tilted label (the default), a pill, a ribbon with notched ends, a star-shaped sticker, a block
# with a hard offset shadow. Each but the first is a little larger and lifted off the picture by a shadow, so it stands out.
LABEL_STYLES = ("tilted", "pill", "ribbon", "burst", "block")
WHITE, NEAR_BLACK = (255, 255, 255), (17, 17, 20)
FORCED = 40                                               # how much stronger the shade gets when the chosen text colour goes against the photo


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


def _hex(colour) -> "tuple | None":
    """`#rrggbb` as (r, g, b); anything else is None (the colour is left to the template)."""
    if not isinstance(colour, str) or len(colour) != 7 or colour[0] != "#":
        return None
    try:
        return tuple(int(colour[at:at + 2], 16) for at in (1, 3, 5))
    except ValueError:
        return None


def _luminance(rgb: tuple) -> float:
    """Relative luminance as WCAG defines it (0 black, 1 white)."""
    def channel(value):
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple, b: tuple) -> float:
    """The WCAG contrast ratio of two colours (1 to 21)."""
    one, two = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (one + 0.05) / (two + 0.05)


def _on(colour: tuple) -> tuple:
    """The ink that reads best on `colour`: white or near-black."""
    return WHITE if contrast(colour, WHITE) >= contrast(colour, NEAR_BLACK) else NEAR_BLACK


def _mix(a: tuple, b: tuple, part: float) -> tuple:
    return tuple(round(x + (y - x) * part) for x, y in zip(a, b))


def _paint(style: dict, measured: str, look: "dict | None") -> dict:
    """The colours of one poster: the template's for the tone of the photo, with the owner's choices (`look`) laid over them."""
    look = look or {}
    text_colour, accent_colour = _hex(look.get("text_colour")), _hex(look.get("accent_colour"))
    tone = measured
    if text_colour:                                       # the shade the chosen text stands out against most
        tone = "dark" if contrast(text_colour, INK["dark"]["shade"]) >= contrast(text_colour, INK["light"]["shade"]) else "light"
    ink = dict(INK[tone])
    if text_colour:
        ink["ink"], ink["soft"] = text_colour, _mix(text_colour, ink["shade"], 0.12)
        if tone != measured:                              # light letters on a light photo (or dark on dark): the shade has to do more
            ink["strength"] = min(235, ink["strength"] + FORCED)
    accent, label_ink = style[tone]
    if accent_colour:
        accent, label_ink = accent_colour, _on(accent_colour)
    return {**ink, "tone": tone, "accent": accent, "label_ink": label_ink,
            "label": look.get("label_style") if look.get("label_style") in LABEL_STYLES else LABEL_STYLES[0]}


def _lift(label, unit: float, hard: "tuple | None" = None):
    """The label lifted off the picture: a soft shadow under it, or (`hard`) a sharp one of that colour, offset to the bottom right."""
    offset = max(2, round(unit * (0.012 if hard else 0.006)))
    blur = 0 if hard else max(1, round(unit * 0.01))
    margin = offset + blur * 2
    out = Image.new("RGBA", (label.width + margin, label.height + margin), (0, 0, 0, 0))
    alpha = label.getchannel("A")
    if hard:
        shadow = Image.new("RGBA", label.size, hard + (255,))
    else:
        shadow = Image.new("RGBA", label.size, (0, 0, 0, 255))
        alpha = alpha.point(lambda v: v * 120 // 255)
    shadow.putalpha(alpha)
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    layer.alpha_composite(shadow, (blur + offset, blur + offset))
    if blur:
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(layer)
    out.alpha_composite(label, (blur, blur))
    return out


def _lines(draw, lines, font, ink, box_left: float, top: float, line_height: float, width: float = 0) -> None:
    """Lines of the label, from `top`; centred in `width` when it is given, else from `box_left`."""
    for n, line in enumerate(lines):
        middle = top + n * line_height + line_height / 2
        if width:
            draw.text((box_left + width / 2, middle), line, font=font, fill=ink, anchor="mm")
        else:
            draw.text((box_left, middle), line, font=font, fill=ink, anchor="lm")


def _label(text: str, kind: str, accent: tuple, label_ink: tuple, unit: float, width: float, outline: tuple = WHITE):
    """The extra text on its label, of the accent colour, in the shape `kind` (one of `LABEL_STYLES`). The label never gets wider than `width`."""
    if kind == "burst":
        return _burst(text, accent, label_ink, unit, width, outline)
    size = 0.04 if kind == "tilted" else 0.047
    font = _font(BODY_BOLD, unit * size)
    line_height = font.size * 1.25
    if kind == "tilted":
        pad_x, pad_y, lean = unit * 0.03, unit * 0.014, unit * 0.022
        lines, _ = _wrap(text, font, width * 0.93 - 2 * pad_x - lean, 2)
        w = round(max(font.getlength(line) for line in lines) + 2 * pad_x + lean)
        h = round(len(lines) * line_height + 2 * pad_y)
        big = Image.new("RGBA", (w * SMOOTH, h * SMOOTH), (0, 0, 0, 0))
        ImageDraw.Draw(big).polygon([(lean * SMOOTH, 0), (w * SMOOTH, 0), ((w - lean) * SMOOTH, h * SMOOTH), (0, h * SMOOTH)], fill=accent + (255,))
        label = big.resize((w, h), Image.LANCZOS)
        _lines(ImageDraw.Draw(label), lines, font, label_ink, pad_x + lean / 2, pad_y, line_height)
        return label.rotate(TILT, resample=Image.BICUBIC, expand=True)
    pad_y = unit * 0.02
    if kind == "pill":
        ring = max(2, round(unit * 0.006))
        pad_x = unit * 0.045
        lines, _ = _wrap(text, font, width * 0.9 - 2 * pad_x - 2 * ring, 2)
        w = round(max(font.getlength(line) for line in lines) + 2 * pad_x + 2 * ring)
        h = round(len(lines) * line_height + 2 * pad_y + 2 * ring)
        big = Image.new("RGBA", (w * SMOOTH, h * SMOOTH), (0, 0, 0, 0))
        ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SMOOTH - 1, h * SMOOTH - 1), radius=min(h, unit * 0.06) * SMOOTH / 2 if len(lines) > 1 else h * SMOOTH / 2,
                                              fill=accent + (255,), outline=outline + (255,), width=ring * SMOOTH)
        label = big.resize((w, h), Image.LANCZOS)
        _lines(ImageDraw.Draw(label), lines, font, label_ink, 0, pad_y + ring, line_height, w)
        return _lift(label, unit)
    if kind == "ribbon":
        lines, _ = _wrap(text, font, width * 0.9 - unit * 0.14, 2)
        h = round(len(lines) * line_height + 2 * pad_y)
        notch = h * 0.32
        pad_x = notch + unit * 0.035
        w = round(max(font.getlength(line) for line in lines) + 2 * pad_x)
        big = Image.new("RGBA", (w * SMOOTH, h * SMOOTH), (0, 0, 0, 0))
        S = SMOOTH
        ImageDraw.Draw(big).polygon([(0, 0), (w * S, 0), ((w - notch) * S, h * S / 2), (w * S, h * S), (0, h * S), (notch * S, h * S / 2)], fill=accent + (255,))
        label = big.resize((w, h), Image.LANCZOS)
        _lines(ImageDraw.Draw(label), lines, font, label_ink, 0, pad_y, line_height, w)
        return _lift(label.rotate(-2, resample=Image.BICUBIC, expand=True), unit)
    # block: a full, upright panel with a hard shadow in the colour of the headline
    pad_x = unit * 0.035
    lines, _ = _wrap(text, font, width * 0.9 - 2 * pad_x, 2)
    w = round(max(font.getlength(line) for line in lines) + 2 * pad_x)
    h = round(len(lines) * line_height + 2 * pad_y)
    label = Image.new("RGBA", (w, h), accent + (255,))
    _lines(ImageDraw.Draw(label), lines, font, label_ink, pad_x, pad_y, line_height)
    return _lift(label, unit, hard=outline)


def _burst(text: str, accent: tuple, label_ink: tuple, unit: float, width: float, outline: tuple):
    """A round sticker with a jagged edge, the text centred in it and the whole turned a little: the loudest of the labels."""
    for size in (0.054, 0.047, 0.04, 0.034, 0.028):
        font = _font(BODY_BOLD, unit * size)
        lines, damaged = _wrap(text, font, unit * 0.34, 3)
        line_height = font.size * 1.18
        text_w = max(font.getlength(line) for line in lines)
        text_h = len(lines) * line_height
        radius = math.hypot(text_w, text_h) / 2 / 0.86 + unit * 0.02
        if radius * 2 <= width * 0.8 and not damaged:
            break
    else:                                                  # too long for a sticker at any size: the pill holds it on two lines
        return _label(text, "pill", accent, label_ink, unit, width, outline)
    side = round(radius * 2) + 2
    S = SMOOTH
    big = Image.new("RGBA", (side * S, side * S), (0, 0, 0, 0))
    points, spikes = [], 18
    for n in range(spikes * 2):
        r = (radius if n % 2 == 0 else radius * 0.88) * S
        angle = math.pi * n / spikes
        points.append((side * S / 2 + r * math.cos(angle), side * S / 2 + r * math.sin(angle)))
    draw = ImageDraw.Draw(big)
    draw.polygon(points, fill=accent + (255,))
    inner = radius * 0.8 * S
    draw.ellipse((side * S / 2 - inner, side * S / 2 - inner, side * S / 2 + inner, side * S / 2 + inner), outline=outline + (200,), width=max(1, round(unit * 0.004 * S)))
    label = big.resize((side, side), Image.LANCZOS)
    _lines(ImageDraw.Draw(label), lines, font, label_ink, 0, (side - text_h) / 2, line_height, side)
    return _lift(label.rotate(10, resample=Image.BICUBIC, expand=True), unit)


def _block(text: dict, style: dict, ink: dict, unit: float, width: int):
    """The texts as one transparent picture `width` wide: bar, headline, rule, list, label. `ink` is what `_paint` chose."""
    accent, label_ink = ink["accent"], ink["label_ink"]
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
    specs_right = 0.0
    for spec in text["specs"]:
        bullets.append(y + spec_rise / 2)
        for line in _wrap(spec, spec_font, width - indent, 2)[0]:
            steps.append((line, spec_font, ink["soft"], indent, y + spec_rise))
            specs_right = max(specs_right, indent + spec_font.getlength(line))
            y += spec_font.size * 1.38
    y += unit * 0.026
    label = _label(text["extra_text"], ink["label"], accent, label_ink, unit, width, outline=ink["ink"])
    # the sticker goes beside the list, from the rule down, where there is room for it: under the list it would make the whole block smaller
    gap = unit * 0.06
    beside = ink["label"] == "burst" and specs_right + gap + label.width <= width
    if beside:
        left = round(specs_right + gap)
        clear = left >= head_font.getlength(head[-1]) + gap                        # the last line of the headline ends before it
        at = (left, round(max(0, rules[0] - (label.height * 0.35 if clear else unit * 0.012))))     # never over the headline
        height = max(y, at[1] + label.height)
    else:
        at = (0, round(y))
        height = y + label.height
    block = Image.new("RGBA", (width, round(height) + 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(block)
    draw.rectangle((0, 0, bar[0], bar[1]), fill=accent)
    for top in rules:
        draw.rectangle((0, top, min(width, unit * 0.46), top + max(1, round(unit * 0.003))), fill=ink["ink"] + (120,))
    for line, font, colour, x, baseline in steps:
        draw.text((x, baseline), line, font=font, fill=colour, anchor="ls")
    side = spec_font.size * 0.3
    for middle in bullets:                                           # drawn, so a bullet never depends on a glyph
        draw.rectangle((0, middle - side / 2, side, middle + side / 2), fill=accent)
    block.alpha_composite(label, at)
    return block


def _fitting(text: dict, style: dict, ink: dict, base: int, width: int, limit: float):
    for scale in SCALES:
        block = _block(text, style, ink, base * scale, width)
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


def _shade(image, ink: dict, mask) -> None:
    colour = Image.new("RGBA", image.size, ink["shade"] + (255,))
    colour.putalpha(mask)
    image.alpha_composite(colour)


def _place(image, block, position: tuple, tone: str, unit: int) -> None:
    """The texts on the picture; on a dark picture with a soft shadow, which keeps white letters sharp on a pale spot."""
    if tone == "dark":
        shadow = Image.new("RGBA", block.size, (0, 0, 0, 0))
        shadow.putalpha(block.getchannel("A").filter(ImageFilter.GaussianBlur(max(1, unit * 0.008))).point(lambda v: v * 150 // 255))
        image.alpha_composite(shadow, (position[0], position[1] + max(1, round(unit * 0.004))))
    image.alpha_composite(block, position)


def _bottom(image, style: dict, text: dict, look: "dict | None") -> None:
    """The texts along the bottom, left-aligned; the picture darkens (or lightens) towards them."""
    width, height = image.size
    base = min(width, height)
    pad = round(base * 0.055)
    ink = _paint(style, _tone(image, (0, height * 0.6, width, height)), look)
    block = _fitting(text, style, ink, base, min(width - 2 * pad, round(width * 0.9)), height * 0.48)
    top = height - pad - block.height
    column = Image.new("L", (1, height))
    column.putdata(_ramp(height, top - base * 0.34, top + base * 0.08, ink["strength"]))
    _shade(image, ink, column.resize((width, height)))
    _place(image, block, (pad, top), ink["tone"], base)


def _left(image, style: dict, text: dict, look: "dict | None") -> None:
    """The texts in the left part of a wide picture; the picture darkens (or lightens) towards the left."""
    width, height = image.size
    base = min(width, height)
    pad = round(base * 0.055)
    ink = _paint(style, _tone(image, (0, 0, width * 0.45, height)), look)
    block = _fitting(text, style, ink, base, round(width * 0.4), height * 0.7)
    row = Image.new("L", (width, 1))                                  # full on the left, gone at 68% of the width
    row.putdata(_ramp(width, width * 0.32, width * 0.62, ink["strength"])[::-1])
    _shade(image, ink, row.resize((width, height)))
    _place(image, block, (pad, height - pad - block.height), ink["tone"], base)


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


def _code(rgb: tuple) -> str:
    return "#%02x%02x%02x" % tuple(rgb[:3])


def palette() -> dict:
    """The templates as the screen needs them to draw an example of a poster: per purpose the accent and the ink on the label for a dark
    and a light photo, the ink and the shade of the texts for each tone, where the texts go per shape, and the label shapes."""
    return {"accents": {name: {tone: {"accent": _code(style[tone][0]), "label": _code(style[tone][1])} for tone in ("dark", "light")}
                        for name, style in TEMPLATES.items()},
            "ink": {tone: {"ink": _code(INK[tone]["ink"]), "shade": _code(INK[tone]["shade"])} for tone in INK},
            "layouts": dict(LAYOUTS), "label_styles": list(LABEL_STYLES)}


def compose(content: bytes, purpose: str, variant: str, *, text: "dict | None" = None, logo: "bytes | None" = None, look: "dict | None" = None) -> bytes:
    """The picture (a JPEG we wrote ourselves) with the texts of `text` (product_name, specs, extra_text) and the logo on it, as JPEG.
    `look` is what the owner chose for the poster: `text_colour` and `accent_colour` (`#rrggbb`, empty for the template's) and `label_style`."""
    with Image.open(BytesIO(content)) as opened:
        image = opened.convert("RGBA")
    if text:
        {"bottom": _bottom, "left": _left}[LAYOUTS[variant]](image, TEMPLATES[purpose], text, look)
    if logo:
        _logo(image, logo)
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()
