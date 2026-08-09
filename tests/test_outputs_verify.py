from __future__ import annotations

import csv
from pathlib import Path

from pricewitness.db import connect
from pricewitness.exporter import export_csv
from pricewitness.report import render_report, write_report
from pricewitness.verify import verify_database


def test_report_is_self_contained_and_escapes_untrusted_text(
    demo_dir: Path, tmp_path: Path
) -> None:
    with connect(demo_dir / "pricewitness.db") as connection:
        connection.execute(
            "UPDATE observations SET raw_name = '<script>alert(1)</script>' WHERE status = 'review'"
        )
    output = tmp_path / "report.html"
    write_report(demo_dir / "pricewitness.db", output)
    text = output.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<script>alert(1)</script>" not in text
    assert "https://" not in text
    assert 'id="pricewitness-analysis"' in text


def test_render_report_handles_empty_document() -> None:
    document = {
        "summary": {
            "receipt_count": 0,
            "mapped_percent": 0.0,
            "basket_change_percent": None,
            "alert_count": 0,
            "currency": "USD",
        },
        "alerts": [],
        "products": [],
        "review_queue": [],
        "evidence": [],
    }
    assert "No mapped products yet" in render_report(document)


def test_csv_export_is_formula_safe(demo_dir: Path, tmp_path: Path) -> None:
    with connect(demo_dir / "pricewitness.db") as connection:
        connection.execute("UPDATE observations SET raw_name = '=HYPERLINK(1)' WHERE id = 1")
    output = tmp_path / "observations.csv"
    assert export_csv(demo_dir / "pricewitness.db", output) == 16
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["raw_name"].startswith("'=")
    assert rows[0]["unit_price"] == "3.4900"


def test_verify_database_and_original_sources(demo_dir: Path) -> None:
    sources = sorted((demo_dir / "receipts").glob("*.txt"))
    result = verify_database(demo_dir / "pricewitness.db", sources)
    assert result.ok is True
    assert "original-source-hashes" in result.checks
    assert result.warnings == ()


def test_verify_reports_missing_database(tmp_path: Path) -> None:
    result = verify_database(tmp_path / "missing.db")
    assert result.ok is False
    assert "not found" in result.errors[0]


def test_verify_detects_source_and_arithmetic_tampering(demo_dir: Path) -> None:
    source = demo_dir / "receipts" / "receipt-2026-01-12.txt"
    source.write_text(source.read_text(encoding="utf-8") + "CHANGED\n", encoding="utf-8")
    with connect(demo_dir / "pricewitness.db") as connection:
        connection.execute("UPDATE observations SET unit_price_micros = 1 WHERE id = 1")
    result = verify_database(
        demo_dir / "pricewitness.db", sorted((demo_dir / "receipts").glob("*.txt"))
    )
    assert result.ok is False
    assert any("hash mismatch" in error for error in result.errors)
    assert any("arithmetic" in error for error in result.errors)


def test_verify_warns_when_sources_are_omitted(demo_dir: Path) -> None:
    result = verify_database(demo_dir / "pricewitness.db")
    assert result.ok is True
    assert result.warnings
