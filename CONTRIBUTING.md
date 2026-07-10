# Contributing to forge-audit

## Setup

```bash
git clone git@github.com:MatrymLabs/forge-audit.git && cd forge-audit
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"    # or: make env
make check                 # everything green before you start
```

## The rules

1. **Every module has a `CARD:` first docstring line and a test twin** in `tests/`
   (`src/forge_audit/x.py` → `tests/test_x.py`), with acceptance *and* refusal cases.
2. **The outside world is a seam, faked in tests.** The subprocess runner
   (`engine.Runner`) and the GitHub probe (`github.RepoProbe`) are injectable - tests
   never touch the network or a real tool. CI runs with no token.
3. **No claim without correspondence.** A gate whose tool is absent reads
   `not_configured`; a verdict quotes its evidence. Never fake a pass.
4. **One-Button Rule.** Any tool worth keeping gets a Makefile target.

## The ritual

```bash
make fix        # while working
make check      # before committing: lint (ruff) + mypy + pytest
make security   # bandit + pip-audit
make secrets    # detect-secrets, against the baseline
git commit -m "feat: <what it adds>"   # Conventional Commits
```

Commit types in use: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.
Work on a branch → PR → CI green → merge. Never merge a red PR.

## Verification culture

- Coverage is gated (`make coverage`, ≥ 85%). Files are judged by gates, not eyeballs.
- Dogfood your change: `make dogfood` audits the codeforge flagship next door.
- If a metric or threshold changes, update the README table and its test in the same PR.

## Onboarding checklist

- [ ] Clone, set up, and get `make check` green
- [ ] `forge-audit --path . --format md` - read your own repo's scorecard
- [ ] `make dogfood` - audit codeforge and read the verdict
- [ ] Read one module + its twin end to end (`scorecard.py` is a good start)
- [ ] Make a tiny docs PR before a code PR
