#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from pathlib import Path


PROTECTED_PATTERNS = (
    re.compile(r"^backend/"),
    re.compile(r"^frontend/"),
    re.compile(r"^deploy/"),
    re.compile(r"^scripts/"),
    re.compile(r"^\.github/workflows/"),
    re.compile(r"^\.github/copilot-instructions\.md$"),
    re.compile(r"^Dockerfile$"),
    re.compile(r"^docker-compose\.yml$"),
    re.compile(r"^\.env\.example$"),
)


def run_git(*args: str, allow_fail: bool = False) -> str:
    result = subprocess.run(
        ["git", "--no-pager", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not allow_fail:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def normalize(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_doc_only(path: str) -> bool:
    return path.lower().endswith(".md") or path.lower().endswith(".txt")


def is_protected(path: str) -> bool:
    return any(pattern.search(path) for pattern in PROTECTED_PATTERNS)


def parse_semver(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(f"Invalid semver format '{version}'. Expected MAJOR.MINOR.PATCH")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_newer(head: tuple[int, int, int], base: tuple[int, int, int]) -> bool:
    return head > base


def get_changed_files(base_ref: str, staged: bool) -> list[str]:
    if staged:
        out = run_git("diff", "--cached", "--name-only")
    else:
        out = run_git("diff", "--name-only", f"{base_ref}...HEAD")
    files = [normalize(line) for line in out.splitlines() if line.strip()]
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()

    files = get_changed_files(args.base_ref, args.staged)
    if not files:
        print("No changed files detected. Version guard passed.")
        return 0

    protected_non_doc = [p for p in files if is_protected(p) and not is_doc_only(p)]
    if not protected_non_doc:
        print("Only docs or non-protected files changed. Version bump not required.")
        return 0

    version_path = Path("VERSION")
    if not version_path.exists():
        raise RuntimeError(
            "Protected paths changed but VERSION file is missing. "
            "Add VERSION with semver format, e.g. 0.1.0."
        )

    if "VERSION" not in files:
        changed = "\n".join(f" - {p}" for p in protected_non_doc)
        raise RuntimeError(
            "Protected paths changed but VERSION was not updated.\n"
            f"Changed protected paths:\n{changed}\n"
            "Fix: bump VERSION (MAJOR.MINOR.PATCH) before commit/PR."
        )

    head_raw = version_path.read_text(encoding="utf-8").strip()
    head = parse_semver(head_raw)

    if args.staged:
        print("Staged check: VERSION changed with valid semver. Guard passed.")
        return 0

    base_raw = run_git("show", f"{args.base_ref}:VERSION", allow_fail=True).strip()
    if not base_raw:
        print(f"Base VERSION not found on {args.base_ref}; valid current semver detected. Guard passed.")
        return 0

    base = parse_semver(base_raw)
    if not is_newer(head, base):
        raise RuntimeError(f"VERSION must increase when protected paths change. Base={base_raw}, Head={head_raw}.")

    print(f"Version bump validated. Base={base_raw}, Head={head_raw}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
