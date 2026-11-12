"""Read what a print file can tell us.

* A **sliced 3MF** (Bambu Studio / Orca "export sliced file") carries the slicer's own numbers:
  filament used per material and the predicted print time. Those are exact.
* An **STL**, or a 3MF that was never sliced, only has geometry. We can measure its volume and
  *estimate* the filament weight from a density and an effective fill; the print time cannot be
  derived from geometry, so it is left empty rather than guessed.

Files are untrusted: XML goes through defusedxml, zips are size-capped before reading, and every
malformed input becomes a PrintFileError with a message the user can act on.
"""
import io
import json
import math
import sys
import re
import struct
import zipfile
from array import array
from pathlib import Path

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as ET

from .i18n import Localized

MAX_UNZIPPED_BYTES = 400 * 1024 * 1024
MAX_TRIANGLES = 5_000_000
MAX_VIEW_TRIANGLES = 400_000          # what the browser is given to draw: 36 bytes each (40 with a colour), so at most about 16 MB
MAX_COLOURS = 256                     # colours read from one group of materials, or filaments of one project
MAX_SETTINGS_BYTES = 8 * 1024 * 1024  # a slicer's settings file that is read for the filament colours
MAX_PAINT_DIGITS = 20_000            # of one triangle's painted-on colours
PAINT_ATTRIBUTES = ("paint_color", "mmu_segmentation")      # Bambu Studio / OrcaSlicer, PrusaSlicer
MAX_PICTURE_BYTES = 16 * 1024 * 1024  # the slicer's picture of a plate
MAX_PLATES = 64                       # build plates of one project that are listed
MESH_MAGIC = b"PPM1"
NO_COLOUR = b"\x00\x00\x00\x00"

DENSITIES = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PA": 1.14, "PC": 1.20}
UNIT_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}


class PrintFileError(Localized):
    pass


def estimate_grams(volume_cm3: float, density: float, fill_pct: float) -> float:
    """Solid volume x density x effective fill (walls + infill as a share of solid)."""
    return round(volume_cm3 * density * fill_pct / 100, 1)


# --- geometry -----------------------------------------------------------------------

class _Mesh:
    """Signed-volume accumulator plus bounding box."""

    def __init__(self):
        self.volume6 = 0.0
        self.lo = [math.inf] * 3
        self.hi = [-math.inf] * 3
        self.triangles = 0

    def add(self, a, b, c):
        self.triangles += 1
        if self.triangles > MAX_TRIANGLES:
            raise PrintFileError("pf.too_many_triangles")
        self.volume6 += (a[0] * (b[1] * c[2] - b[2] * c[1])
                         - a[1] * (b[0] * c[2] - b[2] * c[0])
                         + a[2] * (b[0] * c[1] - b[1] * c[0]))
        for p in (a, b, c):
            for i in range(3):
                if p[i] < self.lo[i]:
                    self.lo[i] = p[i]
                if p[i] > self.hi[i]:
                    self.hi[i] = p[i]

    @property
    def volume(self) -> float:
        return abs(self.volume6) / 6


def _finite(values) -> bool:
    return all(math.isfinite(v) for v in values)


def stl_geometry(data: bytes) -> _Mesh:
    mesh = _Mesh()
    binary = False
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        binary = len(data) == 84 + 50 * count
    if binary:
        for rec in struct.iter_unpack("<12fH", memoryview(data)[84:]):
            if not _finite(rec[3:12]):
                raise PrintFileError("pf.stl_bad_coords")
            mesh.add(rec[3:6], rec[6:9], rec[9:12])
    else:
        text = data.decode("utf-8", errors="ignore")
        if not text.lstrip().lower().startswith("solid"):
            raise PrintFileError("pf.stl_invalid")
        coords = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
        try:
            pts = [tuple(float(v) for v in c) for c in coords]
        except ValueError:
            raise PrintFileError("pf.ascii_bad_coords") from None
        if len(pts) % 3:
            raise PrintFileError("pf.ascii_incomplete")
        for i in range(0, len(pts), 3):
            if not _finite(pts[i] + pts[i + 1] + pts[i + 2]):
                raise PrintFileError("pf.stl_bad_coords")
            mesh.add(pts[i], pts[i + 1], pts[i + 2])
    if mesh.triangles == 0 or mesh.volume == 0:
        raise PrintFileError("pf.stl_no_volume")
    return mesh


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el, name):
    """Attribute by local name: 3MF production-extension attributes carry a namespace."""
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return None


