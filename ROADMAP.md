# Roadmap

`forge-audit` is a proof-tool: point it at a repository and it runs the quality gates,
reads the collaboration signals, and emits a machine-checkable JSON scorecard graded
against objective stage thresholds. This is where it stands and where it is going.
Status labels are honest: **shipped** means done and tested; everything else is a plan,
not a promise.

For the full history of changes, see [CHANGELOG.md](CHANGELOG.md).

## Now (shipped)

- The scorecard engine: gates + collaboration signals -> a `pass | watchlist | fail`
  JSON verdict, graded against staged coverage/CI thresholds. Every verdict quotes its
  evidence; a gate whose tool is absent reads `not_configured`, never a faked pass.
- Two mockable seams so the suite never touches the network or a real tool: the
  subprocess runner (`engine.Runner`) and the GitHub probe (`github.RepoProbe`, with an
  offline filesystem probe and an online `gh` probe).
- Self-hosting evidence set: `make check` (lint + types + tests + coverage), bandit,
  detect-secrets, a CycloneDX SBOM artifact, CodeQL, Dependabot, and a dogfood step that
  proves the tool runs and emits a valid scorecard on its own repo.

## Next

- Publish coverage to Codecov so the badge is earned, not asserted (in progress).
- Embed a live `forge-audit` scorecard in each flagship's README "Evaluation" section,
  so the portfolio's discipline claim is measured rather than stated.
- Broaden the role-signal reads (release cadence, issue/PR loop) as more evidence exists.

## Later (deferred by design)

- A reusable GitHub Action wrapper, once the CLI contract is stable.
- Configurable, project-supplied thresholds beyond the built-in stages.
- Fleet mode polish (`make dogfood-fleet`) for auditing several repos in one pass.

Deferred items are deliberate scope control, not gaps to hide: the tool proves the thesis
today, and each addition earns its place before it lands.
