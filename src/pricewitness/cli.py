"""Command-line interface for the complete PriceWitness workflow."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from pricewitness.aliases import AliasBook, AliasConfigError, add_alias
from pricewitness.analysis import analyze, write_analysis_json
from pricewitness.db import ingest_files, initialize, rematch
from pricewitness.demo import create_demo
from pricewitness.exporter import export_csv
from pricewitness.parser import ReceiptParseError
from pricewitness.report import write_report
from pricewitness.verify import verify_database
from pricewitness.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pricewitness",
        description="Turn grocery receipt text into an auditable unit-price history.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize an empty SQLite ledger")
    init_parser.add_argument("database", type=Path)
    init_parser.set_defaults(handler=_handle_init)

    ingest_parser = subparsers.add_parser("ingest", help="ingest UTF-8 receipt text files")
    ingest_parser.add_argument("database", type=Path)
    ingest_parser.add_argument("sources", nargs="+", type=Path)
    ingest_parser.add_argument("--aliases", type=Path)
    ingest_parser.add_argument("--currency", default="USD")
    ingest_parser.set_defaults(handler=_handle_ingest)

    rematch_parser = subparsers.add_parser("rematch", help="reapply aliases to stored evidence")
    rematch_parser.add_argument("database", type=Path)
    rematch_parser.add_argument("--aliases", required=True, type=Path)
    rematch_parser.set_defaults(handler=_handle_rematch)

    analyze_parser = subparsers.add_parser("analyze", help="emit deterministic analysis JSON")
    _add_analysis_arguments(analyze_parser)
    analyze_parser.add_argument("--output", type=Path)
    analyze_parser.set_defaults(handler=_handle_analyze)

    report_parser = subparsers.add_parser("report", help="build a self-contained HTML report")
    _add_analysis_arguments(report_parser)
    report_parser.add_argument("--output", required=True, type=Path)
    report_parser.set_defaults(handler=_handle_report)

    export_parser = subparsers.add_parser("export", help="export normalized observations as CSV")
    export_parser.add_argument("database", type=Path)
    export_parser.add_argument("--output", required=True, type=Path)
    export_parser.set_defaults(handler=_handle_export)

    verify_parser = subparsers.add_parser("verify", help="verify database and source evidence")
    verify_parser.add_argument("database", type=Path)
    verify_parser.add_argument("sources", nargs="*", type=Path)
    verify_parser.set_defaults(handler=_handle_verify)

    demo_parser = subparsers.add_parser("demo", help="create a runnable synthetic demonstration")
    demo_parser.add_argument("--output", required=True, type=Path)
    demo_parser.set_defaults(handler=_handle_demo)

    aliases_parser = subparsers.add_parser("aliases", help="validate or extend an alias book")
    aliases_subparsers = aliases_parser.add_subparsers(dest="aliases_command", required=True)
    validate_parser = aliases_subparsers.add_parser("validate", help="validate alias JSON")
    validate_parser.add_argument("file", type=Path)
    validate_parser.set_defaults(handler=_handle_alias_validate)
    add_parser = aliases_subparsers.add_parser("add", help="atomically add an alias rule")
    add_parser.add_argument("file", type=Path)
    add_parser.add_argument("--product-key", required=True)
    add_parser.add_argument("--product-name", required=True)
    add_parser.add_argument("--category", default="uncategorized")
    add_parser.add_argument("--pattern", required=True)
    add_parser.add_argument("--match", choices=("exact", "contains", "glob"), default="exact")
    add_parser.add_argument("--merchant", default="*")
    add_parser.add_argument("--package")
    add_parser.set_defaults(handler=_handle_alias_add)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except (AliasConfigError, ReceiptParseError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"pricewitness: {exc}", file=sys.stderr)
        return 2


def _add_analysis_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("database", type=Path)
    parser.add_argument("--spike-threshold", type=float, default=10.0)
    parser.add_argument("--shrink-threshold", type=float, default=5.0)


def _handle_init(arguments: argparse.Namespace) -> int:
    initialize(arguments.database)
    _print_json({"ok": True, "database": str(arguments.database)})
    return 0


def _handle_ingest(arguments: argparse.Namespace) -> int:
    aliases = AliasBook.from_path(arguments.aliases)
    results = ingest_files(
        arguments.database,
        arguments.sources,
        aliases=aliases,
        currency=arguments.currency,
    )
    _print_json(
        {
            "ok": True,
            "receipts": [
                {
                    "receipt_id": result.receipt_id,
                    "source": result.source_name,
                    "duplicate": result.duplicate,
                    "items": result.item_count,
                    "mapped": result.mapped_count,
                    "review": result.review_count,
                }
                for result in results
            ],
        }
    )
    return 0


def _handle_rematch(arguments: argparse.Namespace) -> int:
    mapped, review = rematch(arguments.database, AliasBook.from_path(arguments.aliases))
    _print_json({"ok": True, "mapped": mapped, "review": review})
    return 0


def _handle_analyze(arguments: argparse.Namespace) -> int:
    if arguments.output:
        document = write_analysis_json(
            arguments.database,
            arguments.output,
            spike_threshold=arguments.spike_threshold,
            shrink_threshold=arguments.shrink_threshold,
        )
    else:
        document = analyze(
            arguments.database,
            spike_threshold=arguments.spike_threshold,
            shrink_threshold=arguments.shrink_threshold,
        )
    _print_json(document)
    return 0


def _handle_report(arguments: argparse.Namespace) -> int:
    document = write_report(
        arguments.database,
        arguments.output,
        spike_threshold=arguments.spike_threshold,
        shrink_threshold=arguments.shrink_threshold,
    )
    _print_json({"ok": True, "output": str(arguments.output), "summary": document["summary"]})
    return 0


def _handle_export(arguments: argparse.Namespace) -> int:
    count = export_csv(arguments.database, arguments.output)
    _print_json({"ok": True, "output": str(arguments.output), "observations": count})
    return 0


def _handle_verify(arguments: argparse.Namespace) -> int:
    verification = verify_database(arguments.database, arguments.sources)
    _print_json(verification.to_dict())
    return 0 if verification.ok else 1


def _handle_demo(arguments: argparse.Namespace) -> int:
    _print_json({"ok": True, **create_demo(arguments.output)})
    return 0


def _handle_alias_validate(arguments: argparse.Namespace) -> int:
    book = AliasBook.from_path(arguments.file)
    _print_json({"ok": True, "products": len(book.products), "rules": len(book.rules)})
    return 0


def _handle_alias_add(arguments: argparse.Namespace) -> int:
    add_alias(
        arguments.file,
        product_key=arguments.product_key,
        product_name=arguments.product_name,
        category=arguments.category,
        pattern=arguments.pattern,
        match_type=arguments.match,
        merchant=arguments.merchant,
        package=arguments.package,
    )
    book = AliasBook.from_path(arguments.file)
    _print_json({"ok": True, "products": len(book.products), "rules": len(book.rules)})
    return 0


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
