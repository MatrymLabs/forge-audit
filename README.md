# forge-audit

**The proof-tool.** A portfolio makes a claim — *this engineer uses AI as a force
multiplier, wrapped in automated evidence, quality gates, and delivery mechanics.*
`forge-audit` **proves** that claim instead of asserting it: point it at a repository and
it runs the quality gates, reads the collaboration signals, and forges a machine-checkable
**JSON scorecard** graded against objective stage thresholds.

> *No claim without correspondence.* Every verdict quotes its evidence. A gate whose tool
> is absent reads `not_configured` — it is never faked as passing.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: make env
```

## Run

```bash
forge-audit --path ../codeforge --stage intermediate --json
forge-audit --path .                      # human-readable summary of this repo
forge-audit --path ../codeforge --online  # add live issue/PR signals via the `gh` CLI
```

Exit code carries the verdict so CI can gate on it: `0` pass · `1` watchlist · `2` fail.

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

### Stage thresholds (baked in — the gate is objective, not vibes)

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

- **`engine.Runner`** — runs a gate as a subprocess; tests inject a fake returning canned
  results. `DiagnosticEngine` (`diagnose`) turns tool exit codes into `GateReading`s.
- **`github.RepoProbe`** — a `Protocol` for collaboration signals. The real `GhProbe`
  shells out to `gh`; `OfflineProbe` reads only the local workflow count; tests inject a
  fake. CI runs with no token.

`scorecard.build_scorecard` is the `EvidenceLedger`: it weighs the readings and signals
against the stage thresholds and forges the `Scorecard`.

## Test

```bash
make check       # ruff + mypy + pytest
make coverage    # coverage gate (≥ 85%)
make security    # bandit + pip-audit
make dogfood     # audit the codeforge flagship next door
```

## Part of the MatrymLabs ship

`forge-audit` is the ship's one net-new build — the evaluator that scores the flagships
(`codeforge`, `ai-log-triage`, `federal-guidance-library`). Its output belongs in each
flagship's README *Evaluation* section. It reports **readiness**, never certification.

MIT.
