# forge-audit

[![CI](https://github.com/MatrymLabs/forge-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/MatrymLabs/forge-audit/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/MatrymLabs/forge-audit/branch/main/graph/badge.svg)](https://codecov.io/gh/MatrymLabs/forge-audit)
![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**The proof-tool.** A portfolio makes a claim - *this engineer uses AI as a force
multiplier, wrapped in automated evidence, quality gates, and delivery mechanics.*
`forge-audit` **proves** that claim instead of asserting it: point it at a repository and
it runs the quality gates, reads the collaboration signals, and forges a machine-checkable
**JSON scorecard** graded against objective stage thresholds.

> *No claim without correspondence.* Every verdict quotes its evidence. A gate whose tool
> is absent reads `not_configured` - it is never faked as passing.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: make env
```

## Run

```bash
forge-audit --path .                            # human-readable summary (default)
forge-audit --path ../codeforge --format json   # machine-readable scorecard
forge-audit --path ../codeforge --format md      # a Markdown table for a README Evaluation section
forge-audit --path ../codeforge --online         # add live issue/PR signals via the `gh` CLI
```

`--format {human,json,md}` picks the output shape (`--json` is a shortcut for `--format
json`). Exit code carries the verdict so CI can gate on it: `0` pass · `1` watchlist ·
`2` fail.

### Fleet mode - one scorecard for many repos

Point it at several repos at once and it forges a single **fleet scorecard**: every repo
graded, then rolled up into one verdict (worst-wins, the same rule the single card uses
across its dimensions). This is the shared, multi-consumer surface - platform tooling, not
a one-repo script.

```bash
forge-audit --fleet ../codeforge ../ai-log-triage ../federal-guidance-library
forge-audit --fleet ../codeforge ../ai-log-triage --stage advanced --json   # machine-readable
forge-audit --fleet ../codeforge ../ai-log-triage --format md               # a portfolio-index table
```

`--fleet` takes one or more paths and overrides `--path`; `--stage`, `--format`, and
`--online` apply to every repo in the run. An empty fleet or a path that is not a directory
refuses the run rather than grading a partial, misleading fleet.

## What it grades

| Dimension | Evidence | Passes when |
|-----------|----------|-------------|
| `lint` | `ruff check` | clean |
| `typecheck` | `mypy` | clean |
| `tests` | `pytest --cov` | green suite **and** coverage ≥ the stage floor |
| `security` | `bandit` | no findings |
| `dependencies` | `pip-audit` | no known CVEs |
| `ci` | workflow files in `.github/workflows` | count ≥ the stage minimum |
| `collaboration` | merged PRs (via the GitHub seam) | at least one closed issue→PR→merge loop |
| `performance` | a benchmark artifact (`benchmarks/`, a `bench` Makefile target, or a `reports/` perf dir) | present (else a watchlist gap) |
| `readme` | the README's content (purpose · install · run · test) | all four covered (else a watchlist gap naming what's missing) |

### Stage thresholds (baked in - the gate is objective, not vibes)

| Stage | Coverage floor | CI workflows |
|-------|----------------|--------------|
| `entry` | 70% | 1 |
| `intermediate` | 80% | 2 |
| `advanced` | 85% | 3 |

The overall verdict is the worst dimension: any `fail` → **fail**; any `watchlist` →
**watchlist**; otherwise **pass**. `role_signals` (testing · security · backend · devops ·
collaboration) are claimed **only** when the dimensions that prove them pass.

## Architecture

Two seams to the outside world, both mockable, so **tests never touch the network or a
real tool**:

- **`engine.Runner`** - runs a gate as a subprocess; tests inject a fake returning canned
  results. `DiagnosticEngine` (`diagnose`) turns tool exit codes into `GateReading`s.
- **`github.RepoProbe`** - a `Protocol` for collaboration signals. The real `GhProbe`
  shells out to `gh`; `OfflineProbe` reads only the local workflow count; tests inject a
  fake. CI runs with no token.

`scorecard.build_scorecard` is the `EvidenceLedger`: it weighs the readings and signals
against the stage thresholds and forges the `Scorecard`.

## It audits itself

The tool holds itself to its own rule. Its CI runs the dogfood step; the table below is its
`--format md` output at the **intermediate** stage - regenerate it yourself (the volatile
numbers stay on the live badges, so nothing here can silently drift):

```
$ forge-audit --path . --stage intermediate --online --format md
```

### forge-audit - forge-audit (intermediate stage)

| Dimension | Verdict | Evidence |
|---|---|---|
| lint | ✅ pass | clean |
| typecheck | ✅ pass | clean |
| tests | ✅ pass | green suite, coverage above the 80% floor (the codecov badge is the live source) |
| security | ✅ pass | clean |
| dependencies | ✅ pass | clean |
| ci | ✅ pass | workflow files: `ci`, `codeql` |
| collaboration | ✅ pass | a real issue -> PR -> merge history |
| performance | ✅ pass | a `benchmarks/` directory (`make bench` times the tool's own grading overhead) |
| **overall** | **✅ pass** | role signals: testing · security · backend · devops · collaboration · performance |

Honest about its own age: at the **advanced** stage the tool grades itself `watchlist`, not
`pass` - a young repo with two workflow files legitimately sits on the watchlist, and the
tool says so rather than inflate the verdict. The collaboration signal passes only with
`--online`, where the tool observes the real issue -> PR -> merge loop
([#3](https://github.com/MatrymLabs/forge-audit/issues/3) -> [#4](https://github.com/MatrymLabs/forge-audit/pull/4));
run it offline and that dimension drops to `watchlist` rather than assume the loop. Either
way: **no claim without correspondence,** even about itself.

## Test

```bash
make check       # ruff + mypy + pytest
make bench       # micro-benchmark the tool's own grading overhead (no subprocess, no network)
make coverage    # coverage gate (≥ 85%)
make security    # bandit + pip-audit + detect-secrets
make secrets     # detect-secrets, against the baseline
make sbom        # CycloneDX software bill of materials
make dogfood     # audit the codeforge flagship next door
```

## Part of the MatrymLabs ship

`forge-audit` is the ship's one net-new build - the evaluator that scores the flagships
(`codeforge`, `ai-log-triage`, `federal-guidance-library`). Its output belongs in each
flagship's README *Evaluation* section. It reports **readiness**, never certification.

MIT.