def _transform(text):
    if not text:
        return None
    try:
        m = [float(v) for v in text.split()]
    except ValueError:
        raise PrintFileError("pf.transform_invalid") from None
    if len(m) != 12 or not _finite(m):
        raise PrintFileError("pf.transform_invalid")
    return m


def _det(m):
    if m is None:
        return 1.0
    return (m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6])
            + m[2] * (m[3] * m[7] - m[4] * m[6]))


def _apply(m, p):
    if m is None:
        return p
    return (p[0] * m[0] + p[1] * m[3] + p[2] * m[6] + m[9],
            p[0] * m[1] + p[1] * m[4] + p[2] * m[7] + m[10],
            p[0] * m[2] + p[1] * m[5] + p[2] * m[8] + m[11])


def _parse_model_file(stream, keep: bool = False):
    """Return (unit_scale, {object_id: object}, [build items]) for one .model XML file. With `keep` every object also carries its
    triangles (`tris`: nine numbers each, in the object's own coordinates), for drawing, and their colours where the file names
    one (`cols`: red, green, blue and 255 per triangle, or four zeros for "none"); at most MAX_VIEW_TRIANGLES per file. A colour
    comes from the 3MF's own materials (`basematerials`, or a `colorgroup` of the materials extension), per triangle or per object."""
    unit, objects, items = 1.0, {}, []
    groups, group = {}, None                                             # property group id -> its colours, and the one being read
    current = None
    kept = 0
    verts = array("d")
    for event, el in ET.iterparse(stream, events=("start", "end")):
        name = _local(el.tag)
        if event == "start":
            if name == "model":
                unit = UNIT_MM.get(el.get("unit", "millimeter"), 1.0)
            elif name == "object":
                current = {"id": el.get("id"), "type": el.get("type", "model"), "mesh": _Mesh(), "components": [], "tris": array("f"),
                           "cols": bytearray(), "paint": bytearray(), "pid": el.get("pid"), "pindex": el.get("pindex") or "0"}
                verts = array("d")
            elif name in ("basematerials", "colorgroup"):
                group = groups.setdefault(el.get("id"), [])
            continue
        if name in ("base", "color") and group is not None:
            if len(group) < MAX_COLOURS:
                group.append(_rgb(el.get("displaycolor") if name == "base" else el.get("color")))
            el.clear()
            continue
        if name in ("basematerials", "colorgroup"):
            group = None
            continue
        if name == "vertex":
            try:
                verts.extend((float(el.get("x")), float(el.get("y")), float(el.get("z"))))
            except (TypeError, ValueError):
                raise PrintFileError("pf.vertex_invalid") from None
            el.clear()
        elif name == "triangle" and current is not None:
            try:
                i, j, k = int(el.get("v1")), int(el.get("v2")), int(el.get("v3"))
                a, b, c = verts[3 * i:3 * i + 3], verts[3 * j:3 * j + 3], verts[3 * k:3 * k + 3]
                current["mesh"].add(a, b, c)
                if keep:
                    if len(a) != 3 or len(b) != 3 or len(c) != 3 or min(i, j, k) < 0:
                        raise ValueError
                    kept += 1
                    if kept > MAX_VIEW_TRIANGLES:
                        raise PrintFileError("pf.too_detailed", max=MAX_VIEW_TRIANGLES)
                    current["tris"].extend((*a, *b, *c))
                    # the triangle's own material, else the object's; a file may point at one that is not there
                    listed = groups.get(el.get("pid") or current["pid"]) or ()
                    at = el.get("p1") if el.get("pid") else current["pindex"]
                    at = int(at) if at is not None and str(at).isdigit() else -1
                    current["cols"].extend((*listed[at], 255) if 0 <= at < len(listed) and listed[at] else NO_COLOUR)
                    current["paint"].append(_painted(next((v for k, v in el.attrib.items() if _local(k) in PAINT_ATTRIBUTES), "")))
            except PrintFileError:
                raise
            except (TypeError, ValueError):
                raise PrintFileError("pf.triangle_invalid") from None
            el.clear()
        elif name == "component" and current is not None:
            current["components"].append((_attr(el, "path"), el.get("objectid"), _transform(el.get("transform"))))
        elif name == "object" and current is not None:
            objects[current["id"]] = current
            current = None
        elif name == "item":
            items.append((el.get("objectid"), _transform(el.get("transform"))))
    return unit, objects, items


