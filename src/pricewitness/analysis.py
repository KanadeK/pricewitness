"""Evidence-bounded price, package-size, and review analysis."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from pricewitness.db import connect, initialize
from pricewitness.units import comparison_scale


def analyze(
    database: str | Path,
    *,
    spike_threshold: float = 10.0,
    shrink_threshold: float = 5.0,
) -> dict[str, Any]:
    """Build a deterministic analysis document from mapped observations."""

    if spike_threshold < 0 or shrink_threshold < 0:
        raise ValueError("analysis thresholds cannot be negative")
    initialize(database)
    with connect(database) as connection:
        receipts = connection.execute("SELECT * FROM receipts ORDER BY purchased_at, id").fetchall()
        rows = connection.execute(
            """
            SELECT o.*, r.merchant, r.purchased_at, r.currency, r.source_name,
                   r.source_sha256
            FROM observations o JOIN receipts r ON r.id = o.receipt_id
            ORDER BY r.purchased_at, r.id, o.line_no
            """
        ).fetchall()

    observation_count = len(rows)
    mapped_count = sum(1 for row in rows if row["status"] == "mapped")
    priced_count = sum(1 for row in rows if row["unit_price_micros"] is not None)
    review_queue = [
        {
            "date": row["purchased_at"],
            "merchant": row["merchant"],
            "source": row["source_name"],
            "line_no": row["line_no"],
            "raw_name": row["raw_name"],
            "suggested_key": row["suggested_key"],
            "status": row["status"],
            "candidates": json.loads(row["candidates_json"]),
        }
        for row in rows
        if row["status"] != "mapped"
    ]

    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        if row["product_key"] is not None:
            grouped[row["product_key"]].append(row)

    alerts: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    basket_pairs: list[tuple[Decimal, Decimal]] = []
    for key in sorted(grouped):
        product_rows = grouped[key]
        product, product_alerts, basket_pair = _analyze_product(
            key,
            product_rows,
            spike_threshold=Decimal(str(spike_threshold)),
            shrink_threshold=Decimal(str(shrink_threshold)),
        )
        products.append(product)
        alerts.extend(product_alerts)
        if basket_pair is not None:
            basket_pairs.append(basket_pair)

    basket_change = _weighted_basket_change(basket_pairs)
    currencies = sorted({row["currency"] for row in receipts})
    currency = currencies[0] if len(currencies) == 1 else ("MIXED" if currencies else "USD")
    mapped_percent = round((mapped_count / observation_count * 100), 2) if rows else 0.0
    evidence = [
        {
            "date": receipt["purchased_at"],
            "merchant": receipt["merchant"],
            "source": receipt["source_name"],
            "sha256": receipt["source_sha256"],
            "total": _money(receipt["total_cents"]),
            "currency": receipt["currency"],
        }
        for receipt in receipts
    ]
    alerts.sort(key=lambda item: (item["date"], item["product_key"], item["type"]))
    return {
        "schema_version": 1,
        "summary": {
            "receipt_count": len(receipts),
            "observation_count": observation_count,
            "mapped_count": mapped_count,
            "review_count": len(review_queue),
            "priced_count": priced_count,
            "mapped_percent": mapped_percent,
            "product_count": len(products),
            "alert_count": len(alerts),
            "basket_change_percent": _round_optional(basket_change),
            "currency": currency,
        },
        "thresholds": {
            "price_spike_percent": spike_threshold,
            "package_shrink_percent": shrink_threshold,
        },
        "alerts": alerts,
        "products": products,
        "review_queue": review_queue,
        "evidence": evidence,
    }


def write_analysis_json(
    database: str | Path,
    output: str | Path,
    *,
    spike_threshold: float = 10.0,
    shrink_threshold: float = 5.0,
) -> dict[str, Any]:
    document = analyze(
        database,
        spike_threshold=spike_threshold,
        shrink_threshold=shrink_threshold,
    )
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return document


def _analyze_product(
    key: str,
    rows: list[Any],
    *,
    spike_threshold: Decimal,
    shrink_threshold: Decimal,
) -> tuple[dict[str, Any], list[dict[str, Any]], tuple[Decimal, Decimal] | None]:
    alerts: list[dict[str, Any]] = []
    priced = [row for row in rows if row["unit_price_micros"] is not None]
    units = sorted({row["base_unit"] for row in priced})
    history: list[dict[str, Any]] = []
    basket_pair: tuple[Decimal, Decimal] | None = None

    if len(units) > 1:
        alerts.append(
            {
                "type": "unit-conflict",
                "severity": "review",
                "product_key": key,
                "product": rows[0]["canonical_name"],
                "date": rows[-1]["purchased_at"],
                "message": f"Mapped observations use incompatible base units: {', '.join(units)}.",
            }
        )

    active_unit = units[0] if len(units) == 1 else None
    scale = label = None
    comparable = priced
    if active_unit is not None:
        scale, label = comparison_scale(active_unit)
        comparable = [row for row in priced if row["base_unit"] == active_unit]
        for row in comparable:
            history.append(
                {
                    "date": row["purchased_at"],
                    "merchant": row["merchant"],
                    "source": row["source_name"],
                    "total": _money(row["total_cents"]),
                    "base_amount": row["base_amount"],
                    "base_unit": row["base_unit"],
                    "unit_price": _scaled_price(row["unit_price_micros"], scale),
                    "comparison_unit": label,
                }
            )

        for previous, current in pairwise(comparable):
            previous_price = Decimal(previous["unit_price_micros"])
            current_price = Decimal(current["unit_price_micros"])
            if previous_price > 0:
                delta = (current_price / previous_price - 1) * 100
                if delta >= spike_threshold:
                    alerts.append(
                        {
                            "type": "price-spike",
                            "severity": "watch",
                            "product_key": key,
                            "product": current["canonical_name"],
                            "date": current["purchased_at"],
                            "merchant": current["merchant"],
                            "change_percent": _round(delta),
                            "message": (
                                f"Unit price rose {_round(delta)}% since the prior mapped purchase."
                            ),
                        }
                    )

            previous_amount = Decimal(previous["base_amount"])
            current_amount = Decimal(current["base_amount"])
            if previous_amount > 0 and current_amount < previous_amount:
                shrink = (1 - current_amount / previous_amount) * 100
                total_ratio = Decimal(current["total_cents"]) / Decimal(
                    max(int(previous["total_cents"]), 1)
                )
                if shrink >= shrink_threshold and total_ratio >= Decimal("0.95"):
                    alerts.append(
                        {
                            "type": "package-shrink",
                            "severity": "watch",
                            "product_key": key,
                            "product": current["canonical_name"],
                            "date": current["purchased_at"],
                            "merchant": current["merchant"],
                            "shrink_percent": _round(shrink),
                            "from_amount": str(previous_amount.normalize()),
                            "to_amount": str(current_amount.normalize()),
                            "base_unit": active_unit,
                            "message": (
                                f"Package amount fell {_round(shrink)}% while total price "
                                "stayed within 5%."
                            ),
                        }
                    )

        if len(comparable) >= 2:
            first_price = Decimal(comparable[0]["unit_price_micros"])
            last_price = Decimal(comparable[-1]["unit_price_micros"])
            if first_price > 0:
                basket_pair = (Decimal(comparable[0]["total_cents"]), last_price / first_price)

    first_price_value = last_price_value = change = None
    best_merchant = None
    if active_unit is not None and comparable and scale is not None:
        first_price_value = _scaled_price(comparable[0]["unit_price_micros"], scale)
        last_price_value = _scaled_price(comparable[-1]["unit_price_micros"], scale)
        first_raw = Decimal(comparable[0]["unit_price_micros"])
        last_raw = Decimal(comparable[-1]["unit_price_micros"])
        if first_raw > 0:
            change = _round((last_raw / first_raw - 1) * 100)
        latest_by_merchant: dict[str, Any] = {}
        for row in comparable:
            latest_by_merchant[row["merchant"]] = row
        best = min(latest_by_merchant.values(), key=lambda row: row["unit_price_micros"])
        best_merchant = best["merchant"]

    return (
        {
            "key": key,
            "name": rows[0]["canonical_name"],
            "category": rows[0]["category"],
            "observation_count": len(rows),
            "priced_count": len(priced),
            "base_unit": active_unit,
            "comparison_unit": label,
            "first_date": rows[0]["purchased_at"],
            "latest_date": rows[-1]["purchased_at"],
            "first_unit_price": first_price_value,
            "latest_unit_price": last_price_value,
            "change_percent": change,
            "latest_merchant": rows[-1]["merchant"],
            "best_current_merchant": best_merchant,
            "history": history,
        },
        alerts,
        basket_pair,
    )


def _weighted_basket_change(pairs: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    total_weight = sum((weight for weight, _ in pairs), Decimal("0"))
    if total_weight <= 0:
        return None
    ratio = sum((weight * price_ratio for weight, price_ratio in pairs), Decimal("0"))
    return (ratio / total_weight - 1) * 100


def _scaled_price(unit_price_micros: int, scale: Decimal) -> str:
    amount = Decimal(unit_price_micros) * scale / Decimal("1000000")
    return f"{amount.quantize(Decimal('0.0001')):.4f}"


def _money(cents: int | None) -> str | None:
    if cents is None:
        return None
    return f"{Decimal(cents) / Decimal(100):.2f}"


def _round(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _round_optional(value: Decimal | None) -> float | None:
    return _round(value) if value is not None else None
