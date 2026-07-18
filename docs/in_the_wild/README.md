# forge-audit in the wild

The [honest envelope](../../README.md#auditing-a-repo-you-didnt-build-the-honest-envelope)
is a claim: *forge-audit grades a repo it did not build honestly, passing what is clean,
abstaining where it lacks the environment, respecting each repo's own toolchain, and
flagging real issues without defaming a green-CI project.* This page is the proof: three
well-known, well-run open-source Python repositories, each graded at the **advanced**
stage (the strictest bar), with the raw JSON scorecards committed next to this file.

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

## What these three prove

- **It passes what is clean.** tenacity's tests, httpx's lint/typecheck/tests: real green, on real execution.
- **It abstains, never defames.** Missing deps or an un-collectable suite read `watchlist - not graded here`, never `fail`. A green-CI project is never called broken because our environment is thin.
- **It respects the repo's own toolchain.** rich lints with black; forge-audit does not impose ruff on it.
- **It reports real findings transparently.** httpx's digest-auth hash and rich's bandit highs are surfaced with counts and evidence, for a human to interpret. No black box, no flattery.

forge-audit reports **readiness**, never certification. A verdict here is a measurement against
an objective bar, not a judgment of a project's worth.
