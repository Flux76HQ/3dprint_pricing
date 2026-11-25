"""What is on the shelf, per kind of filament: the rolls of one kind add up, whatever their barcodes are.

Two rolls are **one kind** when they share a barcode **or** are the same filament by name: brand, type, material, colour and diameter. So the
refill and the roll with spool of one colour, which the shop gives a barcode each, are one kind in stock, and so are two spellings of one barcode.
A kind is the group of rolls that these two links connect (`Kinds`)."""
from decimal import Decimal, InvalidOperation

STANDARD = "1.75"                             # the diameter that is left out of a name key: it is what nearly every roll has


def _diameter(row) -> str:
    """The diameter as a plain number ('1.75', also for Decimal('1.750')); a row that does not say has the standard one."""
    value = row["diameter_mm"] if "diameter_mm" in row.keys() else None
    if value in (None, ""):
        return STANDARD
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except InvalidOperation:
        return str(value).strip()


def _name(row) -> str:
    """What makes two rolls the same filament without a barcode: brand, type, material and colour (case and spaces do not matter), and the
    diameter when it is not the standard one (1.75 and 2.85 mm are never one kind). The standard diameter is left out so that the key of a kind
    without a barcode is what it always was, which keeps a "nearly empty" announcement from being sent twice."""
    parts = [(row[k] or "").strip().lower() for k in ("brand", "product_type", "material", "colour")]
    diameter = _diameter(row)
    return "|".join(parts if diameter == STANDARD else [*parts, diameter])


def _code(row) -> str:
    return (row["barcode"] or "").strip()


def key_of(row: dict) -> str:
    """The kind of one roll on its own (see `Kinds` for a roll among others): the barcode when there is one, otherwise the name."""
    return f"barcode:{_code(row)}" if _code(row) else f"name:{_name(row)}"


class Kinds:
    """The kinds in a set of rolls: rolls that share a barcode, or are the same filament by name and diameter, are one kind. A kind is called
    `barcode:<the smallest of its barcodes>` when any roll has one (so a kind with one barcode keeps the key it has always had), else `name:...`.
    Built once from the rolls (`rows`, each with brand, type, material, colour, diameter and barcode); `key(row)` answers for any roll, also one that
    is not among them (an archived roll that a calculation still names): the kind it would be part of, or its own."""

    def __init__(self, rows=()):
        self._parent: dict = {}
        for row in rows:
            tokens = self._tokens(row)
            first = self._find(tokens[0])
            for token in tokens[1:]:
                self._parent[self._find(token)] = first
        codes: dict = {}                                           # per kind: its barcodes
        for token in list(self._parent):
            if token[0] == "b":
                codes.setdefault(self._find(token), []).append(token[1])
        roots = {self._find(token) for token in list(self._parent)}
        self._keys = {root: f"barcode:{min(codes[root])}" if root in codes else f"name:{root[1]}" for root in roots}

    @staticmethod
    def _tokens(row) -> list:
        """The two things that tie a roll to others: its barcode (if any) and its name; the one that decides the kind's key is the barcode."""
        code = _code(row)
        return [*([("b", code)] if code else []), ("n", _name(row))]

    def _find(self, token):
        self._parent.setdefault(token, token)
        root = token
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[token] != root:                         # the path is flattened
            self._parent[token], token = root, self._parent[token]
        return root

    def known(self, row) -> bool:
        """Whether this roll's barcode or name is among those of the rolls this was made from."""
        return any(token in self._parent for token in self._tokens(row))

    def key(self, row) -> str:
        """The key of the kind this roll is part of; the barcode decides when the roll has two matches, and a roll that matches none is a kind of its own."""
        for token in self._tokens(row):
            if token in self._parent:
                return self._keys[self._find(token)]
        return key_of(row)


