"""Who the app is, to a browser: the passkey relying party (domain) and the origins it answers to.

`RP_ID` and `RP_ORIGINS` are optional. Left empty, the app takes them from the address it is opened on, so it also runs
on an IP address on a home network, where only the password login can work (a passkey needs a real domain and https).
Set them to pin the app to one domain: passkeys are bound to `RP_ID`, so pinning is what you want once they are in use
(the host of a request can differ behind a proxy, and changing it later orphans every passkey).
"""
import ipaddress

from flask import request

from .http import config


def _first(header: str) -> str:
    """The first of a comma separated forwarded header (several proxies add one each)."""
    return (request.headers.get(header) or "").split(",", 1)[0].strip()


def _host() -> str:
    return _first("X-Forwarded-Host") or request.host


def bare_host(host: str) -> str:
    """The name without its port: `print.example.com:6080` -> `print.example.com`, `[::1]:6080` -> `::1`."""
    host = host.strip()
    if host.startswith("["):
        return host[1:host.index("]")] if "]" in host else host
    return host.split(":", 1)[0]


def is_secure() -> bool:
    """https as the browser sees it: the proxy's word first (`X-Forwarded-Proto`), else the connection itself."""
    forwarded = _first("X-Forwarded-Proto").lower()
    return forwarded == "https" if forwarded else request.is_secure


def request_origin() -> str:
    """The address the browser used, as `scheme://host[:port]`: what a passkey ceremony will report as its origin."""
    return f"{'https' if is_secure() else 'http'}://{_host()}".rstrip("/")


def rp_id() -> str:
    return config().rp_id or bare_host(_host()).lower()


def rp_origins() -> list[str]:
    return list(config().rp_origins) or [request_origin()]


def cookie_secure() -> bool:
    cfg = config()
    return cfg.cookie_secure if cfg.rp_origins else is_secure()


def origin_allowed(origin: str) -> bool:
    """May a state-changing call that says it comes from `origin` be answered? Pinned: one of `RP_ORIGINS`. Not pinned: the
    address the page itself was served from, so a page on another site (the CSRF case) is refused either way."""
    origin = origin.rstrip("/")
    return origin in config().rp_origins if config().rp_origins else origin.lower() == request_origin().lower()


def public_origin() -> str:
    """The address a link is made for: the one the person is on now when it is allowed, else the first configured one. Never
    a host the request merely claims, which behind a proxy can be an internal address."""
    origins = config().rp_origins
    if not origins:
        return request_origin()
    asked = (request.headers.get("Origin") or "").rstrip("/")
    return asked if asked in origins else origins[0]


def passkey_problem() -> str | None:
    """Why a passkey cannot work on the address in use, as a message key, or None when it can. Only what is certain: browsers
    refuse a passkey on an IP address and outside a secure context (https, or localhost); the rest is for the browser to say."""
    host = bare_host(rp_id())
    try:
        ipaddress.ip_address(host)
        return "passkey.ip_address"
    except ValueError:
        pass
    local = host == "localhost" or host.endswith(".localhost")
    if not local and not is_secure() and not any(o.startswith("https://") for o in config().rp_origins):
        return "passkey.needs_https"
    return None
