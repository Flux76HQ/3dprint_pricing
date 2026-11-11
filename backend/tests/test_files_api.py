import io
import os
import struct
from array import array

import pytest

from tests import printfiles as pf
from tests.test_auth_api import H, onboard, post
from tests.test_domain_api import make, sheet_payload


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def upload(client, data, name="part.stl"):
    return client.post("/api/print-files", data={"file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data", headers=H)


def test_upload_reads_the_file_and_stores_it(owner, app):
    res = upload(owner, pf.sliced_3mf(), "USW rack-mount.gcode.3mf")
    assert res.status_code == 201
    body = res.get_json()
    assert body["kind"] == "3mf" and body["analysis"]["exact"] is True
    assert body["analysis"]["plates"][0]["grams"] == 35.3
    stored = os.listdir(app.config["APP_CONFIG"].upload_dir)
    assert len(stored) == 1 and stored[0].endswith(".3mf") and not stored[0].startswith(".tmp")
    again = owner.get(f"/api/print-files/{body['id']}").get_json()
    assert again["filename"] == "USW rack-mount.gcode.3mf"


def test_download_returns_the_original_bytes(owner):
    data = pf.stl_binary()
    fid = upload(owner, data).get_json()["id"]
    res = owner.get(f"/api/print-files/{fid}/download")
    assert res.status_code == 200 and res.data == data
    assert "attachment" in res.headers["Content-Disposition"] and "part.stl" in res.headers["Content-Disposition"]


def test_rejected_uploads_leave_nothing_behind(owner, app):
    assert upload(owner, b"not a model", "x.stl").status_code == 400
    assert upload(owner, b"", "x.stl").status_code == 400
    assert upload(owner, b"x", "x.exe").status_code == 400
    assert owner.post("/api/print-files", data={}, content_type="multipart/form-data", headers=H).status_code == 400
    assert os.listdir(app.config["APP_CONFIG"].upload_dir) == []


def test_filenames_cannot_escape_the_upload_dir(owner, app):
    res = upload(owner, pf.stl_binary(), "../../etc/passwd.stl")
    assert res.status_code == 201 and res.get_json()["filename"] == "passwd.stl"
    assert all(os.sep not in n for n in os.listdir(app.config["APP_CONFIG"].upload_dir))


def test_oversized_upload_is_refused_with_a_dutch_message(owner):
    res = upload(owner, b"\0" * (3 * 1024 * 1024), "big.stl")     # test config allows 2 MB
    assert res.status_code == 413 and "2 MB" in res.get_json()["error"]


def test_files_need_a_session(client):
    assert client.get("/api/print-files/materials").status_code == 401
    res = client.post("/api/print-files", data={"file": (io.BytesIO(b"x"), "a.stl")},
                      content_type="multipart/form-data", headers=H)
    assert res.status_code == 401


def test_estimate_uses_density_and_fill(owner):
    fid = upload(owner, pf.stl_binary(scale=3)).get_json()["id"]      # 27 cm3
    res = owner.get(f"/api/print-files/{fid}/estimate?density=1.24&fill=40").get_json()
    assert res["grams"] == 13.4
    assert owner.get(f"/api/print-files/{fid}/estimate?density=9&fill=40").status_code == 400
    assert owner.get(f"/api/print-files/{fid}/estimate?density=abc").status_code == 400
    assert "ABS" in owner.get("/api/print-files/materials").get_json()


# --- the model, for the viewer in the browser ---------------------------------------------------------------------

def mesh(client, data, name="part.stl"):
    fid = upload(client, data, name).get_json()["id"]
    return client.get(f"/api/print-files/{fid}/mesh")


def parts(res):
    """(the corners, the colours or None) of what the mesh route sent."""
    assert res.status_code == 200 and res.data[:4] == b"PPM1"
    count, coloured = struct.unpack_from("<II", res.data, 4)
    values = array("f")
    values.frombytes(res.data[12:12 + count * 36])
    shades = res.data[12 + count * 36:]
    assert len(shades) == (count * 4 if coloured else 0)
    return values, ([tuple(shades[n:n + 4]) for n in range(0, len(shades), 4)] if coloured else None)


def corners(res):
    return parts(res)[0]


COLOURED = ('<?xml version="1.0"?><model unit="millimeter" ' + pf.NS + ' xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">'
            '<resources><basematerials id="5"><base name="rood" displaycolor="#FF0000"/><base name="blauw" displaycolor="#0000FFFF"/></basematerials>'
            '<m:colorgroup id="6"><m:color color="#00FF0080"/></m:colorgroup>'
            '<object id="1" type="model" pid="5" pindex="1">{mesh}</object></resources><build><item objectid="1"/></build></model>')


def test_the_colours_a_3mf_names_come_with_the_model(owner):
    # the object is blue; its first triangle says red itself, its second green from another group, its third points at nothing
    body = pf.mesh_xml().replace('<triangle ', '<triangle pid="5" p1="0" ', 1).replace('/><triangle ', '/><triangle pid="6" p1="0" ', 1)
    head, rest = body.split('/><triangle ', 2)[:2], body.split('/><triangle ', 2)[2]
    body = '/><triangle '.join(head) + '/><triangle pid="9" p1="4" ' + rest
    values, shades = parts(mesh(owner, pf.zip_bytes({"3D/3dmodel.model": COLOURED.format(mesh=body)}), "kleur.3mf"))
    assert len(values) == 12 * 9 and len(shades) == 12
    assert shades[:3] == [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 0, 0)] and set(shades[3:]) == {(0, 0, 255, 255)}
    assert parts(mesh(owner, pf.unsliced_3mf(), "kaal.3mf"))[1] is None             # no colour named: none sent
    assert parts(mesh(owner, pf.stl_binary()))[1] is None


