#!/usr/bin/env python3
"""Control matrix for the MSRV feature-flag selection in rust-ci.yml.

The logic is EXTRACTED FROM THE WORKFLOW, not copied here. A test that
exercises its own copy cannot detect a defect in the copy that ships.

What it guards: `msrv-args` carrying its own feature selection must REPLACE the
automatic `--all-features`, never join it. cargo rejects
`--all-features --no-default-features`, and that rejection reads as a broken
MSRV floor rather than a broken invocation -- which is exactly the confusion a
lib+CLI hybrid would hit while verifying a promise it actually keeps.

    python3 tests/test_msrv_args.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "rust-ci.yml"

HEAD = "          scope=(--workspace)"
TAIL = '          echo "verifying ${MEMBER:-<workspace>} at its declared floor $MSRV"'


def extract() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    if HEAD not in text or TAIL not in text:
        raise SystemExit(
            "::error::could not locate the MSRV flag-selection block in "
            f"{WORKFLOW}. It moved or was rewritten; this test is now "
            "measuring nothing."
        )
    body = text[text.index(HEAD): text.index(TAIL)]
    body = "\n".join(l[10:] if l.startswith(" " * 10) else l for l in body.split("\n"))
    return (
        'set -euo pipefail\nMEMBER="$1"; ALLF="$2"; MSRV_ARGS="${3:-}"\n'
        + body
        + '\necho "ARGS: ${scope[@]} ${feats[@]} ${extra[@]}"\n'
    )


# (name, member, all-features, msrv-args, must_contain, must_not_contain)
CASES = [
    ("workspace default",            "",           "true",  "",                       ["--workspace", "--all-features"], []),
    ("member default",               "shrinkpath", "true",  "",                       ["-p shrinkpath", "--all-features"], []),
    ("--no-default-features drops --all-features",
                                     "shrinkpath", "true",  "--no-default-features",  ["--no-default-features"], ["--all-features"]),
    ("--features also drops it",     "shrinkpath", "true",  "--features fs",          ["--features fs"], ["--all-features"]),
    ("an unrelated arg keeps it",    "shrinkpath", "true",  "--locked",               ["--all-features", "--locked"], []),
    ("all-features off stays off",   "shrinkpath", "false", "",                       ["-p shrinkpath"], ["--all-features"]),
]


def main() -> int:
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(extract())
        script = fh.name

    failures = 0
    for name, member, allf, args, want, unwanted in CASES:
        proc = subprocess.run(["bash", script, member, allf, args],
                              capture_output=True, text=True)
        line = next((l for l in proc.stdout.splitlines() if l.startswith("ARGS:")), "")
        ok = proc.returncode == 0
        ok &= all(w in line for w in want)
        ok &= not any(u in line for u in unwanted)
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"      got: {line!r}  (rc={proc.returncode})")
            if proc.stderr.strip():
                print(f"      err: {proc.stderr.strip()[:200]}")

    total = len(CASES)
    print(f"\n{total - failures}/{total} passed")
    if failures:
        print("::error::MSRV flag-selection control matrix failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
