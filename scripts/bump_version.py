#!/usr/bin/env python3
"""Raise VERSION on `beta`: every merged pull request that changed code or build files makes the number 0.1 higher.

Pull requests never touch VERSION (`check_version_bump.py` fails one that does; two that each raised it would collide), so the `docker-beta`
workflow raises it after the merge, on every push to `beta`, and builds the beta image from that commit. The promotion to `main` then
carries the number; the `docker` workflow publishes it and does not raise it again.

  python scripts/bump_version.py [--labels gh|none|FILE.json] [--push beta]     raise VERSION for what was merged since it last changed
  python scripts/bump_version.py --sync-addon                                   set the Home Assistant app's version to VERSION

How many 0.1s are due is read from the history, not from the push that started the run: GitHub keeps only one waiting run per workflow, so
two merges close together would otherwise earn one number. Every first-parent commit after the last one that changed VERSION is one merged pull
request; each that changed a protected, non-documentation path raises the **minor** number (`X.Y.Z` -> `X.(Y+1).0`). Its label chooses
another part: `version:major` (a breaking change or a milestone) or `version:patch` (a fix). Run twice, the second run finds nothing to do.

The Home Assistant app's `version` (homeassistant/config.yaml) is the tag of the image it is built on, and that tag exists only once a release has
been published. So raising VERSION leaves it alone, and `--sync-addon` (run by the `docker` workflow at a promotion) sets it.

Prints what it did and exits 0. It writes VERSION and, with `--push BRANCH`, commits it (`Version X.Y.Z`) and pushes it to origin.
A push that is refused because the branch moved is not rebased: the number is derived, so it starts again from what is there.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from check_version_bump import is_doc_only, is_protected, normalize, parse_version

PARTS = ("patch", "minor", "major")
DEFAULT_PART = "minor"                                   # every release is 0.1 higher; a label picks another part
ADDON_CONFIG = Path("homeassistant/config.yaml")
ADDON_VERSION = re.compile(r'^version: "\d+\.\d+\.\d+"$', re.M)
# Set by the release itself (`--sync-addon`) and carried back into beta by a merge: not the work of a pull request.
RELEASE_PATHS = {"homeassistant/config.yaml"}
PUSH_ATTEMPTS = 3


def git(*args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "--no-pager", *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise RuntimeError(f"`git {' '.join(args)}` failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout


def format_version(version: tuple) -> str:
    return ".".join(map(str, version))


def bump(version: tuple, part: str) -> tuple:
    major, minor, patch = version
    return {"major": (major + 1, 0, 0), "minor": (major, minor + 1, 0), "patch": (major, minor, patch + 1)}[part]


def part_for(labels) -> str:
    """The label of the pull request chooses the part; `major` wins over `patch`; without either it is the default."""
    if "version:major" in labels:
        return "major"
    if "version:patch" in labels:
        return "patch"
    return DEFAULT_PART


def last_version_commit(after: str) -> str:
    """The latest commit on the first-parent line that changed VERSION: what has been merged since is what is not counted yet."""
    found = git("log", "--first-parent", "-n", "1", "--format=%H", after, "--", "VERSION").strip()
    if not found:
        raise RuntimeError("VERSION has never changed on this branch, so there is nothing to count from. Pass --since <commit>.")
    return found


def merged_since(since: str, after: str) -> list:
    """Every first-parent commit after `since`, oldest first: one merged pull request each."""
    return git("rev-list", "--first-parent", "--reverse", f"{since}..{after}").split()


def changed_files(commit: str) -> list:
    """What this commit brought to the branch: the diff against its first parent (empty for a root commit)."""
    if len(git("rev-list", "--parents", "-n", "1", commit).split()) < 2:
        return []
    return [normalize(line) for line in git("diff", "--name-only", f"{commit}^1", commit).splitlines() if line.strip()]


def is_feature(files) -> bool:
    return any(is_protected(p) and not is_doc_only(p) and p not in RELEASE_PATHS for p in files)


def labels_from_github(commit: str) -> list:
    """The labels of the pull request that was merged as `commit` (none for a commit that is not a merged pull request)."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY is not set, so the pull request labels cannot be read (use --labels none).")
    done = subprocess.run(["gh", "api", f"repos/{repo}/commits/{commit}/pulls", "--jq", ".[].labels[].name"], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"Could not read the labels of the pull request merged in {commit[:7]}: {(done.stderr or done.stdout).strip()}\n"
                           "Without them a `version:major` could be missed, so nothing is raised; run the workflow again.")
    return done.stdout.splitlines()