def test_colours_painted_on_in_the_slicer_are_read(owner):
    from app.printfile import _painted
    # one digit per whole triangle: 4 and 8 are filaments 1 and 2, "0C" and "1C" are 3 and 4 (read from the end), 0 is unpainted
    assert [_painted(code) for code in ("4", "8", "0C", "1C", "0", "", "zz", "F" * 30000)] == [1, 2, 3, 4, 0, 0, 0, 0]
    # a triangle split in two ("1" = split once; its pieces follow): most of it wins. Read from the end: split, filament 2, then
    # a piece that is split again into filament 2 and filament 1
    assert _painted("881") == 2 and _painted("48181") == 2                         # half of it, and half of the other half
    assert _painted("1") == 0 and _painted("C") == 0                                # cut off: not painted, never an error
    project = '{"filament_colour": ["#FFFFFF", "#D32F2FFF", "#1976D2"]}'
    body = pf.mesh_xml().replace('<triangle ', '<triangle paint_color="8" ', 1).replace('/><triangle ', '/><triangle paint_color="0C" ', 1)
    model = (f'<?xml version="1.0"?><model unit="millimeter" {pf.NS}><resources><object id="1" type="model">{body}</object></resources>'
             '<build><item objectid="1"/></build></model>')
    shades = parts(mesh(owner, pf.zip_bytes({"3D/3dmodel.model": model, "Metadata/project_settings.config": project}), "painted.3mf"))[1]
    assert shades[:2] == [(211, 47, 47, 255), (25, 118, 210, 255)] and set(shades[2:]) == {(255, 255, 255, 255)}     # the rest: its filament
    prusa = model.replace('paint_color="8"', 'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06" slic3rpe:mmu_segmentation="8"')
    assert parts(mesh(owner, pf.zip_bytes({"3D/3dmodel.model": prusa, "Metadata/project_settings.config": project}), "prusa.3mf"))[1][0] == (211, 47, 47, 255)


def test_a_filament_colour_is_read_in_one_spelling(owner):
    info = pf.SLICE_INFO.replace('color="#FFFFFF"', 'color="#FF8800FF"').replace('color="#000000"', 'color="#1A2B3C"')
    plates = upload(owner, pf.zip_bytes({"3D/3dmodel.model": pf.model_3mf(), "Metadata/slice_info.config": info}), "a.gcode.3mf").get_json()["analysis"]["plates"]
    assert [f["color"] for plate in plates for f in plate["filaments"]] == ["#1a2b3c", "#1a2b3c", "#ff8800"]


def test_the_filament_colours_of_a_slicer_project_colour_its_objects(owner):
    files = pf.component_3mf()                                                      # object 2, made of part 1 in a file of its own
    settings = ('<?xml version="1.0"?><config><object id="2"><metadata key="extruder" value="2"/>'
                '<part id="1" subtype="normal_part"><metadata key="extruder" value="{part}"/></part></object></config>')
    project = '{"filament_colour": ["#FFFFFF", "#00AE42", "nope"], "other": 1}'
    made = lambda **more: parts(mesh(owner, pf.zip_bytes({**files, **more}), "project.3mf"))[1]
    assert set(made(**{"Metadata/project_settings.config": project})) == {(255, 255, 255, 255)}                   # nothing said: the first filament
    assert set(made(**{"Metadata/project_settings.config": project,
                       "Metadata/model_settings.config": settings.format(part=9)})) == {(0, 174, 66, 255)}         # the object's filament
    assert set(made(**{"Metadata/project_settings.config": project,
                       "Metadata/model_settings.config": settings.format(part=1)})) == {(255, 255, 255, 255)}      # the part's own wins
    assert set(made(**{"Metadata/project_settings.config": project,
                       "Metadata/model_settings.config": settings.format(part=3)})) == {(0, 174, 66, 255)}         # a colour that is none: the object's
    assert made(**{"Metadata/model_settings.config": settings.format(part=1)}) is None                              # filaments without colours
    assert set(made(**{"Metadata/slice_info.config": pf.SLICE_INFO})) == {(0, 0, 0, 255)}                           # a sliced file: its first filament
    only_second = pf.SLICE_INFO.replace('<filament id="1"', '<filament id="7"')     # a sliced file lists only the filaments it uses
    assert set(made(**{"Metadata/slice_info.config": only_second})) == {(255, 255, 255, 255)}                       # the first that has a colour
    for broken in ("<config><object", "{not json"):                                 # settings that cannot be read never stop the model
        assert made(**{"Metadata/project_settings.config": broken, "Metadata/model_settings.config": broken}) is None