def threemf_geometry(zf: zipfile.ZipFile):
    """Total volume (cm^3) and bounding box (mm) of everything on the build plate, or None."""
    main = "3D/3dmodel.model"
    if main not in zf.namelist():
        return None
    parsed = {}

    def load(path):
        path = path.lstrip("/")
        if path not in parsed:
            if path not in zf.namelist():
                raise PrintFileError("pf.missing_file", path=path)
            with zf.open(path) as fh:
                parsed[path] = _parse_model_file(fh)
        return parsed[path]

    def volume(path, oid, depth=0):
        if depth > 8:
            raise PrintFileError("pf.too_deep")
        _, objects, _ = load(path)
        obj = objects.get(oid)
        if obj is None or obj["type"] not in ("model", None):
            return 0.0
        total = obj["mesh"].volume
        for cpath, cid, tr in obj["components"]:
            total += volume(cpath or path, cid, depth + 1) * abs(_det(tr))
        return total

    def corners(path, oid, tr, depth=0):
        _, objects, _ = load(path)
        obj = objects.get(oid)
        if obj is None or depth > 8:
            return []
        pts = []
        mesh = obj["mesh"]
        if mesh.triangles:
            for x in (mesh.lo[0], mesh.hi[0]):
                for y in (mesh.lo[1], mesh.hi[1]):
                    for z in (mesh.lo[2], mesh.hi[2]):
                        pts.append(_apply(tr, (x, y, z)))
        for cpath, cid, ctr in obj["components"]:
            for p in corners(cpath or path, cid, ctr, depth + 1):
                pts.append(_apply(tr, p))
        return pts

    unit, _, items = load(main)
    total, pts = 0.0, []
    for oid, tr in items:
        total += volume(main, oid) * abs(_det(tr))
        pts.extend(corners(main, oid, tr))
    total *= unit ** 3
    if total <= 0:
        return None
    bbox = None
    if pts:
        bbox = [round((max(p[i] for p in pts) - min(p[i] for p in pts)) * unit, 1) for i in range(3)]
    return total / 1000, bbox


# --- the model itself, for drawing -------------------------------------------------------

def _stl_triangles(data: bytes) -> array:
    out = array("f")
    if len(data) >= 84 and len(data) == 84 + 50 * struct.unpack_from("<I", data, 80)[0]:
        if (len(data) - 84) // 50 > MAX_VIEW_TRIANGLES:
            raise PrintFileError("pf.too_detailed", max=MAX_VIEW_TRIANGLES)
        for rec in struct.iter_unpack("<12fH", memoryview(data)[84:]):
            if not _finite(rec[3:12]):
                raise PrintFileError("pf.stl_bad_coords")
            out.extend(rec[3:12])
        return out
    text = data.decode("utf-8", errors="ignore")
    if not text.lstrip().lower().startswith("solid"):
        raise PrintFileError("pf.stl_invalid")
    try:
        values = [float(v) for c in re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text) for v in c]
    except ValueError:
        raise PrintFileError("pf.ascii_bad_coords") from None
    if len(values) % 9:
        raise PrintFileError("pf.ascii_incomplete")
    if len(values) // 9 > MAX_VIEW_TRIANGLES:
        raise PrintFileError("pf.too_detailed", max=MAX_VIEW_TRIANGLES)
    if not _finite(values):
        raise PrintFileError("pf.stl_bad_coords")
    out.extend(values)
    return out


