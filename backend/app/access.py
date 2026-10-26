"""Who may call what: the one list of routes that are for administrators only.

It is a list of paths, checked on the server before any handler runs (`create_app`'s `_guard`), so a new route under one of these
prefixes is protected without anyone having to remember. Hiding a tab in the screens is courtesy; this is the control.
`test_access.py` calls every one of them as a regular user.

Everything not listed is for any signed-in person: the work itself (calculations, orders, customers, stock, print files, the filament
library) and each person's own settings, passkeys, password and notifications. Handlers check what a path cannot say: changing the
company's preferences (`api.put_preferences`) is administrator-only too.
"""
from .http import require_admin

# (prefix, whether a plain read is also for administrators only). The template and the logo are read by the screens that make an invoice.
ADMIN_ONLY = (
    ("/api/users", True),               # inviting, resetting, promoting and removing people
    ("/api/backup", True),              # backup and restore: the whole business, in one file
    ("/api/system", True),              # factory reset
    ("/api/update", True),              # the update check: only the person who can update the installation needs it
    ("/api/ai-images", True),           # the OpenAI key, its test and its log; making pictures goes through /api/projects/<id>/images
    ("/api/spoolman", False),           # syncing with Spoolman; the status is for everybody
    ("/api/invoice-template", False),   # uploading and removing the invoice template
    ("/api/invoice-logo", False),       # uploading and removing the invoice logo
)


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def is_admin_only(path: str, method: str) -> bool:
    reading = method in ("GET", "HEAD", "OPTIONS")
    return any(_matches(path, prefix) and (everything or not reading) for prefix, everything in ADMIN_ONLY)


def check(path: str, method: str) -> None:
    """Raises 401 for nobody signed in and 403 for a regular user, on a path that is for administrators only."""
    if is_admin_only(path, method):
        require_admin()