def groups(rows) -> list[dict]:
    """Per kind of filament: the rolls that still have filament on them (with their weights) and the total.

    Archived rolls are not stock. A roll that is empty is not a roll you still have, but its kind stays in
    the list with 0 g so a sold-out colour does not just vanish. `notify_low` is on when any roll of the kind has it on.
    `spool_ids` names every roll of the kind (a calculation line points at one of them and means the kind).

    The rolls of a kind may be in different groups (the bins and shelves of `filament_groups`): `groups` names every group a roll of the kind is in
    (empty rolls too, none for a roll out of any group), and `by_group` says what is in each one (`""` for the rolls out of any group; keyed on the
    name in lower case, the way groups are found): its rolls, their number and the grams, so a list filtered on a group shows what is *there*."""
    rows = list(rows)
    kinds = Kinds(rows)
    found: dict[str, dict] = {}
    for row in rows:
        key = kinds.key(row)
        group = found.setdefault(key, {
            "key": key, "brand": row["brand"], "product_type": row["product_type"] or "", "material": row["material"] or "", "colour": row["colour"] or "",
            "colour_hex": row["colour_hex"] or "", "barcode": "", "barcodes": [], "rolls": [], "spool_ids": [], "remaining_g": Decimal(0),
            "notify_low": False, "groups": [], "by_group": {}})
        if _code(row) and _code(row) not in group["barcodes"]:
            group["barcodes"].append(_code(row))                                         # every barcode of the kind: a refill and a roll with spool have one each
        group["spool_ids"].append(str(row["id"]))                                     # every roll of the kind, the empty ones too
        group["notify_low"] = group["notify_low"] or bool(row["notify_low"])
        group["colour_hex"] = group["colour_hex"] or row["colour_hex"] or ""          # the first roll that has a colour gives the kind its colour
        name = (row["group_name"] or "").strip() if "group_name" in row.keys() else ""
        here = group["by_group"].setdefault(name.lower(), {"group": name, "rolls": [], "remaining_g": Decimal(0)})
        if name and name not in group["groups"]:
            group["groups"].append(name)
        if row["remaining_g"] > 0:
            roll = {"id": str(row["id"]), "remaining_g": str(row["remaining_g"]), "roll_weight_g": str(row["roll_weight_g"]), "group": name}
            group["rolls"].append(roll)
            group["remaining_g"] += row["remaining_g"]
            here["rolls"].append(roll)
            here["remaining_g"] += row["remaining_g"]
    out = []
    for group in found.values():
        group["barcodes"].sort()
        group["barcode"] = group["barcodes"][0] if group["barcodes"] else ""             # the one the kind is called by
        group["roll_count"] = len(group["rolls"])
        group["remaining_g"] = str(group["remaining_g"])
        group["groups"].sort(key=str.lower)
        for here in group["by_group"].values():
            here["roll_count"] = len(here["rolls"])
            here["remaining_g"] = str(here["remaining_g"])
        out.append(group)
    return sorted(out, key=lambda g: ((g["material"] or "~").lower(), g["brand"].lower(), g["product_type"].lower(), g["colour"].lower()))


def fetch(conn, barcode: str | None = None):
    """The rolls that count as stock (not archived), optionally only those with this barcode."""
    sql = ("SELECT s.id, s.brand, s.product_type, s.material, s.colour, s.colour_hex, s.barcode, s.diameter_mm, s.roll_weight_g, s.remaining_g, s.notify_low, s.bambu_id, "
           "COALESCE(g.name, '') AS group_name FROM filament_spools s LEFT JOIN filament_groups g ON g.id = s.group_id WHERE NOT s.archived")
    params: tuple = ()
    if barcode is not None:
        sql, params = sql + " AND s.barcode = %s", (barcode,)
    return conn.execute(sql + " ORDER BY s.created_at", params).fetchall()


def group_of(conn, values: dict) -> "dict | None":
    """The kind in stock that a barcode or a filament belongs to (`values`: its barcode, brand, type, material, colour and diameter, as a roll or a
    library entry has them), with all its rolls: the ones with this barcode and the ones that are the same filament under another barcode. None when no roll
    of it is in stock, not even an empty one."""
    rows = fetch(conn)
    kinds = Kinds(rows)
    if not kinds.known(values):
        return None
    key = kinds.key(values)
    return next((g for g in groups(rows) if g["key"] == key), None)