def _painted(code: str) -> int:
    """The filament a triangle is painted with in Bambu Studio, OrcaSlicer or PrusaSlicer (1 is the first), or 0 for "not painted".
    The slicer stores a triangle that is painted in parts as a tree of ever smaller triangles (hex digits, read from the end: the
    low two bits say into how many it is split, the high two the filament of one that is not, with 3 meaning "the next digit, plus
    3"). A triangle is drawn in one colour here, so this gives the filament that covers most of it."""
    if not code or len(code) > MAX_PAINT_DIGITS:
        return 0
    try:
        digits = [int(char, 16) for char in reversed(code)]
    except ValueError:
        return 0
    share, at, todo = {}, 0, [1.0]                                       # the pieces still to read, each with its share of the triangle
    while todo:
        weight = todo.pop()
        if at >= len(digits):
            return 0
        digit, at = digits[at], at + 1
        split = digit & 3
        if split:
            todo.extend([weight / (split + 1)] * (split + 1))
            continue
        state = digit >> 2
        if state == 3:                                                   # filament 3 and up: the following digit(s) count on
            more = 0
            while at < len(digits) and digits[at] == 15:
                more, at = more + 15, at + 1
            if at >= len(digits):
                return 0
            state, at = digits[at] + more + 3, at + 1
        share[state] = share.get(state, 0.0) + weight
    best = max(share, key=share.get)
    return best if 0 <= best <= 255 else 0


def colour_code(text) -> str:
    """A colour as `#rrggbb` in lower case; a slicer may write it with capitals or with a fourth pair for opacity. '' for no colour."""
    rgb = _rgb(text)
    return "#%02x%02x%02x" % rgb if rgb else ""


