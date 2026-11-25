#!/usr/bin/env python3
"""Tests for bump_version (beta raises VERSION for what was merged) and check_version_bump (the pull request guard), on throwaway repositories.

The repositories have real merge commits, like the ones GitHub makes for a merged pull request, and a real bare remote for the push.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import bump_version
import check_version_bump

CONFIG = 'name: x\nversion: "{}"\nslug: y\n'


class RepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.old_cwd = os.getcwd()
        self.addCleanup(os.chdir, self.old_cwd)
        os.chdir(self.root)
        self.git("init", "-q", "-b", "beta")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.write("VERSION", "1.2.3")
        self.write("README.md", "hello\n")
        self.write("backend/app.py", "x = 1\n")
        self.write("homeassistant/config.yaml", CONFIG.format("1.2.3"))
        self.commit("Release 1.2.3")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True, cwd=cwd).stdout

    def write(self, path, text, base=None):
        target = (base or self.root) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message, cwd=None):
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "-m", message, cwd=cwd)

    def merge(self, number, files, cwd=None):
        """A pull request, merged the way GitHub does it: a merge commit on beta. Returns its hash."""
        branch = f"pr-{number}"
        self.git("checkout", "-q", "-b", branch, "beta", cwd=cwd)
        for path, text in files.items():
            self.write(path, text, base=Path(cwd) if cwd else None)
        self.commit(f"work for {number}", cwd=cwd)
        self.git("checkout", "-q", "beta", cwd=cwd)
        self.git("merge", "-q", "--no-ff", "-m", f"Merge pull request #{number}", branch, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd).strip()

    def labels(self, table):
        path = self.tmp / "labels.json"
        path.write_text(json.dumps(table), encoding="utf-8")
        return str(path)

    def run_main(self, module, *argv):
        old = sys.argv
        sys.argv = [module.__name__ + ".py", *argv]
        try:
            return module.main()
        finally:
            sys.argv = old

    def bump(self, *extra):
        return self.run_main(bump_version, *extra)

    def version(self, cwd=None):
        return ((Path(cwd) if cwd else self.root) / "VERSION").read_text(encoding="utf-8")


class HowManyNumbersAreDueTest(RepoTestCase):
    def test_a_merged_pull_request_that_changed_code_raises_the_minor_number(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.assertEqual(self.bump(), 0)
        self.assertEqual(self.version(), "1.3.0")             # 0.1 higher, and the patch number starts over

    def test_every_merged_pull_request_is_a_tenth_higher(self):
        for number in (1, 2, 3):
            self.merge(number, {"backend/app.py": f"x = {number + 1}\n"})
        self.bump()
        self.assertEqual(self.version(), "1.5.0")

    def test_documentation_alone_leaves_the_version(self):
        self.merge(1, {"README.md": "changed\n", "docs/notes.txt": "x\n"})
        self.bump()
        self.assertEqual(self.version(), "1.2.3")

    def test_a_path_that_is_not_protected_leaves_the_version(self):
        self.merge(1, {"library/filaments.json": "[]\n"})
        self.bump()
        self.assertEqual(self.version(), "1.2.3")

    def test_a_dockerfile_counts_as_code(self):
        self.merge(1, {"Dockerfile": "FROM scratch\n"})
        self.bump()
        self.assertEqual(self.version(), "1.3.0")

    def test_a_change_to_the_home_assistant_app_counts_as_code(self):
        self.merge(1, {"homeassistant/run.py": "x = 1\n"})
        self.bump()
        self.assertEqual(self.version(), "1.3.0")

    def test_a_commit_made_straight_on_beta_counts_like_a_merged_pull_request(self):
        self.write("backend/app.py", "x = 9\n")
        self.commit("direct")
        self.bump()
        self.assertEqual(self.version(), "1.3.0")

    def test_the_release_carried_back_into_beta_is_not_a_feature(self):
        # main sets the Home Assistant app's version in a release commit and that commit is merged back: not the work of a pull request.
        self.git("checkout", "-q", "-b", "main-release", "beta")
        self.write("homeassistant/config.yaml", CONFIG.format("1.4.0"))
        self.commit("Release 1.4.0")
        self.git("checkout", "-q", "beta")
        self.merge(1, {"backend/app.py": "x = 2\n"})            # beta moved on meanwhile, so the merge-back is a real merge commit
        self.git("merge", "-q", "--no-ff", "-m", "Merge main into beta", "main-release")
        self.bump()
        self.assertEqual(self.version(), "1.3.0")                # one feature (#1), not two

    def test_raising_leaves_the_home_assistant_app_alone(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.bump()
        self.assertEqual((self.root / "homeassistant/config.yaml").read_text(), CONFIG.format("1.2.3"))   # its image does not exist yet


class TheLabelChoosesThePartTest(RepoTestCase):
    def test_a_major_label_raises_the_major_number_and_the_next_one_continues_from_it(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        second = self.merge(2, {"backend/app.py": "x = 3\n"})
        self.merge(3, {"backend/app.py": "x = 4\n"})
        self.bump("--labels", self.labels({second: ["enhancement", "version:major"]}))
        self.assertEqual(self.version(), "2.1.0")                # 1.3.0, then 2.0.0, then 2.1.0

    def test_a_patch_label_raises_the_patch_number(self):
        only = self.merge(1, {"backend/app.py": "x = 2\n"})
        self.bump("--labels", self.labels({only: ["version:patch"]}))
        self.assertEqual(self.version(), "1.2.4")

    def test_a_minor_pull_request_after_a_patch_one_starts_the_patch_number_over(self):
        first = self.merge(1, {"backend/app.py": "x = 2\n"})
        self.merge(2, {"backend/app.py": "x = 3\n"})
        self.bump("--labels", self.labels({first: ["version:patch"]}))
        self.assertEqual(self.version(), "1.3.0")                 # patch (1.2.4), then minor (1.3.0)

    def test_major_wins_when_both_labels_are_there(self):
        only = self.merge(1, {"backend/app.py": "x = 2\n"})
        self.bump("--labels", self.labels({only: ["version:patch", "version:major"]}))
        self.assertEqual(self.version(), "2.0.0")

    def test_a_label_on_a_pull_request_that_changed_only_documentation_changes_nothing(self):
        only = self.merge(1, {"README.md": "x\n"})
        self.bump("--labels", self.labels({only: ["version:major"]}))
        self.assertEqual(self.version(), "1.2.3")

    def test_the_part_of_a_label_list(self):
        self.assertEqual(bump_version.part_for([]), "minor")
        self.assertEqual(bump_version.part_for(["bug", "dependencies"]), "minor")
        self.assertEqual(bump_version.part_for(["version:patch"]), "patch")
        self.assertEqual(bump_version.part_for(["version:minor"]), "minor")       # the default; the old label means nothing more
        self.assertEqual(bump_version.part_for(["version:major"]), "major")

    def test_the_numbers_a_major_release_restarts(self):
        self.assertEqual(bump_version.bump((1, 7, 2), "major"), (2, 0, 0))
        self.assertEqual(bump_version.bump((2, 0, 0), "minor"), (2, 1, 0))
        self.assertEqual(bump_version.bump((2, 1, 5), "minor"), (2, 2, 0))
        self.assertEqual(bump_version.bump((2, 1, 5), "patch"), (2, 1, 6))


class OnlyWhatIsNotCountedYetTest(RepoTestCase):
    def raise_and_commit(self):
        self.bump()
        self.commit(f"Version {self.version()}")

    def test_running_it_twice_raises_nothing_twice(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.raise_and_commit()
        self.assertEqual(self.version(), "1.3.0")
        self.bump()
        self.assertEqual(self.version(), "1.3.0")

    def test_a_pull_request_merged_after_a_bump_is_counted_by_the_next_one_only(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.raise_and_commit()
        self.merge(2, {"backend/app.py": "x = 3\n"})
        self.merge(3, {"backend/app.py": "x = 4\n"})
        self.raise_and_commit()
        self.assertEqual(self.version(), "1.5.0")                 # 1.3.0, then two more

    def test_a_run_that_was_dropped_is_made_up_by_the_next_one(self):
        # Three merges close together: GitHub runs the first and the last and drops the one that was waiting. One run still counts all three.
        for number in (1, 2, 3):
            self.merge(number, {"backend/app.py": f"x = {number + 1}\n"})
        self.raise_and_commit()
        self.assertEqual(self.version(), "1.5.0")

    def test_a_hand_made_change_of_version_is_where_counting_starts(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.write("VERSION", "3.0.0")
        self.commit("Version 3.0.0 by hand")
        self.merge(2, {"backend/app.py": "x = 3\n"})
        self.bump()
        self.assertEqual(self.version(), "3.1.0")

    def test_it_can_be_told_where_to_start(self):
        first = self.merge(1, {"backend/app.py": "x = 2\n"})
        self.merge(2, {"backend/app.py": "x = 3\n"})
        self.bump("--since", first)
        self.assertEqual(self.version(), "1.3.0")                 # only the one after `first`

    def test_a_history_where_version_never_changed_says_so_instead_of_counting_everything(self):
        self.git("checkout", "-q", "--orphan", "bare")
        self.git("rm", "-rqf", ".")
        self.write("backend/app.py", "x = 1\n")
        self.commit("no version file here")
        with self.assertRaises(RuntimeError) as caught:
            bump_version.last_version_commit("HEAD")
        self.assertIn("never changed", str(caught.exception))


class SyncTheHomeAssistantAppTest(RepoTestCase):
    def test_it_is_set_to_the_version(self):
        self.write("VERSION", "2.4.0")
        self.assertEqual(self.bump("--sync-addon"), 0)
        self.assertEqual((self.root / "homeassistant/config.yaml").read_text(), CONFIG.format("2.4.0"))

    def test_it_changes_nothing_when_it_is_there_already(self):
        self.assertEqual(self.bump("--sync-addon"), 0)
        self.assertEqual((self.root / "homeassistant/config.yaml").read_text(), CONFIG.format("1.2.3"))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_config_without_a_version_line_is_an_error(self):
        self.write("homeassistant/config.yaml", "name: x\n")
        with self.assertRaises(ValueError):
            self.bump("--sync-addon")


class ReadingTheLabelsFromGitHubTest(RepoTestCase):
    def stub_gh(self, body):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        gh = bin_dir / "gh"
        gh.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
        os.environ["GITHUB_REPOSITORY"] = "owner/repo"

    def test_the_labels_of_the_pull_request_come_back_as_a_list(self):
        self.stub_gh('echo "$2" > "$(dirname "$0")/asked"; printf "enhancement\\nversion:major\\n"')
        self.assertEqual(bump_version.labels_from_github("abcdef1234"), ["enhancement", "version:major"])
        self.assertEqual((self.tmp / "bin" / "asked").read_text().strip(), "repos/owner/repo/commits/abcdef1234/pulls")

    def test_a_commit_that_is_no_pull_request_has_no_labels(self):
        self.stub_gh("exit 0")
        self.assertEqual(bump_version.labels_from_github("abcdef1234"), [])

    def test_when_github_cannot_be_asked_nothing_is_raised(self):
        self.stub_gh('echo "HTTP 502" >&2; exit 1')
        self.merge(1, {"backend/app.py": "x = 2\n"})
        with self.assertRaises(RuntimeError) as caught:
            self.bump("--labels", "gh")
        self.assertIn("nothing is raised", str(caught.exception))
        self.assertEqual(self.version(), "1.2.3")                 # a `version:major` could have been missed: no guess

    def test_without_a_repository_it_says_so(self):
        os.environ.pop("GITHUB_REPOSITORY", None)
        with self.assertRaises(RuntimeError):
            bump_version.labels_from_github("abcdef1234")

    def test_the_labels_are_read_through_gh_end_to_end(self):
        self.stub_gh('printf "version:major\\n"')
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.bump("--labels", "gh")
        self.assertEqual(self.version(), "2.0.0")


class PushingTheNumberTest(RepoTestCase):
    """The workflow's one command: `bump_version.py --push beta`, against a real remote that other people push to meanwhile."""

    def setUp(self):
        super().setUp()
        self.remote = self.tmp / "remote.git"
        self.git("init", "-q", "--bare", "-b", "beta", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "-u", "origin", "beta")
        self.other = self.tmp / "other"
        self.git("clone", "-q", str(self.remote), str(self.other))
        self.git("config", "user.email", "o@example.com", cwd=self.other)
        self.git("config", "user.name", "O", cwd=self.other)

    def remote_version(self):
        return self.git("show", "beta:VERSION", cwd=self.remote)

    def remote_log(self):
        return self.git("log", "--first-parent", "--format=%s", "beta", cwd=self.remote).splitlines()

    def test_the_number_is_committed_and_pushed_with_what_it_counted(self):
        sha = self.merge(1, {"backend/app.py": "x = 2\n"})
        self.git("push", "-q", "origin", "beta")
        self.assertEqual(self.bump("--push", "beta"), 0)
        self.assertEqual(self.remote_version(), "1.3.0")
        self.assertEqual(self.remote_log()[0], "Version 1.3.0")
        body = self.git("log", "-1", "--format=%b", "beta", cwd=self.remote)
        self.assertIn(f"{sha[:7]} minor -> 1.3.0", body)

    def test_nothing_is_pushed_when_nothing_is_due(self):
        self.merge(1, {"README.md": "changed\n"})
        self.git("push", "-q", "origin", "beta")
        before = self.git("rev-parse", "beta", cwd=self.remote)
        self.bump("--push", "beta")
        self.assertEqual(self.git("rev-parse", "beta", cwd=self.remote), before)

    def test_a_push_that_is_refused_starts_again_from_what_is_there_instead_of_rebasing(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.git("push", "-q", "origin", "beta")
        # Meanwhile somebody merges another pull request that changed code; this checkout does not have it yet.
        self.git("pull", "-q", "origin", "beta", cwd=self.other)
        self.write("backend/app.py", "x = 3\n", base=self.other)
        self.git("checkout", "-q", "-b", "pr-2", cwd=self.other)
        self.commit("work for 2", cwd=self.other)
        self.git("checkout", "-q", "beta", cwd=self.other)
        self.git("merge", "-q", "--no-ff", "-m", "Merge pull request #2", "pr-2", cwd=self.other)
        self.git("push", "-q", "origin", "beta", cwd=self.other)

        self.bump("--push", "beta")
        self.assertEqual(self.remote_version(), "1.4.0")           # both, counted once each
        log = self.remote_log()
        self.assertEqual(log[0], "Version 1.4.0")
        self.assertEqual(log.count("Version 1.4.0") + log.count("Version 1.3.0"), 1)   # one bump commit, not one per attempt

    def test_when_the_other_push_already_raised_it_nothing_is_raised_twice(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.git("push", "-q", "origin", "beta")
        self.git("pull", "-q", "origin", "beta", cwd=self.other)
        self.write("VERSION", "1.3.0", base=self.other)
        self.commit("Version 1.3.0", cwd=self.other)
        self.git("push", "-q", "origin", "beta", cwd=self.other)
        self.bump("--push", "beta")
        self.assertEqual(self.remote_version(), "1.3.0")
        self.assertEqual(self.remote_log().count("Version 1.3.0"), 1)

    def test_it_gives_up_loudly_when_the_branch_cannot_be_pushed_to(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.git("push", "-q", "origin", "beta")
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
        with self.assertRaises(RuntimeError) as caught:
            self.bump("--push", "beta")
        self.assertIn("Could not push the VERSION bump to beta", str(caught.exception))
        self.assertIn("protected branch", str(caught.exception))
        self.assertEqual(self.remote_version(), "1.2.3")

    def test_it_refuses_to_start_on_a_checkout_with_changes(self):
        self.merge(1, {"backend/app.py": "x = 2\n"})
        self.write("backend/app.py", "uncommitted\n")
        with self.assertRaises(RuntimeError):
            self.bump("--push", "beta")
        self.assertEqual((self.root / "backend/app.py").read_text(), "uncommitted\n")      # and it did not reset them away


class PullRequestGuardTest(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.git("update-ref", "refs/remotes/origin/beta", "beta")
        self.git("checkout", "-q", "-b", "feature")

    def guard(self, *extra, base="origin/beta"):
        old = sys.argv
        sys.argv = ["check_version_bump.py", "--base-ref", base, *extra]
        try:
            return check_version_bump.main()
        except (RuntimeError, ValueError) as exc:
            self.message = str(exc)
            return 1
        finally:
            sys.argv = old

    def test_a_pull_request_that_leaves_version_alone_passes_with_or_without_code(self):
        self.write("backend/app.py", "x = 2\n")
        self.commit("code")
        self.assertEqual(self.guard(), 0)

    def test_a_pull_request_that_changes_version_fails_and_says_how_to_fix_it(self):
        self.write("VERSION", "1.2.4")
        self.write("backend/app.py", "x = 2\n")
        self.commit("code and a bump")
        self.assertEqual(self.guard(), 1)
        self.assertIn("git checkout origin/beta -- VERSION", self.message)
        self.assertIn("version:major", self.message)
        self.assertIn("version:patch", self.message)
        self.assertIn("merged into beta", self.message)

    def test_beta_having_raised_version_since_the_branch_started_is_not_the_branch_changing_it(self):
        self.git("checkout", "-q", "beta")
        self.write("VERSION", "1.3.0")
        self.commit("Version 1.3.0")
        self.git("update-ref", "refs/remotes/origin/beta", "beta")
        self.git("checkout", "-q", "feature")
        self.write("backend/app.py", "x = 2\n")
        self.commit("code")
        self.assertEqual(self.guard(), 0)

    def promotion(self, head_version, base_version="1.2.3"):
        """main has `base_version`; beta (the head of the promotion) has `head_version`. A commit may be empty when the two are the same."""
        self.git("checkout", "-q", "beta")
        self.write("VERSION", base_version)
        self.git("commit", "-q", "--allow-empty", "-am", "main's version")
        self.git("update-ref", "refs/remotes/origin/main", "beta")
        self.write("VERSION", head_version)
        self.git("commit", "-q", "--allow-empty", "-am", "beta raised it")
        return self.guard("--promotion", base="origin/main")

    def test_a_promotion_carries_the_version_beta_raised(self):
        self.assertEqual(self.promotion("1.5.0"), 0)

    def test_a_promotion_that_raised_nothing_passes(self):
        self.assertEqual(self.promotion("1.2.3"), 0)

    def test_a_promotion_cannot_lower_the_version(self):
        self.assertEqual(self.promotion("1.1.0"), 1)
        self.assertIn("lower VERSION", self.message)
        self.assertIn("main has 1.2.3", self.message)

    def test_a_version_is_compared_as_numbers_not_as_text(self):
        self.assertEqual(self.promotion("1.10.0", base_version="1.9.0"), 0)

    def test_a_promotion_with_an_invalid_version_fails(self):
        self.assertEqual(self.promotion("one.two"), 1)
        self.assertIn("Invalid VERSION", self.message)


if __name__ == "__main__":
    unittest.main()
