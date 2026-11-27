"""The links of a 3D model and of a customer are buttons that open in a new tab (`frontend/js/links.js`), with the icon of their kind in front of the name. There is no browser here, so
the wiring is checked in the sources (the behaviour was checked in Chromium, on a desktop and a phone)."""
import re
from pathlib import Path

from app import api

FRONT = Path(__file__).resolve().parents[2] / "frontend"


def source(name):
    return (FRONT / name).read_text()


def test_the_screen_and_the_server_agree_on_what_a_link_is():
    """A link is shown as a link only when it is an address the server would keep: http(s), no spaces. Anything else is shown, but it goes nowhere."""
    written = re.search(r"export const isLink = \(url\) => /(.*?)/i\.test", source("js/links.js")).group(1)
    assert written.replace("\\/", "/").replace("\\S", "[^\\s]") == api.URL.pattern


def test_a_link_opens_in_a_new_tab_and_only_when_it_is_an_address():
    links = source("js/links.js")
    assert "isLink(url) ? { href: String(url).trim(), target: '_blank', rel: 'noopener noreferrer'" in links          # no address, no href; and the page that opens cannot reach this one
    assert links.count("...target(url)") == 2                                                                         # the button and the chip both go through it
    assert "href: url" not in links and "href: link.url" not in source("js/projects.js") and "href: c." not in source("js/customers.js")


def test_a_link_that_is_not_an_address_is_never_shown_as_a_button_in_an_editor():
    links = source("js/links.js")
    assert "open = open || !(filled() && ok());" in links                                                             # empty or not an address: the fields, never a button that goes nowhere
    assert "if (!ok()) {" in links and "refused.hidden = false;" in links                                             # and the fields do not close on it


def test_the_tile_of_a_model_opens_the_model_by_its_name_so_that_its_links_can_be_links():
    """A link inside a link is not allowed, so the tile is not one: its name is a link that covers it, and the links stand above that."""
    projects = source("js/projects.js")
    tile = projects[projects.index("    tile: (p) => h('article'"):projects.index("    empty: t('calc.none_yet')")]
    assert "h('a', { class: 'stretched', href: href(p) }, p.name)" in tile and "h('div', { class: 'tile-links' }, linkChips(p.links))" in tile
    assert "h('a', { class: 'glass card item link-card'" not in tile
    css = source("css/app.css")
    assert ".link-card .stretched::after { content: ''; position: absolute; inset: 0;" in css and ".link-card { position: relative; }" in css
    assert re.search(r"\.tile-links \{ position: relative; z-index: 1; \}", css)                                       # above the cover
    perf = (Path(__file__).resolve().parents[2] / "scripts" / "perf_baseline.py").read_text()
    assert 'wait_for_selector("a.link-card")' not in perf                                                              # the tile is not an `a` any more


def test_the_links_card_shows_a_link_as_a_button_with_icons_to_edit_and_remove_it():
    projects = source("js/projects.js")
    card = projects[projects.index("function drawLinks()"):projects.index("  drawLinks();\n")]
    assert "linkRow({" in card and "show: () => linkButton({ kind: link.kind, name: linkName(link), url: link.url })" in card
    assert "state.links.push({ kind:" in card and "editing: true" in card                                              # a new one starts with its fields
    links = source("js/links.js")
    assert "action('pencil-outline'" in links and "action('delete-outline'" in links and "action('check'" in links       # the Material Design icons
    for name in ("pencil-outline", "delete-outline", "check", "storefront-outline", "shopping-outline", "web", "cube-outline", "link-variant"):
        assert f"'{name}': '" in source("js/mdi.js") or f"  {name}: '" in source("js/mdi.js"), name
    customers = source("js/customers.js")
    assert "linkRow({" in customers and "linkButton({ kind: 'marktplaats'" in customers and "linkChip({ kind: 'marktplaats'" in customers


def test_the_new_modules_are_cached_by_the_service_worker_and_the_brand_marks_have_their_licence():
    worker = source("sw.js")
    assert "'/js/links.js'" in worker and "'/js/brands.js'" in worker
    vendor = FRONT / "vendor" / "simple-icons"
    assert (vendor / "LICENSE").read_text().startswith("# CC0 1.0 Universal") and (vendor / "DISCLAIMER.md").exists()
    assert "version **16.38.1**" in (vendor / "README.md").read_text() and "version 16.38.1" in source("js/brands.js")
    assert set(re.findall(r"'(brand-[\w-]+)':", source("js/brands.js"))) == {"brand-etsy", "brand-vinted"}
