#!/usr/bin/env python3
"""Create .env from .env.example with fresh random secrets.

    python scripts/init_env.py --port 6090 --domain print.example.com

Without --domain it configures http://localhost:<port>, which is enough to try the app.
Refuses to overwrite an existing .env.
"""
import argparse
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=6080, help="web port (WEB_PORT)")
    parser.add_argument("--domain", help="public domain for passkeys, e.g. print.example.com (uses https)")
    parser.add_argument("--data-path", default="./data")
    args = parser.parse_args()

    target = ROOT / ".env"
    if target.exists():
        print(".env already exists; not overwriting it.", file=sys.stderr)
        return 1

    if args.domain:
        rp_id, origin = args.domain, f"https://{args.domain}"
    else:
        rp_id, origin = "localhost", f"http://localhost:{args.port}"

    values = {
        "WEB_PORT": str(args.port),
        "DATA_PATH": args.data_path,
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "RP_ID": rp_id,
        "RP_ORIGINS": origin,
        "SETUP_CODE": secrets.token_hex(4),
        "SESSION_SECRET": secrets.token_hex(32),
    }
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key, value in values.items():
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    target.write_text(text, encoding="utf-8")
    target.chmod(0o600)
    print(f"Wrote .env (port {args.port}, origin {origin}).")
    print(f"Setup code for onboarding: {values['SETUP_CODE']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
