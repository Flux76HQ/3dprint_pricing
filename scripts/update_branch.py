#!/usr/bin/env python3
"""Bring the current branch up to date with beta (the branch pull requests target), resolving the conflicts that are only bookkeeping.

Two pull requests that add the next migration or regenerate the screenshots collide every time the other one merges first,
although nothing in them contradicts each other. Run this instead of `git merge origin/beta`:

  * VERSION: the base branch's (a pull request does not change it; the pipeline raises it when beta is promoted to main).
  * A migration this branch added whose number the base branch has taken meanwhile: renamed to the next free number.
  * docs/assets/*.png: the base branch's file (they are generated; re-run scripts/generate_screenshots.py if this change alters a screen).
  * Anything else that conflicts is left for you, with the merge still open.

Usage: python scripts/update_branch.py [--base-ref origin/beta] [--no-fetch]
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

MIGRATIONS = "backend/app/migrations_sqlite"
SCREENSHOTS = "docs/assets"


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "--no-pager", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def migration_number(name: str) -> int | None:
    match = re.match(r"(\d{4})_.+\.sql$", Path(name).name)
    return int(match.group(1)) if match else None


def renumber_migrations(base_ref: str, merge_base: str, notes: list) -> None:
    added = [p for p in git("diff", "--name-only", "--diff-filter=A", merge_base, "HEAD", "--", MIGRATIONS).split() if migration_number(p) is not None]
    taken = {migration_number(p): p for p in git("ls-tree", "--name-only", base_ref, f"{MIGRATIONS}/").split() if migration_number(p) is not None}
    for path in sorted(added):
        number = migration_number(path)
        if number not in taken or taken[number] == path:
            continue
        existing = {migration_number(p) for p in Path(MIGRATIONS).glob("*.sql")} | set(taken)
        free = max(existing) + 1
        target = f"{MIGRATIONS}/{free:04d}{Path(path).name[4:]}"
        git("mv", path, target)
        taken[free] = target
        notes.append(f"migration {Path(path).name} -> {Path(target).name} (number {number:04d} is the base branch's {Path(taken[number]).name})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-ref", default="origin/beta")
    parser.add_argument("--no-fetch", action="store_true", help="use the base ref as it is (for tests)")
    args = parser.parse_args()
    base_ref = args.base_ref

    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("Commit or stash your changes first.", file=sys.stderr)
        return 1
    if not args.no_fetch:
        remote, _, branch = base_ref.partition("/")
        git("fetch", "-q", remote, branch)
    merge_base = git("merge-base", "HEAD", base_ref).strip()
    notes: list = []

    if git("rev-list", "--count", f"HEAD..{base_ref}").strip() == "0":
        print(f"Already up to date with {base_ref}.")
        return 0
    merge = subprocess.run(["git", "merge", "--no-commit", "--no-ff", base_ref], capture_output=True, text=True)
    conflicted = git("diff", "--name-only", "--diff-filter=U").split()
    if merge.returncode != 0 and not conflicted:
        print(merge.stdout + merge.stderr, file=sys.stderr)
        git("merge", "--abort", check=False)
        return 1

    for path in list(conflicted):
        if path.startswith(f"{SCREENSHOTS}/") and path.endswith(".png"):
            git("checkout", "--theirs", "--", path)
            git("add", path)
            conflicted.remove(path)
            notes.append(f"{path}: the base branch's file taken (re-run scripts/generate_screenshots.py if this change alters how a screen looks)")
    if "VERSION" in conflicted:                           # a branch from before this rule: the base branch's number stands
        git("checkout", "--theirs", "--", "VERSION")
        git("add", "VERSION")
        conflicted.remove("VERSION")
        notes.append("VERSION: the base branch's number taken (a pull request leaves it alone)")
    renumber_migrations(base_ref, merge_base, notes)

    for note in notes:
        print(f"  {note}")
    if conflicted:
        print("\nStill in conflict (resolve, `git add`, then `git commit`):\n  " + "\n  ".join(conflicted), file=sys.stderr)
        return 1
    git("commit", "--no-edit", "-q")
    print(f"Merged {base_ref}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
