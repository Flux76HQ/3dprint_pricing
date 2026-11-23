#!/usr/bin/env python3
"""Pull-request guard: a pull request into beta must not change VERSION; a promotion to main carries it.

VERSION is raised by the pipeline after a merge into beta (`bump_version.py`, run by the `docker-beta` workflow). A pull request that raises it
itself collides with every other pull request that does the same, which is the conflict this rule exists to remove. The promotion (beta into
main) is the one pull request whose diff holds a VERSION change, because beta has raised it since the last promotion; it must not lower it.

Also holds the list of protected paths that `bump_version.py` uses to decide whether a merge earns a new version.
"""
import argparse
import re
import subprocess
import sys

PROTECTED_PATTERNS = (
    re.compile(r"^backend/"),
    re.compile(r"^frontend/"),
    re.compile(r"^deploy/"),
    re.compile(r"^homeassistant/"),
    re.compile(r"^repository\.yaml$"),
    re.compile(r"^scripts/"),
    re.compile(r"^\.github/workflows/"),
    re.compile(r"^\.github/copilot-instructions\.md$"),
    re.compile(r"^Dockerfile$"),
    re.compile(r"^docker-compose(\.build)?\.yml$"),
    re.compile(r"^\.env\.example$"),
)


def parse_version(value: str) -> tuple:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise ValueError(f"Invalid VERSION '{value.strip()}'. Expected MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in match.groups())


def normalize(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_doc_only(path: str) -> bool:
    return path.lower().endswith(".md") or path.lower().endswith(".txt")


def is_protected(path: str) -> bool:
    return any(pattern.search(path) for pattern in PROTECTED_PATTERNS)


def changed_files(base_ref: str) -> list:
    out = subprocess.run(["git", "--no-pager", "diff", "--name-only", f"{base_ref}...HEAD"], capture_output=True, text=True, check=True).stdout
    return [normalize(line) for line in out.splitlines() if line.strip()]


def version_at(ref: str) -> str:
    return subprocess.run(["git", "--no-pager", "show", f"{ref}:VERSION"], capture_output=True, text=True, check=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-ref", default="origin/beta")
    parser.add_argument("--promotion", action="store_true", help="the pull request is the promotion into main: it carries VERSION, which must not go down")
    args = parser.parse_args()

    if args.promotion:
        base, head = version_at(args.base_ref), version_at("HEAD")
        if parse_version(head) < parse_version(base):
            raise RuntimeError(f"This promotion would lower VERSION: {args.base_ref} has {base.strip()}, beta has {head.strip()}. "
                               "Merge main into beta first (`python scripts/update_branch.py --base-ref origin/main`).")
        print(f"This promotion carries VERSION {head.strip()} ({args.base_ref} has {base.strip()}); the docker workflow publishes it.")
        return 0
    if "VERSION" in changed_files(args.base_ref):
        raise RuntimeError(
            "This pull request changes VERSION, but the pipeline raises it when a pull request is merged into beta.\n"
            f"Fix: restore it (`git checkout {args.base_ref} -- VERSION`). Every merged pull request that changes code makes the number 0.1 higher; for a\n"
            "major or a patch release instead, put the label `version:major` or `version:patch` on this pull request.")
    print("VERSION is untouched; it is raised when this pull request is merged into beta.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
