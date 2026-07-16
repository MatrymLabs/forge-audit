.PHONY: hooks env fix lint typecheck test check coverage security secrets sbom audit dogfood dogfood-fleet clean

# --- Environment: create/validate the .venv, install the tool + dev tooling ---
env: hooks
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -e ".[dev]"
	@.venv/bin/python -c "import sys; assert sys.version_info[:2] >= (3, 13), 'need Python >= 3.13'"
	@echo "✓ .venv ready - activate with: source .venv/bin/activate"

# --- Mutators: run while working ---
fix:
	ruff format .
	ruff check . --fix

# --- Gates: pure checks, cheapest first, nothing is modified ---
lint:
	ruff format --check .
	ruff check .

typecheck:
	mypy src tests

test:
	pytest -q

check: lint typecheck test

# Micro-benchmark forge-audit's own grading overhead (injected fakes; no subprocess, no network).
bench:
	python benchmarks/grading.py

coverage:
	pytest --cov=forge_audit --cov-report=term-missing --cov-report=xml --cov-fail-under=85

# SAST + dependency CVEs + committed secrets. bandit + detect-secrets gate; audit informs.
security:
	bandit -c pyproject.toml -r src -q
	pip-audit --skip-editable
	@git ls-files | xargs detect-secrets-hook --baseline .secrets.baseline

audit:
	pip-audit --skip-editable

# --- SBOM: a CycloneDX software bill of materials (SSDF supply-chain evidence).
# Generated from the installed environment; the output is git-ignored (reproducible
# from the recorded commit), while CI keeps it as an artifact. ---
sbom:
	cyclonedx-py environment -o sbom.cdx.json
	@echo "✓ SBOM -> sbom.cdx.json"

# --- Secret scan: fail on any tracked secret not in the audited baseline.
# Regenerate after auditing: detect-secrets scan --exclude-files '\.venv/' > .secrets.baseline ---
secrets:
	@git ls-files | xargs detect-secrets-hook --baseline .secrets.baseline

# --- Dogfood: audit the flagship next door and print its scorecard ---
dogfood:
	forge-audit --path ../codeforge --stage intermediate --json

dogfood-fleet:
	forge-audit --fleet ../codeforge ../ai-log-triage ../federal-guidance-library --stage intermediate --format md

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache coverage.xml htmlcov sbom.cdx.json *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

hooks:
	git config core.hooksPath scripts/hooks
	@echo "✓ git hooks active (scripts/hooks) - commits on main are refused"
