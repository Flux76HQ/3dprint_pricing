"""Whether a Dutch and an English colour name are the same colour ("Geel" and "Yellow", "Basic Lichtgrijs" and "Light Gray").

The filament library and the rolls carry the names of the Dutch web shop ("Bamboegroen", "Pompoenoranje"); SpoolmanDB (`spoolmandb.py`) and
Spoolman carry English ones. Without this, picking a filament from SpoolmanDB would add a second entry next to the one that is already there,
and pushing the library to Spoolman would make a second filament next to the one Spoolman has.

This is deliberately a *looser* comparison than `filament_library.keys`, which stays exact: restoring a backup refuses a library in which
`keys` sees two entries of one filament, so teaching `keys` that "Geel" is "Yellow" would make a backup that has both unrestorable. The
loose comparison is only used where something is being *added* (`filament_library.add_roll`, the picker's "already have this" mark,
`spoolman._same`), where finding the entry that exists is worth more than telling it from an English twin.

A name is turned into a bag of words, each Dutch word into its English one, so the order does not matter ("Blauw Grijs" is "Gray Blue").
A Dutch compound is split at a colour it ends in ("pompoenoranje" is "pumpkin" + "orange"). A word that is not known stays as it is, so an
unknown Dutch name never matches by accident; it only fails to be recognised.
"""
import re
import unicodedata
from decimal import Decimal

# The colours, Dutch -> English as SpoolmanDB spells them ("gray", not "grey").
COLOURS = {
    "zwart": "black", "wit": "white", "rood": "red", "blauw": "blue", "groen": "green", "geel": "yellow", "oranje": "orange",
    "paars": "purple", "roze": "pink", "bruin": "brown", "grijs": "gray", "zilver": "silver", "goud": "gold", "koper": "copper",
    "brons": "bronze", "cyaan": "cyan", "turkoois": "turquoise", "lila": "lilac", "pruim": "plum", "transparant": "clear",
    "doorzichtig": "clear", "naturel": "natural", "ivoor": "ivory", "bordeaux": "burgundy", "marineblauw": "navy blue",
    "limoen": "lime", "creme": "cream", "zand": "sand", "antraciet": "charcoal",
}
# What a Dutch compound can start with ("lichtgrijs", "pompoenoranje"): a word that is not itself a colour.
MODIFIERS = {
    "licht": "light", "donker": "dark", "helder": "bright", "pompoen": "pumpkin", "zonnebloem": "sunflower", "bamboe": "bamboo",
    "maretak": "mistletoe", "jade": "jade", "gras": "grass", "appel": "apple", "citroen": "lemon", "mandarijn": "mandarin",
    "kers": "cherry", "bos": "forest", "olijf": "olive", "lucht": "sky", "hemel": "sky", "oceaan": "ocean", "zee": "sea",
    "meer": "lake", "steen": "stone", "as": "ash", "koraal": "coral", "vuur": "fire", "wijn": "wine", "chocolade": "chocolate",
}
# Words that are spelled differently in English, or by one shop ("Bambu Green" is Bambu Lab's "Bamboo Green"; "lite" is "light").
SAME = {"grey": "gray", "bambu": "bamboo", "lite": "light"}
# A word that tells nothing about the colour and is left out: Bambu Lab sells its standard line as "Basic" (SpoolmanDB leaves it out of the name).
NOISE = {"basic"}

_SPLIT = re.compile(r"[^a-z0-9+]+")
_BASES = sorted(COLOURS, key=len, reverse=True)           # the longest first: "marineblauw" before "blauw"


def _fold(text) -> str:
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()


def _dutch(word: str) -> "list[str] | None":
    """The English words a Dutch colour word or compound stands for ("pompoenoranje": pumpkin, orange), None when it is not one."""
    if word in COLOURS:
        return COLOURS[word].split()
    for base in _BASES:
        head = word[:-len(base)]
        if word.endswith(base) and head:
            if head in MODIFIERS:
                return [MODIFIERS[head], *COLOURS[base].split()]
            if head in COLOURS:                             # "blauwgrijs"
                return [*COLOURS[head].split(), *COLOURS[base].split()]
    return None


def _word(word: str) -> list[str]:
    """One word as English words, for comparing: itself, or what a Dutch word or compound stands for."""
    if word in NOISE:
        return []
    if word in SAME:
        return [SAME[word]]
    return _dutch(word) or [word]


_LETTERS = re.compile(r"[^\W\d_]+")                              # a run of letters, accented ones too


def to_english(text) -> str:
    """A Dutch colour name in English, word by word and in the same order, with capitals: "Bamboegroen" is "Bamboo Green", "Lila paars" is "Lilac Purple",
    "Matte Pruim" is "Matte Plum". What is already English, and every word that is not a known Dutch one, stays exactly as it is (so an unknown Dutch name is
    kept, never guessed, and translating twice changes nothing). It is what is *stored* when an invoice is imported; `same_name` and `loose_kind` are what
    *recognise* a filament that is already there under a name in either language."""
    def one(found):
        english = _dutch(_fold(found.group(0)))
        return " ".join(w.capitalize() for w in english) if english else found.group(0)
    return _LETTERS.sub(one, str(text or ""))


def words(*parts) -> tuple[str, ...]:
    """The English words a colour name stands for, sorted: what two spellings of one colour have in common."""
    found: list[str] = []
    for token in _SPLIT.split(" ".join(_fold(p) for p in parts)):
        if token:
            found += _word(token)
    return tuple(sorted(found))


def same_name(a, b) -> bool:
    """Whether two colour names (or names with their product line, "Matte Grijs") are one colour, whichever language they are in."""
    found = words(a)
    return bool(found) and found == words(b)


def _num(value) -> str:
    return format(Decimal(str(value)).normalize(), "f") if value not in (None, "") else ""


def loose_kind(values: dict) -> tuple:
    """What a roll says about its filament, with the type and the colour read together and in either language: the loose twin of
    `filament_library._kind` (brand and material in any case, weight and diameter as numbers)."""
    low = lambda key: str(values.get(key) or "").strip().lower()
    return (low("brand"), low("material"), words(values.get("product_type"), values.get("colour")),
            _num(values.get("roll_weight_g")), _num(values.get("diameter_mm")))