def test_the_model_is_served_as_triangles(owner):
    for data in (pf.stl_binary(), pf.stl_ascii()):
        res = mesh(owner, data)
        assert res.status_code == 200 and res.mimetype == "application/octet-stream" and res.headers["Cache-Control"] == "no-store"
        values = corners(res)
        assert res.data[:12] == b"PPM1" + struct.pack("<II", 12, 0) and len(res.data) == 12 + 12 * 36
        assert len(values) == 12 * 9 and (min(values), max(values)) == (0.0, 10.0)       # the cube: twelve triangles, 10 mm


def test_a_3mf_model_is_put_where_its_transforms_put_it(owner):
    values = corners(mesh(owner, pf.unsliced_3mf(unit="centimeter", item_transform="1 0 0 0 1 0 0 0 1 5 0 0"), "part.3mf"))
    xs, ys = values[0::3], values[1::3]
    assert len(values) == 12 * 9 and (min(xs), max(xs)) == (50.0, 150.0) and (min(ys), max(ys)) == (0.0, 100.0)     # moved 5 cm, in mm
    values = corners(mesh(owner, pf.zip_bytes(pf.component_3mf()), "bambu.3mf"))        # a part in a file of its own, twice the size
    assert len(values) == 12 * 9 and (min(values), max(values)) == (0.0, 20.0)


def test_a_file_without_a_model_or_with_too_much_of_it_says_so(owner, monkeypatch):
    only_gcode = pf.zip_bytes({"Metadata/slice_info.config": pf.SLICE_INFO})
    res = mesh(owner, only_gcode, "plate.gcode.3mf")
    assert res.status_code == 422 and "geen 3D-model" in res.get_json()["error"]
    from app import printfile
    monkeypatch.setattr(printfile, "MAX_VIEW_TRIANGLES", 11)
    for data, name in ((pf.stl_binary(), "a.stl"), (pf.stl_ascii(), "b.stl"), (pf.unsliced_3mf(), "c.3mf")):
        res = mesh(owner, data, name)
        assert res.status_code == 422 and "te gedetailleerd" in res.get_json()["error"], name
    assert owner.get("/api/print-files/00000000-0000-0000-0000-000000000000/mesh").status_code == 404


def test_a_sliced_file_without_a_model_still_has_the_picture_of_its_plate(owner):
    from PIL import Image
    def plate(colour, size=(512, 512)):
        out = io.BytesIO()
        Image.new("RGBA", size, colour).save(out, "PNG")
        return out.getvalue()
    sliced = {"Metadata/slice_info.config": pf.SLICE_INFO, "Metadata/plate_2.png": plate((0, 0, 255, 255)),
              "Metadata/plate_1.png": plate((255, 0, 0, 255)), "Metadata/plate_1_small.png": plate((0, 255, 0, 255), (64, 64)),
              "Metadata/top_1.png": plate((0, 255, 0, 255))}
    fid = upload(owner, pf.zip_bytes(sliced), "bak.gcode.3mf").get_json()["id"]
    res = owner.get(f"/api/print-files/{fid}/mesh")
    assert res.status_code == 422 and ".gcode.3mf" in res.get_json()["error"]         # no model, and it says what to do
    res = owner.get(f"/api/print-files/{fid}/preview")
    assert res.status_code == 200 and res.mimetype == "image/jpeg"
    picture = Image.open(io.BytesIO(res.data))
    assert picture.format == "JPEG" and picture.size == (512, 512) and picture.convert("RGB").getpixel((5, 5))[0] > 240       # the first plate, re-encoded
    for data, name in ((pf.sliced_3mf(), "a.gcode.3mf"), (pf.stl_binary(), "a.stl"),
                       (pf.zip_bytes({**sliced, "Metadata/plate_1.png": b"not a picture", "Metadata/plate_2.png": b""}), "b.gcode.3mf")):
        fid = upload(owner, data, name).get_json()["id"]
        assert owner.get(f"/api/print-files/{fid}/preview").status_code == 404, name
    assert owner.get("/api/print-files/00000000-0000-0000-0000-000000000000/preview").status_code == 404