def _rgb(text) -> "tuple | None":
    """(red, green, blue) of `#RRGGBB` or `#RRGGBBAA`; None for anything else."""
    text = str(text or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", text):
        return None
    return tuple(int(text[at:at + 2], 16) for at in (1, 3, 5))


def _slicer_colours(zf: zipfile.ZipFile) -> "tuple[dict, dict, list]":
    """What Bambu Studio and OrcaSlicer keep next to the model instead of in it: which filament an object and each of its parts
    is printed with (`Metadata/model_settings.config`), and the colours of the filaments (`Metadata/project_settings.config`,
    else those of a sliced file's `slice_info.config`). Returns ({object id: filament number}, {part id: number}, [colours]).
    A colour painted on a triangle is read with the triangle (`_painted`). Nothing here is essential: whatever cannot be
    read is left out, and the model is then drawn without a colour of its own."""
    names = set(zf.namelist())
    objects, parts, colours = {}, {}, []

    def number(el):
        for meta in el.findall("metadata"):
            if meta.get("key") == "extruder" and str(meta.get("value", "")).isdigit():
                return int(meta.get("value"))
        return None

    try:
        if "Metadata/model_settings.config" in names and zf.getinfo("Metadata/model_settings.config").file_size <= MAX_SETTINGS_BYTES:
            with zf.open("Metadata/model_settings.config") as fh:
                for obj in ET.parse(fh).getroot().iter("object"):
                    if number(obj) is not None:
                        objects[obj.get("id")] = number(obj)
                    for part in obj.findall("part"):
                        if number(part) is not None:
                            parts[part.get("id")] = number(part)
        if "Metadata/project_settings.config" in names and zf.getinfo("Metadata/project_settings.config").file_size <= MAX_SETTINGS_BYTES:
            with zf.open("Metadata/project_settings.config") as fh:
                listed = json.loads(fh.read().decode("utf-8", errors="replace")).get("filament_colour")
            if isinstance(listed, list):
                colours = [_rgb(c) for c in listed[:MAX_COLOURS]]
        if not colours and "Metadata/slice_info.config" in names and zf.getinfo("Metadata/slice_info.config").file_size <= MAX_SETTINGS_BYTES:
            with zf.open("Metadata/slice_info.config") as fh:
                found = {}
                for filament in ET.parse(fh).getroot().iter("filament"):
                    if str(filament.get("id", "")).isdigit() and 1 <= int(filament.get("id")) <= MAX_COLOURS:
                        found.setdefault(int(filament.get("id")), _rgb(filament.get("color")))
            colours = [found.get(n) for n in range(1, max(found, default=0) + 1)]
    except (ET.ParseError, DefusedXmlException, ValueError, AttributeError, KeyError):
        return {}, {}, []
    return objects, parts, colours


def _slicer_plates(zf: zipfile.ZipFile) -> dict:
    """The build plates of a Bambu Studio / OrcaSlicer project and what stands on each: {plate number: {(object id, instance)}},
    from `Metadata/model_settings.config`. Empty for any other file, or when it cannot be read."""
    name = "Metadata/model_settings.config"
    plates = {}
    try:
        if name not in zf.namelist() or zf.getinfo(name).file_size > MAX_SETTINGS_BYTES:
            return {}
        with zf.open(name) as fh:
            for plate in ET.parse(fh).getroot().iter("plate"):
                meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
                if not str(meta.get("plater_id", "")).isdigit():
                    continue
                on_it = set()
                for instance in plate.findall("model_instance"):
                    values = {m.get("key"): m.get("value") for m in instance.findall("metadata")}
                    if values.get("object_id") is not None:
                        on_it.add((str(values["object_id"]), int(values["instance_id"]) if str(values.get("instance_id", "")).isdigit() else 0))
                if on_it and len(plates) < MAX_PLATES:
                    plates[int(meta["plater_id"])] = on_it
    except (ET.ParseError, DefusedXmlException, ValueError, AttributeError, KeyError):
        return {}
    return plates


def parts(path: Path, extension: str) -> dict:
    """What a file can show: `plates`, the build plates that hold a model (numbers, for a slicer project with more than one), and
    `pictures`, the plates the slicer left a picture of. An STL has neither."""
    if extension.lower().lstrip(".") != "3mf":
        return {"plates": [], "pictures": []}
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return {"plates": [], "pictures": []}
    with zf:
        pictures = sorted({int(m.group(1)) for info in zf.infolist()
                           if (m := re.fullmatch(r"Metadata/plate_(\d{1,3})\.png", info.filename)) and 0 < info.file_size <= MAX_PICTURE_BYTES})
        return {"plates": sorted(_slicer_plates(zf)), "pictures": pictures[:MAX_PLATES]}


def _threemf_triangles(zf: zipfile.ZipFile, plate: "int | None" = None) -> "tuple[array, bytearray]":
    """Everything on the build plate (or, with `plate`, on that plate of a slicer project), every object where its transforms put
    it, in millimetres, with a colour per triangle (four bytes: red, green, blue, 255; or four zeros where the file does not say)."""
    main = "3D/3dmodel.model"
    if main not in zf.namelist():
        raise PrintFileError("pf.no_model")
    parsed, out, shades = {}, array("f"), bytearray()
    by_object, by_part, filaments = _slicer_colours(zf)

    def filament(number):
        """The colour of filament `number` (1 is the first), as four bytes; None when it is not known."""
        if number is None or not 1 <= number <= len(filaments) or not filaments[number - 1]:
            return None
        return bytes((*filaments[number - 1], 255))

    def load(path):
        path = path.lstrip("/")
        if path not in parsed:
            if path not in zf.namelist():
                raise PrintFileError("pf.missing_file", path=path)
            with zf.open(path) as fh:
                parsed[path] = _parse_model_file(fh, keep=True)
        return parsed[path]

    def emit(path, oid, chain, depth=0, tint=None):
        if depth > 8:
            raise PrintFileError("pf.too_deep")
        _, objects, _ = load(path)
        obj = objects.get(oid)
        if obj is None or obj["type"] not in ("model", None):
            return
        tris = obj["tris"]
        if len(out) + len(tris) > MAX_VIEW_TRIANGLES * 9:                 # an object placed many times counts every time
            raise PrintFileError("pf.too_detailed", max=MAX_VIEW_TRIANGLES)
        for n in range(0, len(tris), 3):
            point = tuple(tris[n:n + 3])
            for transform in chain:                                      # innermost first
                point = _apply(transform, point)
            out.extend(point)
        cols, paint = obj["cols"], obj["paint"]
        if tint is not None or any(paint):                                # the slicer's filament, where the model names no colour:
            cols = bytearray(cols)                                        # the one painted on the triangle, else the object's
            for n in range(0, len(cols), 4):
                if not cols[n + 3]:
                    shade = (filament(paint[n // 4]) if paint[n // 4] else None) or tint
                    if shade is not None:
                        cols[n:n + 4] = shade
        shades.extend(cols)
        for cpath, cid, ctr in obj["components"]:
            emit(cpath or path, cid, [ctr] + chain, depth + 1, filament(by_part.get(cid)) or tint)

    unit, _, items = load(main)
    # an object the slicer names no filament for is printed with the first one; a sliced file lists only the filaments it uses,
    # so "the first" is the first one that has a colour
    first = next((filament(n) for n in range(1, len(filaments) + 1) if filament(n)), None)
    wanted = _slicer_plates(zf).get(plate) if plate is not None else None
    if plate is not None and wanted is None:
        raise PrintFileError("pf.no_plate", plate=plate)
    seen = {}                                                             # how often an object was placed so far: its instance number
    for oid, tr in items:
        instance = seen.get(oid, 0)
        seen[oid] = instance + 1
        if wanted is not None and (str(oid), instance) not in wanted:
            continue
        emit(main, oid, [tr], 0, filament(by_object.get(oid)) or first)
    if unit != 1.0:
        out = array("f", (v * unit for v in out))
    return out, shades


def triangles(path: Path, extension: str, plate: "int | None" = None) -> bytes:
    """The model for the browser to draw, little-endian: the four bytes `PPM1`, the number of triangles and a flag (two unsigned
    32-bit numbers; the flag is 1 when colours follow), then nine 32-bit floats per triangle (x, y, z of its three corners, in
    millimetres, Z up as on the printer), then, with the flag, four bytes per triangle: red, green, blue and 255, or four zeros
    for a triangle the file names no colour for. An STL has no colours. Raises PrintFileError when the file holds no model (a
    sliced 3MF may hold only G-code) or one too detailed to send. `plate` asks for one build plate of a slicer project."""
    ext = extension.lower().lstrip(".")
    shades = bytearray()
    if ext == "stl":
        if plate is not None:
            raise PrintFileError("pf.no_plate", plate=plate)
        out = _stl_triangles(Path(path).read_bytes())
    elif ext == "3mf":
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise PrintFileError("pf.not_zip") from None
        with zf:
            if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES:
                raise PrintFileError("pf.too_big_unpacked")
            try:
                out, shades = _threemf_triangles(zf, plate)
            except (ET.ParseError, DefusedXmlException):
                raise PrintFileError("pf.bad_xml") from None
    else:
        raise PrintFileError("pf.unsupported")
    if not len(out) or not _finite(out):
        raise PrintFileError("pf.no_model")
    count = len(out) // 9
    coloured = len(shades) == count * 4 and any(shades[3::4])
    if sys.byteorder != "little":
        out.byteswap()
    return MESH_MAGIC + struct.pack("<II", count, 1 if coloured else 0) + out.tobytes() + (bytes(shades) if coloured else b"")


def plate_picture(path: Path, extension: str, plate: "int | None" = None) -> "bytes | None":
    """The picture of the build plate a slicer puts in a 3MF (Bambu Studio, OrcaSlicer: `Metadata/plate_1.png`, the first plate
    there is one of, or the plate asked for), as it is in the file; None when there is none. A sliced file often holds no model to draw, but it does hold
    this. The bytes are untrusted: whoever shows them decodes and re-encodes them first."""
    if extension.lower().lstrip(".") != "3mf":
        return None
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return None
    with zf:
        plates = sorted((int(m.group(1)), info) for info in zf.infolist() if (m := re.fullmatch(r"Metadata/plate_(\d{1,3})\.png", info.filename)))
        for number, info in plates:
            if 0 < info.file_size <= MAX_PICTURE_BYTES and plate in (None, number):
                return zf.read(info)
    return None


# --- slicer data ----------------------------------------------------------------------

_DURATION = re.compile(r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", re.I)


def _duration_seconds(text: str):
    m = _DURATION.search(text.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(g or 0) for g in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n >= 0 else None


def _plates_from_slice_info(zf):
    if "Metadata/slice_info.config" not in zf.namelist():
        return []
    with zf.open("Metadata/slice_info.config") as fh:
        root = ET.parse(fh).getroot()
    plates = []
    for plate in root.iter("plate"):
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        filaments = []
        for f in plate.findall("filament"):
            grams = _number(f.get("used_g"))
            if grams:
                filaments.append({"type": f.get("type") or "", "color": colour_code(f.get("color")) or (f.get("color") or "").lower(),
                                  "grams": round(grams, 1), "meters": round(_number(f.get("used_m")) or 0, 2)})
        seconds = _number(meta.get("prediction"))
        grams_total = round(sum(f["grams"] for f in filaments), 1) or _number(meta.get("weight"))
        if not filaments and grams_total:
            filaments = [{"type": "", "color": "", "grams": round(grams_total, 1), "meters": 0}]
        if filaments or seconds:
            plates.append({"index": int(_number(meta.get("index")) or len(plates) + 1),
                           "hours": round(seconds / 3600, 2) if seconds else None,
                           "grams": round(grams_total, 1) if grams_total else None,
                           "filaments": filaments})
    return plates


def _plates_from_gcode_headers(zf):
    """Fallback: the header comments of Metadata/plate_N.gcode inside a sliced 3MF."""
    plates = []
    for name in sorted(n for n in zf.namelist() if re.fullmatch(r"Metadata/plate_\d+\.gcode", n)):
        with zf.open(name) as fh:
            head = fh.read(65536).decode("utf-8", errors="ignore")
        weight = re.search(r"total filament weight \[g\]\s*:\s*([\d.]+)", head)
        time_ = (re.search(r"total estimated time:\s*([^;\n]+)", head)
                 or re.search(r"estimated printing time[^=\n]*=\s*([^\n;]+)", head))
        grams = _number(weight.group(1)) if weight else None
        seconds = _duration_seconds(time_.group(1)) if time_ else None
        if grams or seconds:
            index = int(re.search(r"plate_(\d+)", name).group(1))
            plates.append({"index": index, "hours": round(seconds / 3600, 2) if seconds else None,
                           "grams": round(grams, 1) if grams else None,
                           "filaments": [{"type": "", "color": "", "grams": round(grams, 1), "meters": 0}] if grams else []})
    return plates


# --- entry point ----------------------------------------------------------------------

def analyze(path: Path, extension: str) -> dict:
    ext = extension.lower().lstrip(".")
    if ext == "stl":
        mesh = stl_geometry(Path(path).read_bytes())
        return {"format": "stl", "exact": False, "plates": [],
                "volume_cm3": round(mesh.volume / 1000, 3),
                "bbox_mm": [round(mesh.hi[i] - mesh.lo[i], 1) for i in range(3)]}
    if ext != "3mf":
        raise PrintFileError("pf.unsupported")
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise PrintFileError("pf.not_zip") from None
    with zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES:
            raise PrintFileError("pf.too_big_unpacked")
        try:
            plates = _plates_from_slice_info(zf) or _plates_from_gcode_headers(zf)
        except (ET.ParseError, DefusedXmlException):
            plates = []
        try:
            geometry = threemf_geometry(zf)
        except (PrintFileError, ET.ParseError, DefusedXmlException) as exc:
            if not plates:
                if isinstance(exc, PrintFileError):
                    raise
                raise PrintFileError("pf.bad_xml") from None
            geometry = None  # the slicer's numbers are what matter; a broken mesh is not fatal
    if not plates and geometry is None:
        raise PrintFileError("pf.no_data")
    return {"format": "3mf-sliced" if plates else "3mf-model", "exact": bool(plates), "plates": plates,
            "volume_cm3": round(geometry[0], 3) if geometry else None,
            "bbox_mm": geometry[1] if geometry else None}
