"""Allow ``python -m pricewitness`` to behave like the console command."""

from pricewitness.cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
