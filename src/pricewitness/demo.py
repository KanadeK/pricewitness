"""Create a complete synthetic demo without network or cloud services."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from pricewitness.aliases import AliasBook
from pricewitness.analysis import write_analysis_json
from pricewitness.db import ingest_files, initialize
from pricewitness.exporter import export_csv
from pricewitness.report import write_report

_RESOURCE_NAMES = (
    "aliases.json",
    "receipt-2026-01-12.txt",
    "receipt-2026-03-18.txt",
    "receipt-2026-07-30.txt",
)


def create_demo(output: str | Path) -> dict[str, object]:
    destination = Path(output)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"demo output directory is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    receipts_dir = destination / "receipts"
    receipts_dir.mkdir(exist_ok=True)

    package_files = resources.files("pricewitness").joinpath("demo_data")
    for name in _RESOURCE_NAMES:
        target = destination / name if name == "aliases.json" else receipts_dir / name
        target.write_bytes(package_files.joinpath(name).read_bytes())

    database = destination / "pricewitness.db"
    aliases_path = destination / "aliases.json"
    sources = sorted(receipts_dir.glob("*.txt"))
    initialize(database)
    results = ingest_files(database, sources, aliases=AliasBook.from_path(aliases_path))
    analysis_path = destination / "analysis.json"
    report_path = destination / "report.html"
    csv_path = destination / "observations.csv"
    document = write_analysis_json(database, analysis_path)
    write_report(database, report_path)
    export_csv(database, csv_path)
    manifest = {
        "database": database.name,
        "analysis": analysis_path.name,
        "report": report_path.name,
        "export": csv_path.name,
        "receipts": [path.name for path in sources],
        "ingested": [
            result.__dict__
            if hasattr(result, "__dict__")
            else {
                "source_name": result.source_name,
                "receipt_id": result.receipt_id,
                "item_count": result.item_count,
                "mapped_count": result.mapped_count,
                "review_count": result.review_count,
                "duplicate": result.duplicate,
            }
            for result in results
        ],
        "summary": document["summary"],
    }
    (destination / "demo-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest
