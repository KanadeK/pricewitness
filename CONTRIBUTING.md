# Contributing

Thanks for improving PriceWitness. Contributions should preserve its evidence-first boundary.

## Setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest
```

## Before a pull request

```bash
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest
python scripts/release_check.py --skip-package
```

Parser changes require:

1. a synthetic receipt fixture;
2. a positive parsing test;
3. a false-positive test;
4. bounded input behavior;
5. documentation if the accepted grammar changes.

Do not commit real receipts or generated data derived from them. Do not add cloud AI, telemetry, retailer scraping, or a catch-all identity heuristic without an explicit architecture proposal and opt-in boundary.

Use conventional, descriptive commits. By contributing, you agree that your contribution is licensed under MIT.
