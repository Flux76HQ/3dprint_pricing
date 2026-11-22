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


@pytest.mark.parametrize("dutch, english", [
    ("Bamboegroen", "Bamboo Green"), ("Lila paars", "Lilac Purple"), ("Matte Pruim", "Matte Plum"), ("Pompoenoranje", "Pumpkin Orange"),
    ("Zonnebloemgeel", "Sunflower Yellow"), ("Blauw Grijs", "Blue Gray"), ("Transparant", "Clear"), ("Cyaan", "Cyan"), ("Sakura Roze", "Sakura Pink"),
    ("Zwart", "Black"), ("Jadewit", "Jade White"), ("Maretakgroen", "Mistletoe Green"), ("Lichtgrijs", "Light Gray"), ("Crème", "Cream"),
    ("Silk (Blauw)", "Silk (Blue)"),
])
def test_a_dutch_colour_is_translated_word_by_word_in_the_same_order(dutch, english):
    assert cn.to_english(dutch) == english and cn.same_name(dutch, english)                      # what is stored is also recognised as the same colour


@pytest.mark.parametrize("name", ["Ivory White", "Charcoal", "Bambu Green", "Zonsondergang", "Matte Charcoal", ""])
def test_what_is_english_or_not_known_is_kept_as_it_is(name):
    assert cn.to_english(name) == name                                                          # an unknown Dutch word is never guessed


def test_translating_twice_changes_nothing_and_nothing_is_a_problem():
    for name in ("Bamboegroen", "Lila paars", "Rood", "Light Gray", "Zonsondergang"):
        assert cn.to_english(cn.to_english(name)) == cn.to_english(name)
    assert cn.to_english(None) == "" and cn.to_english(5) == "5"
