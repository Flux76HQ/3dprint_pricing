"""`docs/app-engineering-conformance.md` answers every topic, and what it points at exists.

App-Guidance's baseline (section 18) asks an app to declare, for each of its 111 engineering topics, whether it applies and what
shows it. Its validator (`scripts/check_app_engineering.py` there) checks that the question was answered; this test does the same
here, where the pull requests are, because that repository does not see this one. It adds one check of its own: a file the
declaration names as evidence or as the control of a topic has to exist, so renaming a test does not leave a row pointing at nothing.

It cannot check that an answer is true. That takes a reader."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = ROOT / "docs/app-engineering-conformance.md"
TOPICS = 111
STATUSES = ("applies", "partial", "not-now", "n/a")
ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$")
SAYS_NOTHING = {"", "-", "—", "tbd", "todo", "?", "..."}
# A name in backticks that is a file of this repository, written as the documents here write it: with its folder, or bare when it is
# a module of the app, a test, a script or a workflow.
FILE = re.compile(r"`([\w./-]+\.(?:py|md|yml|sh|mjs|sql))`")
FOLDERS = ("", "backend", "backend/app", "backend/tests", "scripts", ".github/workflows", ".github", "deploy")


def rows(text: str) -> dict:
    """{topic number: (name, status, evidence, control)} of the topic table."""
    found = {}
    for line in text.splitlines():
        match = ROW.match(line)
        if match and match.group(3).strip("` ").lower() in (*STATUSES, "unset"):
            found[int(match.group(1))] = (match.group(2), match.group(3).strip("` ").lower(), match.group(4), match.group(5))
    return found


def problems(text: str, root: Path = ROOT) -> list:
    """What is wrong with a declaration, as sentences; empty when nothing is."""
    found, wrong = rows(text), []
    for number in range(1, TOPICS + 1):
        if number not in found:
            wrong.append(f"topic {number} is not answered")
            continue
        name, status, evidence, _control = found[number]
        if status not in STATUSES:
            wrong.append(f"topic {number} ({name}) is still '{status}'")
        elif evidence.strip().lower() in SAYS_NOTHING:
            wrong.append(f"topic {number} ({name}) is '{status}' without {'evidence' if status in ('applies', 'partial') else 'a reason'}")
        elif status == "partial" and "gap:" not in evidence.lower():
            wrong.append(f"topic {number} ({name}) is 'partial' but names no 'Gap:'")
    wrong += [f"topic {number} is not one of the {TOPICS}" for number in sorted(set(found) - set(range(1, TOPICS + 1)))]
    for name in sorted(set(FILE.findall(text))):
        if not any((root / folder / name).is_file() for folder in FOLDERS):
            wrong.append(f"`{name}` is named but is not a file of this repository")
    return wrong


class Conformance(unittest.TestCase):
    def test_every_topic_is_answered_and_every_named_file_exists(self):
        self.assertEqual(problems(DECLARATION.read_text(encoding="utf-8")), [])

    def test_the_check_sees_what_it_is_for(self):
        """Each kind of mistake, made in a copy of the real declaration, is reported; without this the test above could pass on anything."""
        text = DECLARATION.read_text(encoding="utf-8")
        lines = text.splitlines()
        at = {int(m.group(1)): i for i, line in enumerate(lines) if (m := ROW.match(line)) and m.group(3) in STATUSES}
        self.assertEqual(sorted(at), list(range(1, TOPICS + 1)))

        def changed(number, change):
            copy = list(lines)
            copy[at[number]] = change(copy[at[number]])
            return problems("\n".join(copy))

        partial = next(n for n in at if rows(text)[n][1] == "partial")
        applies = next(n for n in at if rows(text)[n][1] == "applies")
        self.assertIn("topic 7 is not answered", changed(7, lambda line: ""))
        self.assertTrue(any("is still 'unset'" in p for p in changed(applies, lambda line: line.replace("| applies |", "| unset |", 1))))
        self.assertTrue(any("without evidence" in p for p in changed(applies, lambda line: re.sub(r"(\| applies \|)[^|]*\|", r"\1  |", line, count=1))))
        self.assertTrue(any("names no 'Gap:'" in p for p in changed(partial, lambda line: line.replace("Gap:", "Missing:"))))
        self.assertTrue(any("`test_that_was_renamed.py` is named" in p
                            for p in changed(applies, lambda line: line[:-1] + " `test_that_was_renamed.py` |")))


if __name__ == "__main__":
    unittest.main()
