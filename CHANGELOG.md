# Changelog

All notable changes to forge-audit are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Community-health docs - `CONTRIBUTING.md`, `SECURITY.md`, this `CHANGELOG.md`.
- `make secrets` - detect-secrets scan against a committed `.secrets.baseline`, run in CI.
- CodeQL SAST (`.github/workflows/codeql.yml`, Python + workflows) and `make sbom`
  (CycloneDX bill of materials, generated in CI and kept as an artifact).

### Changed
- Evidence-set parity with the codeforge flagship (security + docs).

### Removed
- Dead `open_issues` signal - it was fetched over the network but never scored or
  rendered; removed the field, its fetch, and the unused `_gh_count` helper.

## [0.1.0] - 2026-07-09

### Added
- Initial MVP: `forge-audit --path <repo> --stage <s>` runs the quality gates on a target
  repo (ruff · mypy · pytest --cov · bandit · pip-audit) and emits a JSON scorecard
  (`pass | watchlist | fail`) graded against baked-in stage thresholds.
- Two mockable seams - `engine.Runner` (subprocess) and `github.RepoProbe` (GitHub) - so
  tests never touch the network or a real tool.
- Audits a repo with **its own** `.venv/bin/*` toolchain and `[tool.bandit]` config;
  security gated on medium+ severity; a missing tool reads `not_configured`, never faked.
- `--format {human,json,md}` output; `md` emits a README-ready Markdown table (`--json`
  kept as a shortcut).
- Scaffold: `src/` layout, CI (mocked seams, no token), Dependabot, MIT license.

[Unreleased]: https://github.com/MatrymLabs/forge-audit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MatrymLabs/forge-audit/releases/tag/v0.1.0
