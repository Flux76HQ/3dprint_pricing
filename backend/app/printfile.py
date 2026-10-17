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
import math
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


def _parse_model_file(stream):
    """Return (unit_scale, {object_id: object}, [build items]) for one .model XML file."""
    unit, objects, items = 1.0, {}, []
    current = None
    verts = array("d")
    for event, el in ET.iterparse(stream, events=("start", "end")):
        name = _local(el.tag)
        if event == "start":
            if name == "model":
                unit = UNIT_MM.get(el.get("unit", "millimeter"), 1.0)
            elif name == "object":
                current = {"id": el.get("id"), "type": el.get("type", "model"), "mesh": _Mesh(), "components": []}
                verts = array("d")
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
                current["mesh"].add(verts[3 * i:3 * i + 3], verts[3 * j:3 * j + 3], verts[3 * k:3 * k + 3])
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
                filaments.append({"type": f.get("type") or "", "color": (f.get("color") or "").lower(),
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
