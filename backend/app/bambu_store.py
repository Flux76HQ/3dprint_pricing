"""Look up the store ID of a filament on the Bambu Lab web shop (the `id=` of `.../products/pla-matte?id=43992833229019`).

The owner uses that number as the filament's barcode: it identifies one colour of one kind (refill or with spool) in one weight. Every
product page lists its variants as schema.org JSON-LD (`<script id="product-jsonld">`, a ProductGroup whose `hasVariant` entries have
the ID as `sku` and `PLA Matte - Plum (11204) / Refill / 1kg` as name); a line of an invoice is found there by its filament ID in
brackets, whether it is a refill and its weight.

The IDs are those of the EU shop. The shop sends a visitor to the shop of their own region, whose IDs differ, so a redirect to any
other host ends the lookup instead of storing a number that would be wrong. Only that one host is ever contacted, over https, with a
slug made from the product name on the invoice; every failure is quiet, because the lookup is a convenience on top of the import.
"""
import json
import re
import time
from urllib.parse import urljoin

import requests

from .bambu_invoice import REFILL, WEIGHT

HOST = "eu.store.bambulab.com"
PRODUCTS = f"https://{HOST}/nl/products/"
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_PRODUCTS = 8                    # distinct products looked up for one invoice
CACHE_SECONDS = 3600
_cache: dict[str, tuple[float, "list | None"]] = {}
JSONLD = re.compile(r'<script[^>]*id="product-jsonld"[^>]*>(.*?)</script>', re.S)
IN_BRACKETS = re.compile(r"\(\s*([A-Za-z0-9-]{3,10})\s*\)")


class WrongShop(Exception):
    """The shop answered from another region: its IDs are not ours."""


def slugs(name: str) -> list[str]:
    """The addresses a product may have: 'PLA Matte' is `pla-matte`, 'PLA Basic' is `pla-basic-filament`."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return [base, f"{base}-filament"] if base else []


def _get(url: str) -> "bytes | None":
    """The page, following a redirect only within the EU shop; None for a page that does not exist."""
    for _ in range(4):
        with requests.get(url, timeout=10, allow_redirects=False, stream=True,
                          headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0 (3dprint-pricing)"}) as res:
            if res.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, res.headers.get("Location", ""))
                if not url.startswith(f"https://{HOST}/"):
                    raise WrongShop()
                continue
            if res.status_code == 404:
                return None
            if res.status_code != 200:
                raise requests.RequestException(str(res.status_code))
            body = b""
            for chunk in res.iter_content(65536):
                body += chunk
                if len(body) > MAX_PAGE_BYTES:
                    raise requests.RequestException("too big")
            return body
    raise requests.RequestException("too many redirects")


def variants(slug: str) -> "list[dict] | None":
    """The variants {sku, name} of a product page, or None when there is no such page. Kept for an hour: one invoice has many lines of a product."""
    cached = _cache.get(slug)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    page = _get(f"{PRODUCTS}{slug}")
    found = None
    if page is not None:
        found = []
        for block in JSONLD.findall(page.decode("utf-8", errors="replace")):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            for item in data.get("hasVariant", []) if isinstance(data, dict) else []:
                if isinstance(item, dict) and str(item.get("sku", "")).isdigit() and isinstance(item.get("name"), str):
                    found.append({"sku": str(item["sku"]), "name": item["name"]})
    _cache[slug] = (time.monotonic(), found)
    return found


def find(options: list[dict], line: dict) -> "str | None":
    """The ID of the variant that is this invoice line: same filament ID, same refill or spool, same weight."""
    wanted = str(line.get("filament_id") or "").lower()
    if not wanted:
        return None
    for option in options:
        parts = [p.strip() for p in option["name"].split(" / ")]
        named = IN_BRACKETS.search(parts[0])
        if not named or named.group(1).lower() != wanted:
            continue
        if bool(REFILL.search(option["name"])) != bool(line.get("refill")):
            continue
        kg = WEIGHT.search(parts[-1]) if len(parts) > 1 else None
        if kg and round(float(kg.group(1).replace(",", ".")) * 1000) != round(float(line["roll_weight_g"])):
            continue
        return option["sku"]
    return None


def lookup(lines: list[dict]) -> dict:
    """{index of line: store ID} for the lines that were found, and whether the shop could be consulted at all: {"ids": {...}, "reachable": bool}."""
    ids: dict[int, str] = {}
    pages: dict[str, "list[dict] | None"] = {}
    try:
        for n, line in enumerate(lines):
            name = line.get("name") or ""
            if name not in pages:
                if len(pages) >= MAX_PRODUCTS:
                    continue
                pages[name] = next((v for v in (variants(s) for s in slugs(name)) if v), None)
            if pages.get(name):
                found = find(pages[name], line)
                if found:
                    ids[n] = found
    except (requests.RequestException, WrongShop):
        return {"ids": ids, "reachable": False}
    return {"ids": ids, "reachable": True}
