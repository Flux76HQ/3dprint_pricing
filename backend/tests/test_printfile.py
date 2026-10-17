import pytest

from app import printfile
from app.printfile import PrintFileError, analyze, estimate_grams
from tests import printfiles as pf


def run(tmp_path, data, ext):
    path = tmp_path / f"f{ext}"
    path.write_bytes(data)
    return analyze(path, ext)


def test_binary_and_ascii_stl_agree_on_a_one_cm3_cube(tmp_path):
    for data in (pf.stl_binary(), pf.stl_ascii()):
        out = run(tmp_path, data, ".stl")
        assert out["volume_cm3"] == 1.0 and out["bbox_mm"] == [10.0, 10.0, 10.0]
        assert out["exact"] is False and out["format"] == "stl" and out["plates"] == []


def test_stl_volume_scales_with_the_cube(tmp_path):
    assert run(tmp_path, pf.stl_binary(scale=2), ".stl")["volume_cm3"] == 8.0


@pytest.mark.parametrize("data", [b"", b"\0" * 20, b"hello world", b"solid x\nvertex 1 2\nendsolid",
                                  b"solid x\nvertex a b c\nvertex 1 2 3\nvertex 4 5 6\nendsolid"])
def test_broken_stl_is_a_readable_error(tmp_path, data):
    with pytest.raises(PrintFileError):
        run(tmp_path, data, ".stl")


def test_sliced_3mf_gives_the_slicers_exact_numbers(tmp_path):
    out = run(tmp_path, pf.sliced_3mf(), ".3mf")
    assert out["format"] == "3mf-sliced" and out["exact"] is True
    first, second = out["plates"]
    assert first["grams"] == 35.3 and first["hours"] == pytest.approx(3.06, abs=0.01)
    assert first["filaments"] == [{"type": "ABS", "color": "#000000", "grams": 35.3, "meters": 11.35}]
    assert second["grams"] == 9.1 and len(second["filaments"]) == 2   # two materials on one plate
    assert out["volume_cm3"] == 1.0


def test_unsliced_3mf_only_measures_geometry(tmp_path):
    out = run(tmp_path, pf.unsliced_3mf(), ".3mf")
    assert out["format"] == "3mf-model" and out["exact"] is False and out["plates"] == []
    assert out["volume_cm3"] == 1.0 and out["bbox_mm"] == [10.0, 10.0, 10.0]


def test_3mf_units_and_item_transforms_are_applied(tmp_path):
    assert run(tmp_path, pf.unsliced_3mf(unit="centimeter"), ".3mf")["volume_cm3"] == 1000.0
    scaled = run(tmp_path, pf.unsliced_3mf(item_transform="2 0 0 0 2 0 0 0 2 0 0 0"), ".3mf")
    assert scaled["volume_cm3"] == 8.0 and scaled["bbox_mm"] == [20.0, 20.0, 20.0]


def test_3mf_components_in_other_files_are_followed(tmp_path):
    out = run(tmp_path, pf.zip_bytes(pf.component_3mf()), ".3mf")
    assert out["volume_cm3"] == 8.0   # the component is scaled 2x


def test_gcode_header_is_a_fallback_for_slicer_data(tmp_path):
    data = pf.zip_bytes({"3D/3dmodel.model": pf.model_3mf(), "Metadata/plate_1.gcode": pf.GCODE_HEADER})
    out = run(tmp_path, data, ".3mf")
    plate = out["plates"][0]
    assert out["exact"] is True and plate["grams"] == 35.3 and plate["hours"] == pytest.approx(3.05, abs=0.01)


def test_a_broken_model_does_not_hide_the_slicer_numbers(tmp_path):
    data = pf.zip_bytes({"3D/3dmodel.model": "<model><nope", "Metadata/slice_info.config": pf.SLICE_INFO})
    out = run(tmp_path, data, ".3mf")
    assert out["exact"] is True and out["volume_cm3"] is None


@pytest.mark.parametrize("files, message", [
    ({"readme.txt": "hi"}, "geen slicer-gegevens"),
    ({"3D/3dmodel.model": "<model><nope"}, "ongeldige"),
])
def test_unusable_3mf_is_a_readable_error(tmp_path, files, message):
    with pytest.raises(PrintFileError, match=message):
        run(tmp_path, pf.zip_bytes(files), ".3mf")


def test_not_a_zip_and_wrong_extension(tmp_path):
    with pytest.raises(PrintFileError, match="zip"):
        run(tmp_path, b"not a zip", ".3mf")
    with pytest.raises(PrintFileError, match="ondersteund"):
        run(tmp_path, b"x", ".obj")


def test_xml_entity_bombs_are_refused(tmp_path):
    bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
            "<model>&b;</model>")
    with pytest.raises(PrintFileError):
        run(tmp_path, pf.zip_bytes({"3D/3dmodel.model": bomb}), ".3mf")


def test_oversized_archives_are_refused_before_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(printfile, "MAX_UNZIPPED_BYTES", 100)
    with pytest.raises(PrintFileError, match="te groot"):
        run(tmp_path, pf.sliced_3mf(), ".3mf")


def test_estimate_is_volume_times_density_times_fill():
    assert estimate_grams(100, 1.24, 40) == 49.6
    assert estimate_grams(1, 1.04, 100) == 1.0
