"""The Bambu Lab filaments and their colours, read from the web shop, for the new-roll form: pick the product, pick the colour, and
the rest of the form is filled in (see `bambu_store`). Read-only; nothing is stored here."""
import requests
from flask import Blueprint, jsonify

from . import bambu_store
from .http import ApiError, login_required

bp = Blueprint("bambu_catalog", __name__, url_prefix="/api/bambu")


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


@bp.get("/products")
def products():
    return jsonify([{"slug": slug, "name": name} for slug, name in bambu_store.CATALOG])


@bp.get("/products/<slug>")
def colours(slug):
    """The colours of one product, as the fields of a filament; the store ID of each is its barcode."""
    if slug not in bambu_store.SLUGS:
        raise ApiError(404, "bambu.err_product")
    try:
        found = bambu_store.catalog(slug)
    except (requests.RequestException, bambu_store.WrongShop):
        raise ApiError(502, "bambu.err_store") from None
    if not found:
        raise ApiError(404, "bambu.err_product")
    found.sort(key=lambda v: (v["colour"].lower(), not v["refill"]))
    return jsonify({"slug": slug, "colours": found})
