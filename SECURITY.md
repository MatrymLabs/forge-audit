# Security Policy

## Reporting a vulnerability

Please open a private [security advisory](https://github.com/MatrymLabs/forge-audit/security/advisories/new)
on GitHub, or email the maintainer. Do not file public issues for suspected
vulnerabilities.

## Design notes

forge-audit's only outward actions are **running the target repo's own toolchain**
(ruff, mypy, pytest, bandit, pip-audit) and, with `--online`, shelling out to the `gh`
CLI. It writes nothing to the target repo and holds no credentials of its own. Both the
subprocess runner (`engine.Runner`) and the network probe (`github.RepoProbe`) are seams,
so the test suite exercises them entirely with fakes — **tests never touch the network or
a real tool**. Only run forge-audit against repositories you trust: auditing a repo runs
that repo's configured tooling.

Its own supply chain is gated: `make security` (bandit + pip-audit) and `make secrets`
(detect-secrets, baselined) run in CI, and Dependabot watches dependencies.

## Supported versions

This is a portfolio project; `main` is the only supported line.
