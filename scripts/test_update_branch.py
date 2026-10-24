#!/usr/bin/env python3
"""Tests for update_branch: each test builds a throwaway repository with a main and a feature branch that collide only in bookkeeping."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import update_branch

MIG = "backend/app/migrations"
PNG = "docs/assets/orders.png"


class UpdateBranchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.old_cwd = os.getcwd()
        self.addCleanup(os.chdir, self.old_cwd)
        os.chdir(self.root)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.write("VERSION", "0.1.0")
        self.write(f"{MIG}/0001_init.sql", "-- init")
        self.write("README.md", "one\n")
        self.write(PNG, "base")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")

    def git(self, *args):
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def on_main(self, change):
        self.git("checkout", "-q", "main")
        change()
        self.commit("main moves on")
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("checkout", "-q", "feature")

    def run_script(self):
        import sys
        old = sys.argv
        sys.argv = ["update_branch.py", "--no-fetch"]
        try:
            return update_branch.main()
        finally:
            sys.argv = old

    def read(self, path):
        return (self.root / path).read_text(encoding="utf-8")

    def test_migrations_and_screenshots_collide_and_are_resolved(self):
        self.write(f"{MIG}/0002_mine.sql", "-- mine")
        self.write(PNG, "mine")
        self.commit("feature")
        self.on_main(lambda: (self.write(f"{MIG}/0002_theirs.sql", "-- theirs"), self.write(PNG, "theirs")))
        self.assertEqual(self.run_script(), 0)
        self.assertEqual(self.read(f"{MIG}/0002_theirs.sql"), "-- theirs")
        self.assertEqual(self.read(f"{MIG}/0003_mine.sql"), "-- mine")
        self.assertFalse((self.root / f"{MIG}/0002_mine.sql").exists())
        self.assertEqual(self.read(PNG), "theirs")
        self.assertEqual(self.git("status", "--porcelain").strip(), "")     # committed

    def test_a_branch_that_still_bumps_version_takes_mains_number(self):
        self.write("VERSION", "0.2.0")
        self.commit("feature (from before the rule)")
        self.on_main(lambda: self.write("VERSION", "0.1.1"))
        self.assertEqual(self.run_script(), 0)
        self.assertEqual(self.read("VERSION"), "0.1.1")

    def test_a_real_conflict_is_left_open_for_the_human(self):
        self.write("README.md", "feature\n")
        self.commit("feature")
        self.on_main(lambda: self.write("README.md", "main\n"))
        self.assertEqual(self.run_script(), 1)
        self.assertIn("<<<<<<<", self.read("README.md"))
        self.assertIn("README.md", self.git("diff", "--name-only", "--diff-filter=U"))

    def test_nothing_to_do_when_main_has_not_moved(self):
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.assertEqual(self.run_script(), 0)


if __name__ == "__main__":
    unittest.main()
