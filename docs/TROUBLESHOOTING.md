# Troubleshooting and repair

Preserve the database and original receipt files before attempting a repair. PriceWitness never needs a ledger deletion as the first step.

## `receipt contains no recognizable line items`

Diagnosis:

```bash
python -c "from pathlib import Path; print(Path('receipt.txt').read_text(encoding='utf-8'))"
```

Check that item lines end in a two-decimal amount and that OCR did not put product/price in separate columns or lines.

Repair:

1. Keep the original scan unchanged.
2. Correct a copy of the OCR text so each item is on one line.
3. Ingest the corrected text. The byte hash will make it a distinct evidence source.

## Every item is in `review`

Diagnosis:

```bash
pricewitness export groceries.db --output review.csv
pricewitness aliases validate aliases.json
```

Repair one narrow pattern first:

```bash
pricewitness aliases add aliases.json \
  --product-key oat-milk-barista \
  --product-name "Oat milk, barista" \
  --category "dairy alternatives" \
  --pattern "OAT BRT 1 L" \
  --package "1 L"
pricewitness rematch groceries.db --aliases aliases.json
```

Prefer exact aliases. Use contains/glob only when fixtures prove they cannot capture another product.

## An item is `ambiguous`

Two products have equal top-ranked matches. Narrow one rule with a merchant, make an exact pattern, or lower its priority. Do not use a catch-all alias to suppress the warning.

```bash
pricewitness aliases validate aliases.json
pricewitness rematch groceries.db --aliases aliases.json
```

## `source hash mismatch`

The supplied file bytes differ from the file that was ingested.

1. Do not overwrite either copy.
2. Compare file size, modification date, and SHA-256 using your operating system.
3. Locate the original or treat the new bytes as a new source and ingest them separately.
4. Preserve the failed verification JSON with the evidence package.

## SQLite integrity or foreign-key failure

First copy the `.db`, `.db-wal`, and `.db-shm` files while no PriceWitness process is running. Then inspect using a copy:

```bash
python -m sqlite3 groceries-copy.db ".recover"
```

If your Python build does not expose the SQLite CLI module, use the official `sqlite3` tool:

```bash
sqlite3 groceries-copy.db "PRAGMA integrity_check;"
sqlite3 groceries-copy.db ".recover" > recovered.sql
sqlite3 recovered.db < recovered.sql
pricewitness verify recovered.db
```

Never replace the original until the recovered copy passes `verify` and row counts match.

## Subtotal plus tax differs from total

This is a warning, not an integrity failure. Check for coupons, bottle deposits, tips, tax-inclusive pricing, refunds, or OCR loss. The raw classified lines remain in SQLite for review.

## CSV opens as a formula

PriceWitness prefixes dangerous receipt-derived cells with `'`. If a downstream tool removes that prefix, import the column as text. Do not disable the protection in shared exports.

## Build cannot download dependencies

Runtime PriceWitness has no third-party dependencies, but development/build tools do. After network access returns:

```bash
python -m pip install -e ".[dev]"
python -m pip show build setuptools wheel
python scripts/release_check.py
```

The first command is the only step that may need the package index. Once those declared tools are installed, `package_release.py` builds with the local backend (`--no-isolation`) and does not create a second network-dependent build environment. If installation still fails, fix the proxy/CA configuration or select an organization-approved package mirror; do not disable TLS verification.

If an editable install is already present, the runtime demo can still run without fetching anything:

```bash
pricewitness demo --output .demo-offline
```

## Release checksum failure

Do not upload the mismatching asset. Rebuild into a fresh output directory and rerun:

```bash
python scripts/package_release.py --output release
python scripts/verify_release.py --directory release
```

If two deliberately separated builds differ, inspect wheel and sdist archive metadata before publishing. `SOURCE_DATE_EPOCH` is fixed by the packaging script.
