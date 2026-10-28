#!/usr/bin/env python3
"""Create .env from .env.example with fresh random secrets.

    python scripts/init_env.py --port 6090 --domain print.example.com

Without --domain it leaves RP_ID and RP_ORIGINS empty: the app then follows the address it is opened on, which is enough to try
it (also on an IP address, with a password; a passkey needs a domain and https).
Refuses to overwrite an existing .env.
"""
import argparse
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_vapid import generate as generate_vapid  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=6080, help="web port (WEB_PORT)")
    parser.add_argument("--domain", help="public domain to pin the app to, e.g. print.example.com (uses https; passkeys are bound to it)")
    parser.add_argument("--data-path", default=str(ROOT / "data"), help="ABSOLUTE folder of the host for the database (db/) and the uploads (uploads/); default: data/ in this checkout")
    args = parser.parse_args()
    if not args.data_path.startswith("/"):
        parser.error("--data-path must be an absolute path: a relative one is resolved by whatever tool starts the stack (see .env.example)")

    target = ROOT / ".env"
    if target.exists():
        print(".env already exists; not overwriting it.", file=sys.stderr)
        return 1

    rp_id, origin = (args.domain, f"https://{args.domain}") if args.domain else ("", "")

    values = {
        "WEB_PORT": str(args.port),
        "DATA_PATH": args.data_path,
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "RP_ID": rp_id,
        "RP_ORIGINS": origin,
        "SETUP_CODE": secrets.token_hex(4),
        "SESSION_SECRET": secrets.token_hex(32),
        **generate_vapid(),                      # web push keys
    }
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key, value in values.items():
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    target.write_text(text, encoding="utf-8")
    target.chmod(0o600)
    print(f"Wrote .env (port {args.port}, {'origin ' + origin if origin else 'no domain: RP_ID and RP_ORIGINS are empty'}).")
    print(f"Setup code for onboarding: {values['SETUP_CODE']}")
    print("Enter it in the 'Setup code' field on the first screen of the app. It stays in .env as SETUP_CODE=.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
