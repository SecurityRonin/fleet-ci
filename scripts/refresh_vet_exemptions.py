#!/usr/bin/env python3
"""Refresh vet exemptions for version churn, but never for a NEW crate.

Renovate bumps a dependency, the resolved version changes, and every
`[[exemptions.foo]] version = "1.2.3"` that named the old version stops
matching. `cargo vet` goes red and blocks the automerge Renovate was configured
to perform. Across this fleet that is 7,059 version-pinned exemptions meeting a
bot that bumps continuously, so the two tools fight by construction.

Regenerating exemptions fixes that, and a blanket regeneration would also
quietly swallow the one case where the red is doing real work.

  version churn   `serde 1.0.200 -> 1.0.201`. Same crate, same trust posture,
                  same (absent) assurance. An exemption asserts only "nobody
                  audited this" -- that statement is equally true before and
                  after, so refreshing it invents nothing.

  a NEW crate     something that was not in the graph at all is now being
                  shipped. That is exactly the moment a human should look, and
                  the moment a blanket regeneration would hide.

So this refreshes the first and refuses the second. The distinction is by crate
NAME, not by version: names present before must be a superset of names after.

Exit 0 refreshed (or nothing to do), 1 a new crate appeared and needs a human,
2 the check could not do its work.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

CONFIG = Path("supply-chain/config.toml")
EXEMPTION = re.compile(r"^\[\[exemptions\.([^\]]+)\]\]", re.M)


def names(text: str) -> set[str]:
    return {m.group(1).strip('"') for m in EXEMPTION.finditer(text)}


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True)


def main() -> int:
    if not CONFIG.is_file():
        print(f"error: {CONFIG} not found -- run from the repository root.", file=sys.stderr)
        return 2

    before_text = CONFIG.read_text()
    before = names(before_text)

    if run("cargo", "vet", "--locked").returncode == 0:
        print("ok: cargo vet already passes; nothing to refresh.")
        return 0

    regen = run("cargo", "vet", "regenerate", "exemptions")
    if regen.returncode != 0:
        print("error: `cargo vet regenerate exemptions` failed:", file=sys.stderr)
        print(regen.stderr.strip(), file=sys.stderr)
        return 2

    after = names(CONFIG.read_text())
    added = sorted(after - before)

    if added:
        # Refuse rather than ship it. Restoring the original file means the PR
        # stays red, which is the correct outcome: a crate nobody has looked at
        # just entered the dependency graph.
        CONFIG.write_text(before_text)
        print(
            f"error: {len(added)} crate(s) entered the graph that were not exempted before:",
            file=sys.stderr,
        )
        for name in added:
            print(f"  {name}", file=sys.stderr)
        print(
            "\nRefreshing a version pin is bookkeeping; accepting a NEW dependency is a\n"
            "supply-chain decision. This job will refresh the first and never the second.\n"
            "Review the crate, then record it deliberately -- `cargo vet trust <crate>\n"
            "<publisher>` if its publisher is one we rely on, or an exemption with a\n"
            "truthful note if not.",
            file=sys.stderr,
        )
        return 1

    verify = run("cargo", "vet", "--locked")
    if verify.returncode != 0:
        CONFIG.write_text(before_text)
        print(
            "error: exemptions were refreshed but `cargo vet --locked` still fails, so the\n"
            "failure was never about stale version pins. Restored the original file rather\n"
            "than leaving a rewritten one that fixes nothing.",
            file=sys.stderr,
        )
        print(verify.stdout.strip()[-2000:], file=sys.stderr)
        return 2

    removed = sorted(before - after)
    print(f"ok: refreshed version pins for {len(before & after)} exemption(s).")
    if removed:
        print(f"    {len(removed)} no longer needed: {', '.join(removed)}")
    print("    no new crate entered the graph.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