def labels_source(spec: str):
    """`none`: every pull request gets the default part. `gh`: ask GitHub. Anything else is a JSON file {commit: [labels]} (tests)."""
    if spec == "none":
        return lambda commit: []
    if spec == "gh":
        return labels_from_github
    table = json.loads(Path(spec).read_text(encoding="utf-8"))
    return lambda commit: table.get(commit, [])


def plan(after: str = "HEAD", since: str = None, labels_for=lambda commit: []) -> tuple:
    """-> (the version `after` has, the version it should have, [(commit, part, version it makes), ...])."""
    current = git("show", f"{after}:VERSION").strip()
    version = parse_version(current)
    steps = []
    for commit in merged_since(since or last_version_commit(after), after):
        if not is_feature(changed_files(commit)):
            continue
        part = part_for(labels_for(commit))
        version = bump(version, part)
        steps.append((commit, part, format_version(version)))
    return current, format_version(version), steps


def write_addon_version(version: str) -> bool:
    """The Home Assistant app is built on the image of the same number (homeassistant/Dockerfile). True when the file changed."""
    if not ADDON_CONFIG.exists():
        return False
    text = ADDON_CONFIG.read_text(encoding="utf-8")
    if not ADDON_VERSION.search(text):
        raise ValueError(f'{ADDON_CONFIG} has no line `version: "X.Y.Z"` to raise.')
    changed = ADDON_VERSION.sub(f'version: "{version}"', text, count=1)
    ADDON_CONFIG.write_text(changed, encoding="utf-8")
    return changed != text


def raise_version(args) -> bool:
    """Write VERSION for what was merged and not yet counted. True when it changed."""
    current, new, steps = plan(args.after, args.since, labels_source(args.labels))
    for commit, part, version in steps:
        print(f"  {commit[:7]} {part:5} -> {version}")
    if new == current:
        print(f"Nothing merged since VERSION last changed raised it. VERSION stays {current}.")
        return False
    Path("VERSION").write_text(new, encoding="utf-8")
    print(f"VERSION raised: {current} -> {new}")
    return True


def commit_message(version: str, steps: list) -> str:
    return f"Version {version}\n\n" + "\n".join(f"{commit[:7]} {part} -> {v}" for commit, part, v in steps)


def raise_and_push(args) -> None:
    if git("status", "--porcelain").strip():
        raise RuntimeError("The working tree has changes; --push commits VERSION and may reset the checkout, so it starts from a clean one.")
    last = ""
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        current, new, steps = plan(args.after, args.since, labels_source(args.labels))
        for commit, part, version in steps:
            print(f"  {commit[:7]} {part:5} -> {version}")
        if new == current:                           # nothing merged that counts (or a run that ran meanwhile already raised it)
            print(f"Nothing merged since VERSION last changed raised it. VERSION stays {current}.")
            return
        Path("VERSION").write_text(new, encoding="utf-8")
        git("commit", "-m", commit_message(new, steps), "VERSION")
        pushed = subprocess.run(["git", "--no-pager", "push", "origin", f"HEAD:{args.push}"], capture_output=True, text=True)
        if pushed.returncode == 0:
            print(f"VERSION raised: {current} -> {new} (pushed to {args.push})")
            return
        last = (pushed.stderr or pushed.stdout).strip()
        print(f"Push {attempt} of {PUSH_ATTEMPTS} was refused; starting again from {args.push} as it is now.", file=sys.stderr)
        git("fetch", "origin", args.push)
        git("reset", "--hard", "FETCH_HEAD")
    raise RuntimeError(f"Could not push the VERSION bump to {args.push}: {last}\n"
                       "Let github-actions push to it (a ruleset bypass if it is protected), or run the workflow again.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--after", default="HEAD", help="the commit to count up to (the tip of beta)")
    parser.add_argument("--since", help="count from this commit instead of the last one that changed VERSION")
    parser.add_argument("--labels", default="none", help="`gh` reads the pull request labels from GitHub, `none` gives every pull request the default part, or a JSON file {commit: [labels]}")
    parser.add_argument("--push", metavar="BRANCH", help="commit the new VERSION and push it to origin/BRANCH")
    parser.add_argument("--sync-addon", action="store_true", help="set the Home Assistant app's version to VERSION and do nothing else")
    args = parser.parse_args()

    if args.sync_addon:
        version = Path("VERSION").read_text(encoding="utf-8").strip()
        parse_version(version)
        print(f"Home Assistant app set to {version}." if write_addon_version(version) else f"Home Assistant app already at {version}.")
        return 0
    if args.push:
        raise_and_push(args)
    else:
        raise_version(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
