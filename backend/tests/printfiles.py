"""Synthetic print files: a 10 mm cube is exactly 1 cm^3, so every number can be checked by hand."""
import io
import struct
import zipfile

CUBE_VERTS = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
# Outward-facing triangles.
CUBE_TRIS = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


def stl_binary(scale=1.0) -> bytes:
    out = bytearray(b"\0" * 80 + struct.pack("<I", len(CUBE_TRIS)))
    for a, b, c in CUBE_TRIS:
        pts = [tuple(v * scale for v in CUBE_VERTS[i]) for i in (a, b, c)]
        out += struct.pack("<12fH", 0, 0, 0, *pts[0], *pts[1], *pts[2], 0)
    return bytes(out)


def stl_ascii() -> bytes:
    lines = ["solid cube"]
    for a, b, c in CUBE_TRIS:
        lines.append("facet normal 0 0 0\n outer loop")
        lines += [" vertex %s %s %s" % CUBE_VERTS[i] for i in (a, b, c)]
        lines.append(" endloop\nendfacet")
    lines.append("endsolid cube")
    return "\n".join(lines).encode()


def mesh_xml(scale=1.0) -> str:
    v = "".join(f'<vertex x="{x * scale}" y="{y * scale}" z="{z * scale}"/>' for x, y, z in CUBE_VERTS)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in CUBE_TRIS)
    return f"<mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh>"


NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'


def model_3mf(unit="millimeter", item_transform=None) -> str:
    tr = f' transform="{item_transform}"' if item_transform else ""
    return (f'<?xml version="1.0"?><model unit="{unit}" {NS}><resources>'
            f'<object id="1" type="model">{mesh_xml()}</object></resources>'
            f'<build><item objectid="1"{tr}/></build></model>')


def component_3mf() -> dict:
    """Bambu-style: the main model only holds a component that points into 3D/Objects/."""
    main = (f'<?xml version="1.0"?><model unit="millimeter" {NS} '
            'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"><resources>'
            '<object id="2" type="model"><components>'
            '<component p:path="/3D/Objects/object_1.model" objectid="1" transform="2 0 0 0 2 0 0 0 2 0 0 0"/>'
            '</components></object></resources><build><item objectid="2"/></build></model>')
    sub = (f'<?xml version="1.0"?><model unit="millimeter" {NS}><resources>'
           f'<object id="1" type="model">{mesh_xml()}</object></resources><build/></model>')
    return {"3D/3dmodel.model": main, "3D/Objects/object_1.model": sub}


SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config><header><header_item key="X-BBL-Client-Type" value="slicer"/></header>
<plate>
  <metadata key="index" value="1"/>
  <metadata key="prediction" value="11000"/>
  <metadata key="weight" value="35.32"/>
  <object identify_id="1" name="USW rack-mount" skipped="false"/>
  <filament id="1" tray_info_idx="GFB00" type="ABS" color="#000000" used_m="11.35" used_g="35.32"/>
</plate>
<plate>
  <metadata key="index" value="2"/>
  <metadata key="prediction" value="3600"/>
  <filament id="1" type="ABS" color="#000000" used_m="2.0" used_g="6.1"/>
  <filament id="2" type="PLA" color="#FFFFFF" used_m="1.0" used_g="3.0"/>
</plate></config>"""

GCODE_HEADER = """; HEADER_BLOCK_START
; BambuStudio 01.09.00.00
; model printing time: 2h 57m 58s; total estimated time: 3h 3m 17s
; total layer number: 150
; total filament weight [g] : 35.32
; HEADER_BLOCK_END
G28
"""


def zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def sliced_3mf() -> bytes:
    return zip_bytes({"3D/3dmodel.model": model_3mf(), "Metadata/slice_info.config": SLICE_INFO})


def unsliced_3mf(**kw) -> bytes:
    return zip_bytes({"3D/3dmodel.model": model_3mf(**kw)})
