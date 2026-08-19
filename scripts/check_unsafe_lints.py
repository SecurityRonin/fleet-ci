#!/usr/bin/env python3
"""Assert every workspace member EFFECTIVELY forbids or denies `unsafe_code`.

Surveying the workspace root is not enough, and that is the whole point of this
check. A member carrying its own `[lints]` table REPLACES inheritance rather
than extending it, so a crate can silently lose `unsafe_code = "forbid"` while
the root manifest still reads compliant. Measuring at the aggregation point
scores such a repo green while a member compiles with nothing enforced.

What this does NOT do is re-check what the compiler already guarantees. Where
the lint is in force, `unsafe` is a compile error and a CI job asserting its
absence would be a check that cannot fail — which is worse than no check,
because it reads as coverage that does not exist. This asserts the lint is
actually IN FORCE, per member, which is the part nothing else verifies.

Usage:  check_unsafe_lints.py <workspace-root> [exempt,members,...]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

FORBID = re.compile(r'^\s*unsafe_code\s*=\s*(?:"(forbid|deny)"|\{[^}]*level\s*=\s*"(forbid|deny)")',
                    re.M)
LINTS_TABLE = re.compile(r'^\s*\[lints(?:\.\w+)?\]\s*$', re.M)
LINTS_WORKSPACE = re.compile(r'^\s*\[lints\]\s*$.*?^\s*workspace\s*=\s*true', re.M | re.S)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"::error::cannot read {path}: {exc}")
        sys.exit(1)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    exempt = {m.strip() for m in re.split(r"[,\n]", sys.argv[2] if len(sys.argv) > 2 else "")
              if m.strip()}

    meta = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=root, capture_output=True, text=True,
    )
    if meta.returncode != 0:
        print(f"::error::cargo metadata failed — cannot enumerate workspace members.\n{meta.stderr.strip()[:600]}")
        return 1
    packages = json.loads(meta.stdout)["packages"]
    if not packages:
        # Refuse to pass over an empty member list: that is not-run, never passed.
        print("::error::cargo metadata reported no workspace members — this check ran over nothing.")
        return 1

    ws_manifest = read(root / "Cargo.toml")
    ws_forbids = bool(FORBID.search(ws_manifest))

    bad, ok, skipped = [], [], []
    for pkg in packages:
        name = pkg["name"]
        manifest = Path(pkg["manifest_path"])
        if name in exempt:
            skipped.append(name)
            continue
        text = read(manifest)

        if FORBID.search(text):
            ok.append((name, "own [lints]"))
        elif LINTS_WORKSPACE.search(text):
            if ws_forbids:
                ok.append((name, "inherited via [lints] workspace = true"))
            else:
                bad.append((name, manifest, "inherits from a workspace that does not set unsafe_code"))
        elif LINTS_TABLE.search(text):
            bad.append((name, manifest,
                        "declares its own [lints] table, which REPLACES workspace inheritance, "
                        "and that table does not set unsafe_code"))
        elif ws_forbids:
            bad.append((name, manifest,
                        "has no [lints] table at all, so the workspace lints do NOT apply to it "
                        "(inheritance is opt-in via `[lints] workspace = true`)"))
        else:
            bad.append((name, manifest, "no unsafe_code rule anywhere in its lint configuration"))

    for name, manifest, why in bad:
        rel = manifest.relative_to(root) if manifest.is_relative_to(root) else manifest
        print(f"::error file={rel}::`{name}` does not effectively forbid or deny `unsafe_code`: {why}.")

    print(f"\nmembers enforcing unsafe_code: {len(ok)}   "
          f"not enforcing: {len(bad)}   exempt: {len(skipped)}")
    for name, how in sorted(ok):
        print(f"  ok      {name}  ({how})")
    for name in sorted(skipped):
        print(f"  exempt  {name}  (declared via unsafe-audit-exempt)")

    if bad:
        print("\nA member that does not enforce the lint compiles with `unsafe` permitted while "
              "the workspace root still reads compliant. Either set `unsafe_code` in that member's "
              "own [lints] table, add `[lints] workspace = true`, or declare it in "
              "`unsafe-audit-exempt` with a reason in the caller workflow.")
        return 1
    print("\nEvery workspace member effectively forbids or denies unsafe_code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
