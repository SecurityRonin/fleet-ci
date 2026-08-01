# fleet-ci — the SecurityRonin reusable Rust CI workflow

One `workflow_call` workflow, called by every fleet repo, replacing 91 copies of
`ci.yml` that had drifted into **89 distinct normalized variants across 49
feature profiles**.

Adopting it is a ~10-line file per repo:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  ci:
    uses: SecurityRonin/fleet-config/.github/workflows/rust-ci.yml@<SHA>
```

That stub gets: fmt · clippy · test (3 OS) · MSRV · cargo-deny · cargo-vet ·
secret scan · fuzz build-check · per-line coverage gate.

## What the single workflow closes

| Gap | Before | After |
|---|---|---|
| Secret scan | 48 of 91 repos had none | every repo, always on |
| SHA-pinned actions | 10 of 91 fully pinned; 81 carried a floating tag | every action pinned, tag verified via the GitHub API |
| `permissions:` block | **0 of 91** declared one | `contents: read`, workflow-wide |
| Coverage gate | 6 implementations, 3 incompatible semantics | one implementation |

### The pins are sound; one provenance label is fiction

`9bdad043e88c75890e36ad3bbc8d27f0090dd609` appears in **56 fleet repos, across 87
workflow files, 292 times** — 276 of those commented `# v2.7.8`, 16 commented
`# v2`. It is a real `Swatinem/rust-cache` commit dated 2024-05-03 (`fix: usage of
deprecated version of node`, PR #197), but it **matches no release tag**:

| Tag | Commit |
|---|---|
| v2.7.3 | `23bce251a8cd2ffc3c1075eaa2367cf899916d84` |
| v2.7.5 | `82a92a6e8fbeee089604da2575dc567ae9ddeaab` |
| v2.7.7 | `f0deed1e0edfc6a9be95417288c0e1099b1eeec3` |
| v2.7.8 | `9d47c6ad4b02e050fd481d890b2ea34778fd09d6` |
| v2.8.0 | `98c8021b550208e191a6a3145459bfc9fb29c4c0` |

**This is a traceability defect, not a vulnerability.** A SHA is immutable, so the
security control is doing exactly its job — the pinned bytes cannot change under
anyone. What fails is provenance: 56 repos run untagged mid-tree code while the
comment beside it asserts a release. An audit answering *"are we on released
versions?"* by reading those comments gets a wrong answer, and Renovate's
digest-pinning may not map SHA→version cleanly either.

Two repos — `orchestration/issen` and `parser/browser-forensic` — pin **both**
SHAs in different workflows, so they are internally inconsistent about which
`rust-cache` they run.

Every SHA in `rust-ci.yml` was resolved with
`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha` at authoring time, so the
comment and the bytes agree. `rust-cache` here is
`c19371144df3bb44fab255c43d04cbc2ab54d1c4`, which is genuinely v2.9.1.

## The coverage gate

The fleet's gate existed in three incompatible semantics. They disagree about
what "100% coverage" even asserts:

1. **Per-line, `// cov:unreachable`-aware** (36 repos) — walks every `DA:<n>,0`
   record, reads the source line, exempts annotated ones. Names the file and
   line that failed.
2. **Aggregate floor**, `--fail-under-lines N` (10 repos, N ∈ {85, 89, 90, 92,
   95, 96, 97}) — a percentage. **Structurally cannot honour a per-line
   exemption**, and never says *which* lines are uncovered.
3. **Naive `grep -qE '^DA:[0-9]+,0$'`** — strict 100% with no exemption at all,
   so a provably-dead defensive guard can only be satisfied by deleting it.

**This workflow implements (1), and it is the default.** The reasons:

- It is what the fleet constitution already requires: *"100% line coverage …
  with `// cov:unreachable` on provably-dead defensive arms — never delete a
  defensive guard to satisfy the gate."* Semantics (2) and (3) both make that
  impossible — (3) by having no exemption, (2) by having no per-line hook.
- **It is the only one that preserves defence in depth.** Under an aggregate
  floor, a guard that cannot be reached is indistinguishable from a guard nobody
  tested; under the naive grep, the only way to go green is to delete the guard.
  Both pressure the author toward removing exactly the code that makes a parser
  safe on hostile input.
- **A floor hides *which* lines rot.** At 85%, 15% of the crate can decay with no
  signal. Every floor in the fleet carried a "ratchet it up later" comment; none
  had been ratcheted.

Two exemptions, both narrow, both printed with file:line so the gate stays
auditable:

- **`cov:unreachable: <invariant>`** — matched as a bare substring, not anchored
  to `//`, because the fleet writes the marker in line comments *and* trailing
  block comments. Anchoring to `//` silently drops the others back into the
  failure set (this was a real bug, caught by running the gate against real
  `cargo llvm-cov` output rather than only a hand-built fixture).
- **Delimiter-only lines** (`}`, `)`, `);`, `)?;`, `,`) — `llvm-cov` emits a
  zero-count record on some of these as a region-attribution artifact. A line
  carrying nothing but a delimiter has no behaviour of its own.

Anything else with a zero hit count fails. A zero-hit line whose source file
cannot be read also fails — an unverifiable line is not a covered one.

`require-exemption-reason` (default `true`) rejects a bare `// cov:unreachable`
with no stated invariant. The marker asserts a guard is provably dead; an
assertion with no reason cannot be reviewed. Fleet-wide this is nearly free:
**585 of 616 markers already carry a reason**; 31 bare ones remain, mostly in
`apfs-forensic`.

### Migration, stated honestly

A repo not yet at per-line coverage sets `coverage-gate: floor` +
`coverage-floor: N`. The job then renders in the checks UI as:

> `Coverage (FLOOR 85% — migration debt, not the fleet gate)`

and emits a `::warning::` explaining what the floor cannot do. The debt stays
visible instead of looking like a passing gate.

### Coverage scope is part of the semantics

`coverage-scope` defaults to `workspace` (all members, all test targets). Repos
using `--lib` measure unit tests only, which under-counts any crate whose
oracle/differential suites live in `tests/`.

Scope is not cosmetic. Running this gate over `ntfs-forensic` at the fleet
default (`--workspace --all-features`) surfaces **37 uncovered lines in
`core/src/vfs.rs`** that its current gate — `cargo llvm-cov --lib`, no features —
never measures at all. That job is named "Coverage" and enforces per-line 100%;
the number is true for what it measures and silent about a whole feature-gated
module.

## `cargo deny` runs from a shared config

`cargo-deny` has **no include/extends mechanism** — v0.19.0's `check` subcommand
offers only `-c/--config` (verified against `cargo deny check --help`). So the
shared config is fetched and passed by path: the `deny` job checks out
`deny-config-repo` into `.fleet-config/` and runs
`cargo deny --config .fleet-config/<deny-config-path> check all`.

**Assumption:** the shared `deny.toml` lands at
`SecurityRonin/fleet-config` on `main` at path `deny.toml`. Change the
`deny-config-*` inputs if it lands elsewhere. Setting `deny-config-repo: ""`
falls back to the repo's own local `deny.toml`, which is the pre-migration
behaviour.

Pin `deny-config-ref` to a SHA in production; `main` is a moving target and an
advisory config that changes under you is a CI result you cannot reproduce.

## Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `msrv` | string | `""` | Empty derives the floor from the workspace's own `rust-version` |
| `msrv-check` | string | `build` | `build` or `test` |
| `os-matrix` | boolean | `true` | ubuntu + macos + windows |
| `all-features` | boolean | `true` | Batteries-included; turn off only for mutually-exclusive features |
| `coverage-gate` | string | `strict` | `strict` \| `floor` \| `off` |
| `coverage-floor` | number | `100` | Only read when `coverage-gate: floor` |
| `coverage-scope` | string | `workspace` | `workspace` \| `lib` |
| `coverage-ignore-regex` | string | `""` | `--ignore-filename-regex` |
| `require-exemption-reason` | boolean | `true` | Reject bare `// cov:unreachable` |
| `deny-config-repo` | string | `SecurityRonin/fleet-config` | `""` = repo-local `deny.toml` |
| `deny-config-ref` | string | `main` | Pin to a SHA in production |
| `deny-config-path` | string | `deny.toml` | Path within the config repo |
| `vet` | boolean | `true` | `cargo vet --locked` |
| `secret-scan` | boolean | `true` | gitleaks; should never be false |
| `gitleaks-version` | string | `8.30.1` | Pinned; Renovate-annotated |
| `fuzz-build-check` | boolean | `true` | Auto-skips when there is no `fuzz/` |

### MSRV is derived, not restated

Leave `msrv` empty and the job reads the lowest `rust-version` across workspace
members from `cargo metadata`. Restating the MSRV in CI is precisely how a repo
ends up *verifying* 1.85 while *promising* 1.81 to downstreams — and the survey
found exactly that spread: `rust-version` values across the fleet span
{1.70, 1.75, 1.80, 1.81, 1.83, 1.85, 1.87, 1.88, 1.93, 1.96}, while the MSRV
jobs pin their own separate set. Deriving it makes disagreement structurally
impossible.

The sort is numeric per component, so `1.9` correctly ranks below `1.85`
(a string sort would invert them). Verified against `browser-forensic`, whose
members declare both 1.80 and 1.85 — it derives 1.80, the floor the whole
workspace can actually build at.

If no member declares `rust-version`, the job **fails loudly** rather than
guessing a floor it would then claim to have verified.

### Fuzz is detected, not configured

The `fuzz-build` job discovers fuzz crates at runtime and skips when there are
none — so nothing needs per-repo wiring, and a repo that gains fuzz targets is
covered the moment they land. It is a **build check**, not a campaign; the long
run stays in each repo's `fuzz.yml` (68 repos already have one).

Detection looks for *any* directory named `fuzz` containing a `Cargo.toml`, not
just one at the repo root, and runs `cargo fuzz build` from each owning parent.
That distinction is load-bearing: 79 fleet repos have a fuzz crate, but only 70
keep it at `fuzz/` — the other 9 use `core/fuzz`, `forensic/fuzz`, or
`crates/<member>/fuzz`. A root-only check would have skipped those **silently**,
and a fuzz job that passes because it found nothing is worse than no fuzz job at
all: it reads as coverage that does not exist. The discovery logic was run
against all 92 repos and matches ground truth exactly.

## Secrets

The callee declares **no** `secrets:`, so the caller stub deliberately omits
`secrets: inherit` — nothing here needs a credential. gitleaks downloads from
public GitHub releases, and `cargo deny`/`vet` need none. The default
`GITHUB_TOKEN` can read public repos, which covers the cross-repo checkout of
the config repo.

`secrets: inherit` does work and does pass org-level secrets (they are available
to the caller, and `inherit` forwards the caller's full set to a *directly*
called workflow — it does not chain further). Add it only when a job here
genuinely needs one, e.g. a Codecov upload token.

## Verified mechanics

- **Cross-repo `workflow_call` and visibility.** A **public** caller can only
  reference reusable workflows in **public** repos; a private caller can use
  both ([GitHub docs, "Access to reusable workflows"](https://docs.github.com/en/actions/reference/workflows-and-actions/reusable-workflows#access-to-reusable-workflows)).
  The SecurityRonin org is 115 public / 14 private, and **all 91 fleet repos are
  public** — so the repo hosting this workflow **must be created public** or
  nothing can call it.
- **Reference syntax.** `{owner}/{repo}/.github/workflows/{filename}@{ref}`,
  where `{ref}` may be a SHA, tag, or branch. The docs name the commit SHA the
  safest option; pilots pin by full SHA.
- **Caller `env:` is not inherited** by a called workflow, so every variable the
  jobs rely on is declared inside `rust-ci.yml`.
- **Permissions cannot be escalated.** A called workflow never holds more than
  its caller grants; the `permissions: contents: read` block here is a floor,
  and the caller stub declares the same.
- **Nesting.** Not used — this is a single level, well inside the 4-deep limit.

## Why `rust-ci.yml` and not `ci.yml`

If this lands in a repo named `.github`, a file at `.github/workflows/ci.yml`
would also be *that repo's own* CI workflow. `rust-ci.yml` avoids the collision
and leaves room for `release.yml` / `docs.yml` callees later.

## Not yet done

- The workflow has **never executed**. It is validated statically (YAML parses,
  the gate's Python compiles) and its coverage gate is validated dynamically
  against real `cargo llvm-cov` output — but no CI run has exercised the
  workflow end to end, because the callee repo does not exist yet.
- The `actions/checkout` pin is **v7.0.1**, three majors ahead of the v4.2.2 the
  fleet runs today. Centralising makes it one bump instead of 91, but the jump
  is untested here.
