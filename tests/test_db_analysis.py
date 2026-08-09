from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pricewitness.aliases import AliasBook, add_alias
from pricewitness.analysis import analyze, write_analysis_json
from pricewitness.db import connect, ingest_file, ingest_files, initialize, rematch
from pricewitness.parser import ReceiptParseError


def test_demo_analysis_exercises_price_and_shrink_signals(demo_dir: Path) -> None:
    document = analyze(demo_dir / "pricewitness.db")
    assert document["summary"] == {
        "receipt_count": 3,
        "observation_count": 16,
        "mapped_count": 15,
        "review_count": 1,
        "priced_count": 16,
        "mapped_percent": 93.75,
        "product_count": 5,
        "alert_count": 5,
        "basket_change_percent": 14.87,
        "currency": "USD",
    }
    alert_types = {alert["type"] for alert in document["alerts"]}
    assert {"price-spike", "package-shrink"} <= alert_types
    assert document["review_queue"][0]["raw_name"] == "LOCAL JAM 250G"
    coffee = next(
        product for product in document["products"] if product["key"] == "dark-roast-coffee"
    )
    assert coffee["history"][0]["comparison_unit"] == "100 g"


def test_duplicate_receipt_is_idempotent(demo_dir: Path) -> None:
    result = ingest_file(
        demo_dir / "pricewitness.db",
        demo_dir / "receipts" / "receipt-2026-01-12.txt",
        aliases=AliasBook.from_path(demo_dir / "aliases.json"),
    )
    assert result.duplicate is True
    assert analyze(demo_dir / "pricewitness.db")["summary"]["receipt_count"] == 3


def test_rematch_promotes_review_item(demo_dir: Path) -> None:
    aliases_path = demo_dir / "aliases.json"
    add_alias(
        aliases_path,
        product_key="local-jam",
        product_name="Local jam",
        category="pantry",
        pattern="LOCAL JAM 250G",
        match_type="exact",
        merchant="*",
        package="250 g",
    )
    mapped, review = rematch(demo_dir / "pricewitness.db", AliasBook.from_path(aliases_path))
    assert (mapped, review) == (16, 0)
    assert analyze(demo_dir / "pricewitness.db")["summary"]["review_count"] == 0


def test_unit_conflicts_are_reported(demo_dir: Path) -> None:
    with connect(demo_dir / "pricewitness.db") as connection:
        connection.execute(
            """
            UPDATE observations SET base_unit = 'each'
            WHERE product_key = 'durum-pasta'
              AND id = (
                SELECT MAX(id) FROM observations WHERE product_key = 'durum-pasta'
              )
            """
        )
    document = analyze(demo_dir / "pricewitness.db")
    assert any(alert["type"] == "unit-conflict" for alert in document["alerts"])


def test_write_analysis_json_is_stable(demo_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "nested" / "analysis.json"
    first = write_analysis_json(demo_dir / "pricewitness.db", output)
    assert json.loads(output.read_text(encoding="utf-8")) == first
    with pytest.raises(ValueError, match="cannot be negative"):
        analyze(demo_dir / "pricewitness.db", spike_threshold=-1)


def test_invalid_utf8_source_fails_without_partial_row(tmp_path: Path) -> None:
    source = tmp_path / "bad.txt"
    source.write_bytes(b"\xff\xfe")
    database = tmp_path / "ledger.db"
    with pytest.raises(ReceiptParseError, match="not UTF-8"):
        ingest_files(database, [source], aliases=AliasBook.empty())
    with connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_initialize_rejects_future_schema(tmp_path: Path) -> None:
    database = tmp_path / "ledger.db"
    initialize(database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE metadata SET value = '99' WHERE key = 'schema_version'")
    with pytest.raises(ValueError, match="unsupported"):
        initialize(database)
