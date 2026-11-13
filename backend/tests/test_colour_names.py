"""The loose Dutch/English colour comparison (`colour_names`): the names are the real ones of the shared library file and of SpoolmanDB."""
import pytest

from app import colour_names as cn

# (Dutch, as the library has it) -> (English, as SpoolmanDB names the same Bambu Lab colour)
PAIRS = [
    ("Bamboegroen", "Bambu Green"), ("Basic Lichtgrijs", "Light Gray"), ("Pompoenoranje", "Pumpkin Orange"),
    ("Zonnebloemgeel", "Sunflower Yellow"), ("Maretakgroen", "Mistletoe Green"), ("Jadewit", "Jade White"),
    ("Grasgroen", "Grass Green"), ("Lila paars", "Lilac Purple"), ("Matte Pruim", "Matte Plum"), ("Sakura Roze", "Sakura Pink"),
    ("Blauw Grijs", "Blue Gray"), ("Cyaan", "Cyan"), ("Transparant", "Clear"), ("Matte Grijs", "Matte Gray"),
    ("Basic Geel", "Yellow"), ("Zwart", "Black"), ("Marineblauw", "Navy Blue"), ("Blauwgrijs", "Gray Blue"),
]


@pytest.mark.parametrize("dutch, english", PAIRS)
def test_a_dutch_name_is_its_english_one(dutch, english):
    assert cn.same_name(dutch, english) and cn.same_name(english, dutch)


@pytest.mark.parametrize("a, b", [
    ("Rood", "Dark Red"), ("Blauw", "Blue Gray"), ("Matte Zwart", "Black"), ("Pompoenoranje", "Orange"), ("Zwart", "White"),
    ("Zonsondergang", "Sunset"),          # an unknown Dutch word stays as it is: it is not recognised, and never matches by accident
    ("", ""), ("Geel", ""),
])
def test_other_colours_are_not_the_same(a, b):
    assert not cn.same_name(a, b)


def test_grey_and_gray_and_case_and_accents_do_not_matter():
    assert cn.same_name("LIGHT GREY", "light gray") and cn.same_name("Crème", "Cream")


def test_a_product_line_is_part_of_the_name_unless_it_is_basic():
    assert not cn.same_name("Matte Grijs", "Grijs")          # a matte filament is another filament
    assert cn.same_name("Basic Grijs", "Gray")               # "Basic" is Bambu Lab's standard line, which SpoolmanDB does not put in the name


def test_loose_kind_reads_type_and_colour_together_in_either_language():
    dutch = {"brand": "Bambu Lab", "material": "PLA", "product_type": "Basic", "colour": "Geel", "roll_weight_g": "1000.0", "diameter_mm": 1.75}
    english = {"brand": "bambu lab", "material": "pla", "product_type": "", "colour": "Yellow", "roll_weight_g": 1000, "diameter_mm": "1.750"}
    assert cn.loose_kind(dutch) == cn.loose_kind(english)
    assert cn.loose_kind(dutch) != cn.loose_kind({**english, "roll_weight_g": 750})
    assert cn.loose_kind(dutch) != cn.loose_kind({**english, "material": "PETG"})
    assert cn.loose_kind(dutch) != cn.loose_kind({**english, "brand": "Sunlu"})
