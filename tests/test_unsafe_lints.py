#!/usr/bin/env python3
"""Control matrix for scripts/check_unsafe_lints.py.

Both failure modes are asserted, because both were found in the live fleet and
neither is visible from the workspace root:

  * a member with NO `[lints]` table — workspace lints are opt-in, so it never
    inherits them (5 published crates across 2 repos were in this state)
  * a member whose OWN `[lints]` table replaces inheritance without restating
    `unsafe_code`

    python3 tests/test_unsafe_lints.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "check_unsafe_lints.py"
FX = ROOT / "tests" / "fixtures" / "unsafe_lints"

CASES = [
    ("member inheriting via [lints] workspace = true passes", "good", "", 0),
    ("member with NO [lints] table fails", "bad_no_lints_table", "", 1),
    ("member whose own [lints] table drops unsafe_code fails", "bad_own_lints_table", "", 1),
    ("a named exemption is honoured", "bad_no_lints_table", "unprotected-member", 0),
    ("an unrelated exemption does not rescue it", "bad_no_lints_table", "some-other-crate", 1),
]


def main() -> int:
    failures = 0
    for name, fixture, exempt, want in CASES:
        proc = subprocess.run(
            [sys.executable, str(CHECK), str(FX / fixture), exempt],
            capture_output=True, text=True,
        )
        ok = proc.returncode == want
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  exit={proc.returncode} want={want}  {name}")
        if not ok:
            for line in proc.stdout.splitlines()[:12]:
                print(f"    {line}")

    # Assert on emitted output, not just status: the message must name the member
    # and say WHY, or the failure is unactionable.
    proc = subprocess.run(
        [sys.executable, str(CHECK), str(FX / "bad_no_lints_table"), ""],
        capture_output=True, text=True,
    )
    for label, needle in (
        ("names the offending member", "unprotected-member"),
        ("explains that inheritance is opt-in", "inheritance is opt-in"),
        ("emits a file-annotated error", "::error file="),
    ):
        cond = needle in proc.stdout
        failures += not cond
        print(f"{'ok  ' if cond else 'FAIL'}  {label}")

    total = len(CASES) + 3
    print(f"\n{total - failures}/{total} passed")
    if failures:
        print("::error::unsafe lint audit control matrix failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
