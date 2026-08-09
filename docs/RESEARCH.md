# Research and non-duplication snapshot

Snapshot date: **2026-08-08**. This is a bounded search record, not a permanent claim that no similar repository can ever exist.

## Requirement signal

A July 2026 self-hosting discussion asks for a tool that extracts grocery line items, categorizes products, tracks the same product over time, and compares price changes. The discussion repeatedly identifies abbreviated product normalization and unit price as the hard missing layer, and suggests combining multiple tools because no turnkey open-source path was known: [Self-hosted tool for tracking grocery expenses from receipts](https://www.reddit.com/r/selfhosted/comments/1v71z9l/selfhosted_tool_for_tracking_grocery_expenses/).

Similar earlier requests asked for itemized receipt analytics such as “which grocery store has cheaper spinach?” and noted the lack of a local open-source line-item extraction workflow: [Receipts based expense tracker?](https://www.reddit.com/r/selfhosted/comments/17qcrs4/receipts_based_expense_tracker/).

## Workspace and history exclusion

Before selection, the local `D:\我的\GitHub` workspace and the authenticated `KanadeK` repository list were inventoried. Existing projects already covered repository audits, release evidence, data privacy, home automation, game tooling, spreadsheet checks, household maintenance, laundry planning, meal scheduling, allergen matrices, and many other domains. The new project therefore could not be another generic developer dashboard, file preflight, maintenance planner, or data viewer.

Candidates excluded after web/GitHub checks:

| Candidate | Why it was rejected |
|---|---|
| Warranty/return tracker | Mature self-hosted projects already exist and have active communities. |
| Insurance-ready home inventory | Multiple current commercial and open-source products offer photos, receipts, room inventory, and PDF claim packs. |
| Generic grocery inventory | Grocy is mature and actively maintained. |
| Grocery price website scraper | Region-specific scraper projects already exist. |

## Adjacent repositories inspected

| Project | Current role | Boundary that remains |
|---|---|---|
| [grocy/grocy](https://github.com/grocy/grocy) | Full self-hosted household ERP with product, barcode, and price history features | Does not serve as a small post-OCR receipt normalization/evidence engine; integration is a future adapter target. |
| [Receipt-Wrangler/receipt-wrangler](https://github.com/Receipt-Wrangler/receipt-wrangler) | Multi-platform receipt management application | Broader receipt workflow; PriceWitness keeps deterministic grocery identity, unit normalization, and evidence verification as a portable layer. |
| [robisonkarls/grocery-receipt-parser](https://github.com/robisonkarls/grocery-receipt-parser) | OCR/LLM-to-SQLite pipeline and agent skill | Focuses on capture and search. Its public roadmap listed price adjustments and more stores; it did not expose the same alias review, unit comparison, shrink detection, and source verification contract in the inspected snapshot. |
| [viktorfa/python-receipt-parsing](https://github.com/viktorfa/python-receipt-parsing) | Research/prototype parser built around Google Vision and AWS-era setup | No release, no local end-to-end evidence workflow, and no cross-receipt review ledger in the inspected snapshot. |
| [Herover/heissepreise](https://github.com/Herover/heissepreise) | Danish grocery website price scraper and search UI | Retailer scraping rather than personal receipt evidence; region/store adapters are the core. |

## GitHub search record

Authenticated repository searches included:

```text
"grocery receipt price history"
"receipt normalization grocery"
"grocery receipt parser"
"grocery price tracker"
"pricewitness in:name"
```

The exact combined searches returned no repository implementing the full contract. Broader searches returned small parsers and price trackers, mostly 0–5 stars, plus region-specific scrapers. GitHub search briefly returned HTTP 403 secondary-rate-limit responses; those failures were treated as **no evidence**, then retried sequentially after the rate window recovered.

The `pricewitness` repository name had no GitHub repository result at selection time.

## Why this shape has discovery potential

No project can guarantee stars. PriceWitness was selected because it has several evidence-backed discovery hooks:

- a fresh and repeated self-hosting request;
- a universal consumer pain point: personal grocery inflation and shrinkflation;
- an integration-shaped boundary rather than an attempt to replace Grocy, Paperless-ngx, or Receipt Wrangler;
- a one-command offline demo with visibly meaningful alerts;
- no account, server, model download, or cloud bill;
- artifacts suitable for GitHub sharing: HTML evidence report, CSV, JSON, wheel, sdist, demo ZIP, checksums, and SBOM.

Popularity still depends on honest documentation, real-world merchant fixtures, integrations, maintenance, and community distribution after release.
