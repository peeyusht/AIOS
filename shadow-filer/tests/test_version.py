"""The consoles' version (ui/package.json) and the changelog (ui/src/changelog.ts) agree: the newest entry is the
version, versions are a.b.c and go down, each entry has a date and something in it. Every code change raises the
version (scripts/check_version_bump.py, run before a merge)."""
import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_version_bump  # noqa: E402


class VersionTest(unittest.TestCase):
    def test_changelog_matches_package(self):
        version = json.loads((UI / "package.json").read_text(encoding="utf-8"))["version"]
        text = (UI / "src" / "changelog.ts").read_text(encoding="utf-8")
        entries = re.findall(r'version: "([^"]+)", date: "([^"]+)", title: "([^"]+)"', text)
        self.assertTrue(entries)
        self.assertEqual(entries[0][0], version, "the newest changelog entry must be package.json's version")
        nums = [tuple(map(int, v.split("."))) for v, _, _ in entries]
        self.assertTrue(all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v, _, _ in entries))
        self.assertEqual(nums, sorted(nums, reverse=True))
        self.assertEqual(len(nums), len(set(nums)))
        for _, d, t in entries:
            date.fromisoformat(d)
            self.assertTrue(t.strip())

    def test_bump_rules(self):
        cmp = check_version_bump.compare
        self.assertEqual([cmp("1.10.0", "1.9.1") > 0, cmp("1.5.0", "1.5.0") == 0, cmp("1.4.9", "1.5.0") < 0], [True, True, True])
        docs = check_version_bump.docs_only
        self.assertTrue(docs(["docs/spec.md", "CLAUDE.md"]))
        self.assertFalse(docs(["docs/spec.md", "server/app/main.py"]))
        self.assertFalse(docs([]))


if __name__ == "__main__":
    unittest.main()
