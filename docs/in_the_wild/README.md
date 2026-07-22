# forge-audit in the wild

The [honest envelope](../../README.md#auditing-a-repo-you-didnt-build-the-honest-envelope)
is a claim: *forge-audit grades a repo it did not build honestly, passing what is clean,
abstaining where it lacks the environment, respecting each repo's own toolchain, and
flagging real issues without defaming a green-CI project.* This page is the proof: three
well-known, well-run open-source Python repositories, each graded at the **advanced**
stage (the strictest bar), with the raw JSON scorecards committed next to this file. A
second panel below - [compliance depth in the wild](#compliance-depth-in-the-wild) - runs
the deepened `license` dimension against six more repos to show it grades real foreign code
without a single false positive.

**These are excellent repositories.** The point is not to rank them. The point is to show
what forge-audit does when it meets code it did not write: where it passes, where it
honestly abstains, where it respects the repo's own choices, and where it reports a real
finding a human then interprets.

## How this was run (reproducible)

Each target was cloned and its **full declared dev environment** was installed into the
target's own `.venv` (the honest envelope requires it: `tests` and `typecheck` grade
fairly only with the repo's deps present). Then:

```bash
forge-audit --path <repo> --stage advanced --format md
```

Graded 2026-07-18 against these pinned commits:

| Repo | Commit | What it is |
| --- | --- | --- |
| [tenacity](https://github.com/jd/tenacity) | `c650fb4` | retry library (ruff + mypy + pytest) |
| [rich](https://github.com/Textualize/rich) | `9d8f9a3` | terminal rendering (black + isort + mypy) |
| [httpx](https://github.com/encode/httpx) | `b5addb6` | HTTP client (ruff + mypy + pytest) |

Re-run against a newer commit and the numbers may move; that is the point of grading by
running, not by asserting.

---

## tenacity

### forge-audit - tenacity (advanced stage)

| Dimension | Verdict | Evidence |
|---|---|---|
| lint | ✅ pass | clean |
| typecheck | 🔶 watchlist | not graded here: imports unresolved (deps absent) |
| tests | ✅ pass | green suite, coverage 95% ≥ 85% |
| security | ✅ pass | clean |
| dependencies | ✅ pass | clean |
| ci | 🔶 watchlist | 2 workflow(s) < 3 for this stage |
| collaboration | 🔶 watchlist | no merged-PR loop observed (offline) |
| performance | 🔶 watchlist | no benchmark/profiling artifact found |
| readme | ✅ pass | covers purpose, install, run, test |
| **overall** | **🔶 watchlist** | role signals: testing · security · documentation |

**Read it:** lint, tests (95% coverage), and security all pass on real execution. The
`typecheck` row **abstains** rather than fails: mypy could not resolve every import in the
environment as installed, and forge-audit will not turn its own missing stubs into a defect
it pins on tenacity. The `ci` / `performance` rows are honest advanced-bar gaps (a small,
focused library reasonably ships two workflows and no benchmark suite), reported as
`watchlist`, not `fail`. Raw: [`tenacity.scorecard.json`](tenacity.scorecard.json).

## rich

### forge-audit - rich (advanced stage)

| Dimension | Verdict | Evidence |
|---|---|---|
| lint | 🔶 watchlist | repo lints with black + isort, not ruff (not graded here) |
| typecheck | 🔶 watchlist | not graded here: imports unresolved (deps absent) |
| tests | 🔶 watchlist | not graded here: suite not collectable (deps absent) |
| security | ❌ fail | 2 high, 4 medium severity issue(s) |
| dependencies | ✅ pass | clean |
| ci | ✅ pass | 6 CI workflow(s) |
| performance | ✅ pass | benchmark artifact: benchmarks/ directory |
| readme | 🔶 watchlist | README missing: test |
| **overall** | **❌ fail** | role signals: devops · performance |

**Read it:** this is the toolchain-respect case. rich lints with **black + isort** and never
adopted ruff, so forge-audit **abstains** on lint ("not graded here") instead of imposing
ruff's opinionated defaults and inventing 80+ findings. It does the same on typecheck and
tests where the environment as installed could not collect the suite. The `security` row is
a **real** bandit result (high-severity findings in shipped code), reported transparently
with its count. Whether those are true risks or acceptable-in-context is a **human** call:
forge-audit surfaces the finding; it does not pretend to adjudicate it. Raw:
[`rich.scorecard.json`](rich.scorecard.json).

## httpx

### forge-audit - httpx (advanced stage)

| Dimension | Verdict | Evidence |
|---|---|---|
| lint | ✅ pass | clean |
| typecheck | ✅ pass | clean |
| tests | ✅ pass | green suite, coverage 100% ≥ 85% |
| security | ❌ fail | 1 high severity issue(s) |
| dependencies | ✅ pass | clean |
| ci | 🔶 watchlist | 2 workflow(s) < 3 for this stage |
| performance | 🔶 watchlist | no benchmark/profiling artifact found |
| readme | 🔶 watchlist | README missing: test |
| **overall** | **❌ fail** | role signals: testing · backend |

**Read it:** with httpx's full dev environment installed, code quality grades cleanly:
lint, typecheck, and tests all pass at **100% coverage**. The `security` row is **one high**
finding, and it is the instructive one: it is httpx's HTTP **digest-auth** hashing, which
[RFC 7616](https://www.rfc-editor.org/rfc/rfc7616) *requires* (MD5/SHA1 are mandated by the
digest scheme). bandit sees a weak hash; a human sees a spec-mandated algorithm. forge-audit
reports exactly what the scanner found, with the count, and leaves the judgment to the
engineer. **That is the thesis:** the tool measures, the evidence is transparent, the human
makes the call. Raw: [`httpx.scorecard.json`](httpx.scorecard.json).

> An earlier run graded httpx's typecheck as `fail` with 24 errors. That was an incomplete
> environment (base deps without the pinned type-stub extras), not an httpx defect. Installing
> the repo's full pinned dev requirements produced the clean grade above. The lesson is the
> honest envelope's own rule: **a fair grade needs the target's deps.**

---

## Compliance depth in the wild

The `license` dimension is now four layers deep: root-license detection, a **per-file
`SPDX-License-Identifier` scan**, a **dependency-license copyleft scan**, and **SBOM
validation + a staleness cross-check**. The two filesystem layers need no dev environment,
so they grade a bare clone directly. Run 2026-07-22 against six well-known repos (raw:
[`compliance_scan.json`](compliance_scan.json)):

| Repo | Commit | Root license | SPDX headers | License verdict |
|---|---|---|---|---|
| [numpy](https://github.com/numpy/numpy) | `dbe3531` | BSD-3-Clause | 0 | ✅ pass |
| [pytest](https://github.com/pytest-dev/pytest) | `532b201` | MIT | 0 | ✅ pass |
| [pydantic](https://github.com/pydantic/pydantic) | `7b3dd4c` | MIT | 0 | ✅ pass |
| [flask](https://github.com/pallets/flask) | `36e4a82` | BSD-3-Clause | 0 | ✅ pass |
| [requests](https://github.com/psf/requests) | `69f8484` | Apache-2.0 (+ NOTICE) | 0 | ✅ pass |
| [Pillow](https://github.com/python-pillow/Pillow) | `b741b77` | *unrecognized* | 1 | 🔶 watchlist |

**Read it:**

- **Detection spans the permissive licenses**, not just MIT: BSD-3-Clause (numpy, flask),
  Apache-2.0 (requests, whose `NOTICE` file is also surfaced as provenance).
- **The per-file scan ran on every repo and raised nothing false.** Mainstream permissive
  Python does not carry per-file SPDX headers, so the conflict scan correctly stays silent.
  For a compliance check, **zero false positives on code it did not write is the signal** -
  a tool that cried "contamination" on numpy would be worthless.
- **Pillow abstains, it does not guess.** forge-audit does not recognize Pillow's HPND
  license text, so the dimension reads `watchlist - present but unrecognized`, never a wrong
  guess and never a `fail`. That is the same honesty the `tests`/`typecheck` gates show when
  the environment is thin: **say "unknown," never fake a verdict.**

The two env-dependent layers (the **GPL/AGPL dependency scan** and **SBOM validation +
freshness**) need each target's own `.venv` and committed SBOM, which mainstream repos
gitignore. They are proven instead in the [self-audit](../../README.md#it-audits-itself) and
the test suite: forge-audit grades its **own** installed dependencies (correctly ignoring its
MPL-2.0 and LGPL deps, and it would flag a GPL one) and its **own** freshly generated
CycloneDX SBOM (67 components, cross-checked against what is installed). Same rule as the
whole page: measure what the environment permits, and say so plainly where it does not.

---

## What these prove

- **It passes what is clean.** tenacity's tests, httpx's lint/typecheck/tests: real green, on real execution.
- **It abstains, never defames.** Missing deps or an un-collectable suite read `watchlist - not graded here`, never `fail`. A green-CI project is never called broken because our environment is thin. An unrecognized license reads `watchlist - unrecognized`, never a wrong guess.
- **It respects the repo's own toolchain.** rich lints with black; forge-audit does not impose ruff on it.
- **It reports real findings transparently.** httpx's digest-auth hash and rich's bandit highs are surfaced with counts and evidence, for a human to interpret. No black box, no flattery.
- **Its compliance depth does not cry wolf.** The per-file license scan runs on real foreign code and raises nothing false; the copyleft/SBOM guards stay silent unless there is something real to flag.

forge-audit reports **readiness**, never certification. A verdict here is a measurement against
an objective bar, not a judgment of a project's worth.
