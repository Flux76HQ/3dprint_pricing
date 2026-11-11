"""The fixed templates that turn a generated picture into a poster: the product texts and the logo, drawn here.

The model is asked for a picture *without* text (it cannot be trusted to spell) and to keep part of it calm; the texts are then
drawn by this module, so they are exactly what was typed. A poster has one loud thing and the rest is quiet, so the template is a
short accent bar, the product name as a large headline in capitals, the specifications as a plain list under it and the extra text on
a tilted label. Only one picture of the four is made a poster (the others stay photos, so a carousel is not four times the same
text). Where the block goes depends on the shape of the picture (`LAYOUTS`): a slanted colour field rising across the bottom (`wedge`), the picture fading into the colour (`ground`), or a slanted
column on the left of a wide picture (`side`). Each purpose has its own colours (`TEMPLATES`). Nothing here is random: the same
texts on the same picture give the same poster. Sizes follow the picture, and a text that does not fit is made smaller, then cut."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).parent / "fonts"
# purpose -> the colour field (with its opacity), the headline, the list, the accent (bar, bullets, label) and the text on the label
TEMPLATES = {
    "marktplaats": {"panel": (250, 248, 244), "alpha": 242, "ink": (24, 24, 27), "soft": (63, 63, 70), "accent": (234, 88, 12), "accent_ink": (255, 255, 255)},
    "social": {"panel": (14, 14, 17), "alpha": 236, "ink": (255, 255, 255), "soft": (228, 228, 231), "accent": (250, 204, 21), "accent_ink": (24, 24, 27)},
    "webshop": {"panel": (255, 255, 255), "alpha": 242, "ink": (15, 23, 42), "soft": (51, 65, 85), "accent": (37, 99, 235), "accent_ink": (255, 255, 255)},
}
# shape of the picture -> where the texts go
LAYOUTS = {"square": "wedge", "portrait": "wedge", "context": "wedge", "studio": "ground", "detail": "ground", "landscape": "side"}
# what the model is told, so that the object is not where the texts come
ROOM = {
    "wedge": "Compose the picture so that the object sits in the upper part and the bottom third stays calm and uncluttered: a caption is put there afterwards. ",
    "ground": "Compose the picture so that the object sits in the upper part and the bottom third stays calm and uncluttered: a caption is put there afterwards. ",
    "side": "Compose the picture so that the object sits in the right half and the left 40% stays calm and uncluttered: a caption is put there afterwards. ",
}
HEADLINE = (0.094, 0.082, 0.072, 0.063, 0.055, 0.048)     # sizes tried for the headline, largest first (times the unit)
SCALES = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)                   # the whole block is made smaller, step by step, until it fits its field
SMOOTH = 3                                                # slanted edges are drawn this much larger and scaled down, so they are not jagged
TILT = 3                                                  # degrees the label leans


def room(variant: str) -> str:
    return ROOM[LAYOUTS[variant]]


def _font(bold: bool, size: float):
    return ImageFont.truetype(str(FONTS / ("OpenSans-Bold.ttf" if bold else "OpenSans-Regular.ttf")), max(8, round(size)))


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
        while last and font.getlength(last + "…") > width:
            last = last[:-1]
        lines = lines[:max_lines - 1] + [last.rstrip() + "…"]
    return lines, damaged


def _label(text: str, style: dict, unit: float, width: float):
    """The extra text on a slanted, slightly tilted label of the accent colour."""
    font = _font(True, unit * 0.04)
    pad_x, pad_y, lean = unit * 0.03, unit * 0.014, unit * 0.022
    lines, _ = _wrap(text, font, width * 0.93 - 2 * pad_x - lean, 2)
    line_height = font.size * 1.25
    w = round(max(font.getlength(line) for line in lines) + 2 * pad_x + lean)
    h = round(len(lines) * line_height + 2 * pad_y)
    big = Image.new("RGBA", (w * SMOOTH, h * SMOOTH), (0, 0, 0, 0))
    ImageDraw.Draw(big).polygon([(lean * SMOOTH, 0), (w * SMOOTH, 0), ((w - lean) * SMOOTH, h * SMOOTH), (0, h * SMOOTH)], fill=style["accent"] + (255,))
    label = big.resize((w, h), Image.LANCZOS)
    draw = ImageDraw.Draw(label)
    for n, line in enumerate(lines):
        draw.text((pad_x + lean / 2, pad_y + n * line_height + line_height / 2), line, font=font, fill=style["accent_ink"], anchor="lm")
    return label.rotate(TILT, resample=Image.BICUBIC, expand=True)


def _block(text: dict, style: dict, unit: float, width: int):
    """The texts as one transparent picture `width` wide: bar, headline, list, label."""
    steps, y = [], 0.0
    bar = (unit * 0.12, unit * 0.016)
    y += bar[1] + unit * 0.03
    name = text["product_name"].upper()
    for size in HEADLINE:                                            # the largest size at which the name fits whole
        head_font = _font(True, unit * size)
        head, damaged = _wrap(name, head_font, width, 3)
        if not damaged:
            break
    for line in head:
        steps.append((line, head_font, style["ink"], 0, y))
        y += head_font.size * 1.06
    y += unit * 0.026
    spec_font = _font(False, unit * 0.035)
    indent, bullets = unit * 0.04, []
    for spec in text["specs"]:
        bullets.append(y + spec_font.size * 0.7)
        for line in _wrap(spec, spec_font, width - indent, 2)[0]:
            steps.append((line, spec_font, style["soft"], indent, y))
            y += spec_font.size * 1.36
    y += unit * 0.03
    label = _label(text["extra_text"], style, unit, width)
    block = Image.new("RGBA", (width, round(y + label.height) + 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(block)
    draw.rectangle((0, 0, bar[0], bar[1]), fill=style["accent"])
    for line, font, colour, x, top in steps:
        draw.text((x, top), line, font=font, fill=colour)
    side = spec_font.size * 0.3
    for middle in bullets:                                           # drawn, so a bullet never depends on a glyph
        draw.rectangle((0, middle - side / 2, side, middle + side / 2), fill=style["accent"])
    block.alpha_composite(label, (0, round(y)))
    return block


def _fitting(text: dict, style: dict, base: int, width: int, limit: float):
    for scale in SCALES:
        block = _block(text, style, base * scale, width)
        if block.height <= limit:
            break
    return block


def _fields(image, *fields) -> None:
    """Colour fields with slanted edges, (points, colour with opacity) each, smooth."""
    width, height = image.size
    big = Image.new("RGBA", (width * SMOOTH, height * SMOOTH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    for points, colour in fields:
        draw.polygon([(x * SMOOTH, y * SMOOTH) for x, y in points], fill=colour)
    image.alpha_composite(big.resize(image.size, Image.LANCZOS))


def _wedge(image, style: dict, text: dict) -> None:
    """A colour field across the bottom whose top edge rises to the right, with the accent along it."""
    width, height = image.size
    base = min(width, height)
    pad, rise, stripe = round(base * 0.05), round(height * 0.085), max(3, round(base * 0.011))
    block = _fitting(text, style, base, width - 2 * pad, height * 0.44)
    top = height - pad - block.height
    left, right = top - pad, top - pad - rise
    _fields(image,
            ([(0, left), (width, right), (width, height), (0, height)], style["panel"] + (style["alpha"],)),
            ([(0, left - stripe), (width, right - stripe), (width, right), (0, left)], style["accent"] + (255,)))
    image.alpha_composite(block, (pad, top))


def _ground(image, style: dict, text: dict) -> None:
    """The picture fades into the colour towards the bottom; the texts stand in it."""
    width, height = image.size
    base = min(width, height)
    pad = round(base * 0.05)
    block = _fitting(text, style, base, width - 2 * pad, height * 0.46)
    top = height - pad - block.height
    fade, solid = round(base * 0.2), max(0, top - pad // 2)
    mask = Image.new("L", image.size, 0)
    ramp = Image.linear_gradient("L").resize((width, fade)).point(lambda v: v * style["alpha"] // 255)
    mask.paste(ramp, (0, solid - fade))
    mask.paste(style["alpha"], (0, solid, width, height))
    colour = Image.new("RGBA", image.size, style["panel"] + (255,))
    colour.putalpha(mask)
    image.alpha_composite(colour)
    image.alpha_composite(block, (pad, top))


def _side(image, style: dict, text: dict) -> None:
    """A column on the left whose right edge leans, with the accent along it; for a wide picture."""
    width, height = image.size
    base = min(width, height)
    pad, column, lean, stripe = round(base * 0.05), round(width * 0.47), round(width * 0.075), max(3, round(base * 0.011))
    block = _fitting(text, style, base, column - lean - 2 * pad, height * 0.68)
    _fields(image,
            ([(0, 0), (column, 0), (column - lean, height), (0, height)], style["panel"] + (style["alpha"],)),
            ([(column, 0), (column + stripe, 0), (column - lean + stripe, height), (column - lean, height)], style["accent"] + (255,)))
    image.alpha_composite(block, (pad, height - pad - block.height))


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
        {"wedge": _wedge, "ground": _ground, "side": _side}[LAYOUTS[variant]](image, TEMPLATES[purpose], text)
    if logo:
        _logo(image, logo)
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()
