"""The template of invoice numbers: a prefix of the owner's choosing, optionally the year, and a running number.

`FLX-{JJJJ}-{NNNN}` gives FLX-2026-0001, FLX-2026-0002, ... and starts again at 1 in the next year. Without a year token the
number just keeps counting. The number of N's is the minimum number of digits (`{NNNN}` -> 0007)."""
import re
from datetime import date

from .http import ApiError

DEFAULT = "{JJJJ}-{NNNN}"
MAX_LENGTH = 40

_TOKEN = re.compile(r"\{([A-Za-z]+)\}")
_YEAR4, _YEAR2 = ("JJJJ", "YYYY"), ("JJ", "YY")
_LITERAL = re.compile(r"[A-Za-z0-9._/ -]*")      # what may stand around the tokens: safe in a file name and in a bank reference


def _split(template: str):
    """The template as a list of ('text', s) / ('year4',) / ('year2',) / ('seq', digits); None when it is not valid."""
    parts, position, sequences = [], 0, 0
    for match in _TOKEN.finditer(template):
        parts.append(("text", template[position:match.start()]))
        name = match.group(1).upper()
        if name in _YEAR4:
            parts.append(("year4",))
        elif name in _YEAR2:
            parts.append(("year2",))
        elif set(name) == {"N"} and len(name) <= 9:
            parts.append(("seq", len(name)))
            sequences += 1
        else:
            return None
        position = match.end()
    parts.append(("text", template[position:]))
    if sequences != 1 or any(p[0] == "text" and not _LITERAL.fullmatch(p[1]) for p in parts):
        return None
    return parts


def validate(value) -> str:
    """The template as it is saved (empty means the default); an ApiError when it cannot be used."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT
    if not isinstance(value, str) or len(value.strip()) > MAX_LENGTH or _split(value.strip()) is None:
        raise ApiError(400, "err.invoice_number_format")
    return value.strip()


def uses_year(template: str) -> bool:
    parts = _split(template) or []
    return any(p[0] in ("year4", "year2") for p in parts)


def render(template: str, year: int, sequence: int) -> str:
    parts = _split(template) or _split(DEFAULT)
    out = []
    for part in parts:
        if part[0] == "text":
            out.append(part[1])
        elif part[0] == "year4":
            out.append(f"{year:04d}")
        elif part[0] == "year2":
            out.append(f"{year % 100:02d}")
        else:
            out.append(f"{sequence:0{part[1]}d}")
    return "".join(out)


def example(template: str) -> str:
    return render(template, date.today().year, 1)
