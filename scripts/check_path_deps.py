#!/usr/bin/env python3
"""Fail if any `path` dependency resolves outside the repository.

Every fleet repo is cloned on its own in CI, so a path dependency pointing at a
sibling repo names a directory the runner does not have. Cargo then fails at
manifest loading, before any check does work -- and because *every* cargo-based
job dies at the same point, the repo goes red across fmt, clippy, test, MSRV,
deny, vet, docs and coverage at once, with an error that mentions none of them.

Observed 2026-07/08 in three fleet repos on one dependency chain: issen ->
usb-forensic, usb-forensic -> peripheral-core, peripheral-forensic ->
forensicnomicon-core. Roughly 28 red checks, one cause.

In CI this job does not detect anything cargo would otherwise miss -- cargo
fails there regardless. What it adds is a named diagnosis in place of a
six-way failure whose message points at a workspace member rather than the
dependency that escaped. Run locally it is a genuine detector: a full-fleet
checkout resolves the path happily, so this is the only way to observe the
single-checkout property from a developer machine.

Exits 0 when clean, 1 when a path dependency escapes, 2 when the check itself
could not do its work (no manifests found, or no path dependencies extracted) --
a check that inspected nothing must never report success.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePath

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    print(
        "error: tomllib is unavailable (needs Python 3.11+). Refusing to fall "
        "back to a regex, which cannot see the `[dependencies.foo]` section "
        "form and would report a clean result it did not earn.",
        file=sys.stderr,
    )
    sys.exit(2)

# `.fleet-ci` / `.fleet-config` are the checkout paths this workflow uses for
# shared config, so they are someone else's repo sitting inside the workspace.
SKIP_DIRS = {"target", ".git", ".claude", "node_modules", ".fleet-ci", ".fleet-config"}


def path_dependencies(value: object, under_deps: bool = False) -> list[tuple[str, str]]:
    """Every (name, declared path) pair under any `*dependencies` table.

    Covers `[dependencies]`, `[dev-dependencies]`, `[build-dependencies]`,
    `[workspace.dependencies]`, the per-target `[target.<cfg>.dependencies]`
    forms, and both spellings of a single dependency -- inline
    `foo = { path = "..." }` and the section form `[dependencies.foo]` with
    `path` on its own line. A line-anchored regex cannot see the second, which
    is why this walks the parsed document instead.
    """
    if not isinstance(value, dict):
        return []
    out: list[tuple[str, str]] = []
    for key, child in value.items():
        is_deps = key.endswith("dependencies")
        if under_deps and not is_deps and isinstance(child, dict):
            declared = child.get("path")
            if isinstance(declared, str):
                out.append((key, declared))
        out.extend(path_dependencies(child, under_deps or is_deps))
    return out


def normalize(path: PurePath) -> PurePath:
    """Resolve `.` and `..` lexically, without touching the filesystem.

    Deliberately not `Path.resolve()`: that follows symlinks, and a path that
    escapes the repo is exactly the case where the target may not exist.
    """
    parts: list[str] = []
    for part in PurePath(path).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    return PurePath(*parts)


def count(n: int, noun: str) -> str:
    if n == 1:
        return f"{n} {noun}"
    plural = f"{noun[:-1]}ies" if noun.endswith("y") else f"{noun}s"
    return f"{n} {plural}"


def manifests(root: Path) -> list[Path]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "Cargo.toml" in filenames:
            found.append(Path(dirpath) / "Cargo.toml")
    return sorted(found)


def main() -> int:
    root = normalize(PurePath(Path(sys.argv[1] if len(sys.argv) > 1 else ".").absolute()))
    found = manifests(Path(root))

    if not found:
        print(f"error: no Cargo.toml found under {root}", file=sys.stderr)
        print("The check inspected nothing, so a pass would prove nothing.", file=sys.stderr)
        return 2

    escaping: list[str] = []
    checked = 0
    for manifest in found:
        try:
            with manifest.open("rb") as handle:
                document = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"error: cannot read {manifest}: {exc}", file=sys.stderr)
            return 2
        for name, declared in path_dependencies(document):
            checked += 1
            resolved = normalize(manifest.parent / declared)
            if not str(resolved).startswith(f"{root}{os.sep}") and resolved != root:
                rel = manifest.relative_to(Path(root))
                escaping.append(
                    f"  {rel}\n"
                    f'     {name} = {{ path = "{declared}" }}\n'
                    f"     resolves to {resolved}"
                )

    if checked == 0:
        print(
            f"error: {count(len(found), 'manifest')} found but zero path dependencies "
            "extracted -- the extractor is not reading dependency tables, so "
            "this check is inert.",
            file=sys.stderr,
        )
        return 2

    if escaping:
        print(
            f"error: {len(escaping)} of {count(checked, 'path dependency')} resolve "
            f"outside {root}.",
            file=sys.stderr,
        )
        print(
            "A lone clone of this repo cannot satisfy them, so `cargo metadata` "
            "fails before any check runs.\n",
            file=sys.stderr,
        )
        print("\n\n".join(escaping), file=sys.stderr)
        print(
            "\nPublish the crate and depend on the registry version instead "
            "(ADR-0006 bottom-up release order).",
            file=sys.stderr,
        )
        return 1

    print(f"ok: {count(checked, 'path dependency')} across "
          f"{count(len(found), 'manifest')} all stay inside {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
