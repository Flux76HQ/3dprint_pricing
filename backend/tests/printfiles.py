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

# The G-code of one plate as Bambu Studio writes it, cut down: the purge line of the start G-code (no feature yet), a brim, a filament
# change that purges beside the plate (M620..M621), a prime tower and support, none of which is the object; the object is a block of
# 20 x 30 mm from (100, 100), 12 mm high (relative E, the layer height on a line of its own; the wipe at the end of a wall retracts,
# which is no extrusion), and an arc on top that bulges 5 mm past its ends to y = 135. After the end G-code begins, nothing counts.
PLATE_GCODE = GCODE_HEADER.replace("G28\n", "") + """; EXECUTABLE_BLOCK_START
M83
G90
G1 X18 Y1 E10 F1000
G1 X240 Y1 E20
G1 Z.2
; FEATURE: Brim
G1 X95 Y95
G1 X125 Y95 E1.5
; FEATURE: Prime tower
G1 X200 Y200
G1 X230 Y230 E3
; FEATURE: Outer wall
G1 X100 Y100
G1 X120 Y100 E.8 ; a wipe would go beyond:
G1 X126 Y100 E-.4
G1 X120 Y100
G1 E.4
G1 X120 Y130 E1.2 ; a comment on the line
G1 X100 Y130 E.8
G1 X100 Y100 E1.2
G1 X108 Y100 E-.8
M620 S1A
G1 X-38 Y200 E50
M621 S1A
; FEATURE: Support
G1 X60 Y60
G1 X60 Y160 E2
G1 Z12 F600
; FEATURE: Top surface
G1 X105 Y130
G2 X115 Y130 I5 J0 E.5
G3 X105 Y130 I-5 J0 E.5
; MACHINE_END_GCODE_START
G1 X0 Y250 E5
"""

# The same block as PrusaSlicer writes it: `;TYPE:`, absolute E reset by G92, a skirt.
PRUSA_GCODE = """M82
G92 E0
;TYPE:Custom
G1 X0 Y-3 E8
G92 E0
G1 Z.2
;TYPE:Skirt/Brim
G1 X90 Y90
G1 X130 Y90 E1
;TYPE:External perimeter
G1 X10 Y20
G1 X30 Y20 E2
G1 X30 Y50 E3
G1 Z8.4
G1 X10 Y50 E4
G1 X12 Y50 E3.5
;TYPE:Wipe tower
G1 X150 Y150 E6
"""


def sliced_with_gcode(gcode: str = PLATE_GCODE) -> bytes:
    """A `.gcode.3mf`: the slicer's numbers and the G-code of plate 1, no model; plate 2 has no G-code."""
    return zip_bytes({"Metadata/slice_info.config": SLICE_INFO, "Metadata/plate_1.gcode": gcode})


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
