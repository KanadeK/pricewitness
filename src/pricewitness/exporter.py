"""Portable exports with spreadsheet formula-injection protection."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from pricewitness.db import connect, initialize
from pricewitness.units import comparison_scale

_FIELDS = (
    "date",
    "merchant",
    "source",
    "source_sha256",
    "line_no",
    "raw_name",
    "status",
    "suggested_key",
    "product_key",
    "canonical_name",
    "category",
    "item_count",
    "total",
    "currency",
    "base_amount",
    "base_unit",
    "unit_price",
    "comparison_unit",
)


def export_csv(database: str | Path, output: str | Path) -> int:
    """Export every observation to a stable, review-friendly CSV."""

    initialize(database)
    with connect(database) as connection:
        rows = connection.execute(
            """
            SELECT o.*, r.purchased_at, r.merchant, r.source_name, r.source_sha256,
                   r.currency
            FROM observations o JOIN receipts r ON r.id = o.receipt_id
            ORDER BY r.purchased_at, r.id, o.line_no
            """
        ).fetchall()

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            unit_price = comparison_unit = ""
            if row["unit_price_micros"] is not None and row["base_unit"] is not None:
                scale, comparison_unit = comparison_scale(row["base_unit"])
                scaled = Decimal(row["unit_price_micros"]) * scale / Decimal("1000000")
                unit_price = f"{scaled.quantize(Decimal('0.0001')):.4f}"
            writer.writerow(
                {
                    "date": row["purchased_at"],
                    "merchant": _safe_cell(row["merchant"]),
                    "source": _safe_cell(row["source_name"]),
                    "source_sha256": row["source_sha256"],
                    "line_no": row["line_no"],
                    "raw_name": _safe_cell(row["raw_name"]),
                    "status": row["status"],
                    "suggested_key": row["suggested_key"],
                    "product_key": row["product_key"] or "",
                    "canonical_name": _safe_cell(row["canonical_name"] or ""),
                    "category": _safe_cell(row["category"] or ""),
                    "item_count": row["item_count"],
                    "total": f"{Decimal(row['total_cents']) / Decimal(100):.2f}",
                    "currency": row["currency"],
                    "base_amount": row["base_amount"] or "",
                    "base_unit": row["base_unit"] or "",
                    "unit_price": unit_price,
                    "comparison_unit": comparison_unit,
                }
            )
    return len(rows)


def _safe_cell(value: str) -> str:
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