def test_the_model_needs_a_session(client, owner):
    fid = upload(owner, pf.stl_binary()).get_json()["id"]
    client.delete_cookie("pp_session")
    assert client.get(f"/api/print-files/{fid}/mesh").status_code == 401


def test_project_links_the_file_and_a_source_url(owner):
    fid = upload(owner, pf.sliced_3mf(), "print.3mf").get_json()["id"]
    body = {**sheet_payload(), "file_id": fid, "source_url": "https://makerworld.com/en/models/12345"}
    p = make(owner, "/api/projects", body)
    assert p["file_id"] == fid and p["source_url"].startswith("https://makerworld.com/")
    again = owner.get(f"/api/projects/{p['id']}").get_json()
    assert again["file_id"] == fid
    unlinked = owner.put(f"/api/projects/{p['id']}", json={**sheet_payload(), "source_url": ""}, headers=H)
    assert unlinked.get_json()["file_id"] is None and unlinked.get_json()["source_url"] == ""


def test_a_model_keeps_several_links_each_with_its_kind(owner):
    links = [{"kind": "model", "label": "", "url": "https://makerworld.com/en/models/12345"},
             {"kind": "marktplaats", "label": "Zwarte uitvoering", "url": "https://www.marktplaats.nl/v/a1"},
             {"kind": "bol", "label": "", "url": "https://www.bol.com/nl/nl/p/x/9300000000000000/"}]
    p = make(owner, "/api/projects", {**sheet_payload(), "links": links})
    assert p["links"] == links
    assert p["source_url"] == links[0]["url"]                           # the link to the model itself, for a backup read by an older release
    assert owner.get("/api/projects").get_json()[0]["links"] == links   # the list shows where a model is offered
    fewer = owner.put(f"/api/projects/{p['id']}", json={**sheet_payload(), "links": links[1:]}, headers=H).get_json()
    assert fewer["links"] == links[1:] and fewer["source_url"] == ""


def test_one_source_url_becomes_the_link_to_the_model(owner):
    # A client or backup from before there were several links sends only `source_url`.
    p = make(owner, "/api/projects", {**sheet_payload(), "source_url": "https://www.printables.com/model/1"})
    assert p["links"] == [{"kind": "model", "label": "", "url": "https://www.printables.com/model/1"}]
    assert make(owner, "/api/projects", sheet_payload())["links"] == []


@pytest.mark.parametrize("extra", [{"file_id": "00000000-0000-0000-0000-000000000000"}, {"file_id": "nope"},
                                   {"source_url": "javascript:alert(1)"}, {"source_url": "ftp://x/y"},
                                   {"links": "https://x.example"}, {"links": ["https://x.example"]},
                                   {"links": [{"kind": "model", "url": "javascript:alert(1)"}]}, {"links": [{"kind": "model", "url": ""}]},
                                   {"links": [{"kind": "ebay", "url": "https://x.example"}]},
                                   {"links": [{"kind": "other", "url": "https://x.example", "label": "x" * 61}]},
                                   {"links": [{"kind": "other", "url": "https://x.example"}] * 13}])
def test_project_rejects_bad_links(owner, extra):
    assert owner.post("/api/projects", json={**sheet_payload(), **extra}, headers=H).status_code == 400


def test_unlinked_uploads_are_purged_after_a_day_but_linked_ones_stay(owner, app):
    from tests.conftest import connect
    kept = upload(owner, pf.stl_binary(), "kept.stl").get_json()["id"]
    make(owner, "/api/projects", {**sheet_payload(), "file_id": kept})
    orphan = upload(owner, pf.stl_binary(), "orphan.stl").get_json()["id"]
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        conn.execute("UPDATE print_files SET created_at = strftime('%Y-%m-%d %H:%M:%f', 'now', '-2 days')")
    upload(owner, pf.stl_binary(), "trigger.stl")           # any upload runs the cleanup
    assert owner.get(f"/api/print-files/{kept}").status_code == 200
    assert owner.get(f"/api/print-files/{orphan}").status_code == 404
    assert len(os.listdir(app.config["APP_CONFIG"].upload_dir)) == 2   # kept + trigger


def test_packaging_flows_through_the_api(owner):
    body = sheet_payload()
    body["data"]["parts"] = [{"group": "verpakking", "label": "Doos", "quantity": 1, "unit": "stuks", "unit_price": "0.85"}]
    res = owner.post("/api/calculate", json=body, headers=H).get_json()
    assert res["subtotals"]["packaging"] == "0.85" and res["cost_price"] == "3.59"
