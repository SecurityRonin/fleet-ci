#!/usr/bin/env python3
"""Control matrix for the strict coverage gate in rust-ci.yml.

The gate is EXTRACTED FROM THE WORKFLOW rather than kept as a second copy here.
A test that exercises its own copy of the logic cannot detect a defect in the
copy that actually ships, and a second copy is a correction that will not
propagate. This reads the heredoc the workflow really runs.

Every case asserts an exit status, and most of them assert a FAILURE: a gate
that has only ever been seen to pass is not known to work.

    python3 tests/test_coverage_gate.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "rust-ci.yml"
FIXTURES = ROOT / "tests" / "fixtures"
MARKER = "python3 - lcov.info <<'PYGATE'"


def extract_gate() -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").split("\n")
    start = end = None
    for i, line in enumerate(lines):
        if MARKER in line:
            start = i + 1
        elif start is not None and line.strip() == "PYGATE":
            end = i
            break
    if start is None or end is None:
        raise SystemExit(
            f"::error::could not find the PYGATE heredoc in {WORKFLOW}. "
            "The gate moved or was renamed; this test is now measuring nothing."
        )
    body = lines[start:end]
    indent = min(len(l) - len(l.lstrip()) for l in body if l.strip())
    return "\n".join(l[indent:] if len(l) >= indent else l for l in body)


# (name, fixture, env, expected_exit)
CASES = [
    # Back-compatibility: the 47 repos on the default must not change behaviour.
    ("default env is line-gating",        "monomorph.info",      {},                                                    0),
    ("default env still fails a real uncovered line",
                                          "uncovered-line.info", {},                                                    1),
    ("metric=lines passes monomorph",     "monomorph.info",      {"COV_METRIC": "lines"},                               0),
    # The reason coverage-metric exists: every line covered, one instantiation never entered.
    ("metric=functions catches the uncalled instantiation",
                                          "monomorph.info",      {"COV_METRIC": "functions"},                           1),
    ("metric=both catches it too",        "monomorph.info",      {"COV_METRIC": "both"},                                1),
    ("metric=lines fails an uncovered line",
                                          "uncovered-line.info", {"COV_METRIC": "lines"},                               1),
    # Gate scoping.
    ("include-regex gates only the matched file",
                                          "two-files.info",      {"COV_METRIC": "functions", "COV_INCLUDE": r"clean\.rs"},  0),
    ("include-regex fails when the dirty file is in scope",
                                          "two-files.info",      {"COV_METRIC": "functions", "COV_INCLUDE": r"dirty\.rs"},  1),
    # A scope matching nothing must be an error, never a silent pass.
    ("include-regex matching no file is an error",
                                          "two-files.info",      {"COV_METRIC": "functions", "COV_INCLUDE": "no_such_file"}, 1),
    # Malformed configuration fails loudly rather than degrading to a pass.
    ("invalid include-regex fails loudly", "two-files.info",     {"COV_INCLUDE": "("},                                  1),
    ("invalid metric fails loudly",        "two-files.info",     {"COV_METRIC": "branches"},                            1),
]


def main() -> int:
    gate = extract_gate()
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(gate)
        gate_path = fh.name

    failures = 0
    for name, fixture, env, want in CASES:
        full_env = {"PATH": "/usr/bin:/bin", "REQUIRE_REASON": "true", **env}
        proc = subprocess.run(
            [sys.executable, gate_path, str(FIXTURES / fixture)],
            capture_output=True, text=True, env=full_env, cwd=ROOT,
        )
        ok = proc.returncode == want
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  exit={proc.returncode} want={want}  {name}")
        if not ok:
            print("    ---- stdout ----")
            for line in proc.stdout.splitlines():
                print(f"    {line}")

    # The function-level exemption is the one behaviour a pass/fail status cannot
    # distinguish, so assert on the emitted output rather than the exit code.
    proc = subprocess.run(
        [sys.executable, gate_path, str(FIXTURES / "two-files.info")],
        capture_output=True, text=True, cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "REQUIRE_REASON": "true",
             "COV_METRIC": "functions", "COV_INCLUDE": r"dirty\.rs"},
    )
    named = "never_entered" in proc.stdout
    exempted = "dead_guard" in proc.stdout and "(function) dead_guard" in proc.stdout
    for label, cond in (("names the uncalled function", named),
                        ("exempts the annotated function", exempted)):
        failures += not cond
        print(f"{'ok  ' if cond else 'FAIL'}  {label}")

    total = len(CASES) + 2
    print(f"\n{total - failures}/{total} passed")
    if failures:
        print("::error::coverage gate control matrix failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
