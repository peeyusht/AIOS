"""Before merging a branch: every code change raises the consoles' version (shadow-filer/ui/package.json) above
main's, and adds its entry to shadow-filer/ui/src/changelog.ts (the tests check the two agree). Changes to docs
only (docs/ and *.md) need no bump. The same rule as Anvay's (nacdesk scripts/check-version-bump.mjs).

    python scripts/check_version_bump.py [base]        # base defaults to origin/main; exit 1 when not bumped
"""
import json
import re
import subprocess
import sys

PACKAGE = "shadow-filer/ui/package.json"


def compare(a: str, b: str) -> int:
    pa, pb = [int(x) for x in a.split(".")], [int(x) for x in b.split(".")]
    return (pa > pb) - (pa < pb)


def docs_only(files: list) -> bool:
    return bool(files) and all(f.startswith("docs/") or f.endswith(".md") for f in files)


def main(base: str = "origin/main") -> int:
    git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout
    files = [f for f in git("diff", "--name-only", f"{base}...HEAD").splitlines() if f]
    files += [f for f in git("diff", "--name-only", "HEAD").splitlines() if f and f not in files]      # not committed yet
    if docs_only(files):
        print("Docs-only change: no version bump needed.")
        return 0
    mine = json.loads(open(PACKAGE, encoding="utf-8").read()).get("version", "")
    try:
        theirs = json.loads(git("show", f"{base}:{PACKAGE}")).get("version") or "0.0.0"
    except subprocess.CalledProcessError:
        theirs = "0.0.0"
    if not re.fullmatch(r"\d+\.\d+\.\d+", mine or ""):
        print(f'{PACKAGE} "version" is "{mine}", not a.b.c.')
        return 1
    if compare(mine, theirs) <= 0:
        print(f'Raise {PACKAGE} "version" and add a changelog entry: this branch has {mine}, {base} has {theirs}.')
        return 1
    print(f"Version {theirs} -> {mine}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
