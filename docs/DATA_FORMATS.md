# Data formats

## Receipt text

- UTF-8 or UTF-8 with BOM.
- One physical receipt line per text line.
- Maximum 2 MB, 10,000 lines, and 1,000 characters per line.
- Dates currently support `YYYY-MM-DD`, `YYYY/MM/DD`, `MM/DD/YYYY`, and dot variants.
- Money requires two decimal places on item/total lines.

The source file bytes are hashed before decoding. A byte-identical duplicate is idempotent even when imported from a different directory.

## Alias JSON v1

Top-level fields:

- `schema_version`: integer `1`;
- `products`: non-empty rule-bearing product objects.

Product fields:

- `key`: lowercase ASCII letters/digits/hyphens, maximum 64 characters;
- `name`: display name, maximum 120 characters;
- `category`: display category, maximum 80 characters;
- `aliases`: one or more rules.

Alias fields:

- `pattern`: maximum 120 characters;
- `match`: `exact`, `contains`, or `glob`;
- `merchant`: exact normalized merchant or `*`;
- `package`: optional complete size such as `500 g`, `1 L`, `12 ct`, or `2 x 150 g`;
- `priority`: optional integer from -50 to 50.

Merchant-specific rules outrank wildcard rules. Match precedence is exact, contains, then glob. Equal top-ranked rules for different products produce `ambiguous`.

## Analysis JSON v1

The document contains:

- `summary`: counts, mapped percentage, basket change, currency;
- `thresholds`: explicit price/package thresholds;
- `alerts`: price spike, package shrink, and unit conflict records;
- `products`: canonical product summaries and history;
- `review_queue`: unresolved raw descriptors and candidates;
- `evidence`: receipt basenames, totals, and full SHA-256 values.

Money values in output JSON are decimal strings. Percentages are rounded to two decimals. `null` means the supplied evidence was insufficient for that comparison.

## CSV

The CSV is UTF-8, RFC 4180-compatible, and uses LF line endings. Money and unit prices are decimal strings. Receipt-derived cells that could trigger spreadsheet formulas are prefixed with a single quote.

## Exit codes

- `0`: command succeeded; a review queue may still be present.
- `1`: `verify` completed and found an integrity failure.
- `2`: invalid user data, alias configuration, filesystem operation, or database operation.
