"""SQLite persistence and ingestion pipeline."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pricewitness.aliases import AliasBook, suggested_key
from pricewitness.parser import MAX_SOURCE_BYTES, ReceiptParseError, parse_receipt_text
from pricewitness.units import NormalizedAmount, parse_package_size
from pricewitness.version import __version__

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class IngestResult:
    receipt_id: int
    source_name: str
    duplicate: bool
    item_count: int
    mapped_count: int
    review_count: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_sha256 TEXT NOT NULL UNIQUE,
    merchant TEXT NOT NULL,
    purchased_at TEXT NOT NULL,
    currency TEXT NOT NULL CHECK(length(currency) = 3),
    subtotal_cents INTEGER,
    tax_cents INTEGER,
    total_cents INTEGER,
    parser_version TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipt_lines (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    kind TEXT NOT NULL,
    UNIQUE(receipt_id, line_no)
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    line_no INTEGER NOT NULL,
    raw_name TEXT NOT NULL,
    suggested_key TEXT NOT NULL,
    product_key TEXT,
    canonical_name TEXT,
    category TEXT,
    total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
    item_count TEXT NOT NULL,
    base_amount TEXT,
    base_unit TEXT,
    unit_price_micros INTEGER,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL CHECK(status IN ('mapped', 'review', 'ambiguous')),
    candidates_json TEXT NOT NULL,
    parser_rule TEXT NOT NULL,
    UNIQUE(receipt_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_observations_product ON observations(product_key);
CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(purchased_at);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize(path: str | Path) -> None:
    """Create or validate a PriceWitness database."""

    with connect(path) as connection:
        connection.executescript(_SCHEMA)
        existing = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if existing is not None and int(existing["value"]) != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported database schema {existing['value']}; expected {SCHEMA_VERSION}"
            )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('created_with', ?)",
            (__version__,),
        )


def ingest_files(
    database: str | Path,
    sources: Iterable[str | Path],
    *,
    aliases: AliasBook,
    currency: str = "USD",
) -> list[IngestResult]:
    """Ingest source text files transactionally, one receipt at a time."""

    initialize(database)
    results: list[IngestResult] = []
    for source in sources:
        results.append(ingest_file(database, source, aliases=aliases, currency=currency))
    return results


def ingest_file(
    database: str | Path,
    source: str | Path,
    *,
    aliases: AliasBook,
    currency: str = "USD",
) -> IngestResult:
    source_path = Path(source)
    try:
        payload = source_path.read_bytes()
    except OSError as exc:
        raise ReceiptParseError(f"cannot read {source_path}: {exc}") from exc
    if len(payload) > MAX_SOURCE_BYTES:
        raise ReceiptParseError(f"receipt exceeds {MAX_SOURCE_BYTES} bytes")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ReceiptParseError(f"{source_path.name} is not UTF-8 text") from exc

    source_hash = hashlib.sha256(payload).hexdigest()
    draft = parse_receipt_text(text, currency=currency)
    initialize(database)
    with connect(database) as connection:
        duplicate = connection.execute(
            "SELECT id FROM receipts WHERE source_sha256 = ?", (source_hash,)
        ).fetchone()
        if duplicate is not None:
            return _existing_result(connection, int(duplicate["id"]), source_path.name)

        cursor = connection.execute(
            """
            INSERT INTO receipts(
                source_name, source_sha256, merchant, purchased_at, currency,
                subtotal_cents, tax_cents, total_cents, parser_version, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_path.name,
                source_hash,
                draft.merchant,
                draft.purchased_at,
                draft.currency,
                draft.subtotal_cents,
                draft.tax_cents,
                draft.total_cents,
                __version__,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
            ),
        )
        if cursor.lastrowid is None:
            raise sqlite3.DatabaseError("receipt insert did not return a row id")
        receipt_id = int(cursor.lastrowid)
        connection.executemany(
            "INSERT INTO receipt_lines(receipt_id, line_no, raw_text, kind) VALUES (?, ?, ?, ?)",
            ((receipt_id, line.line_no, line.raw_text, line.kind) for line in draft.lines),
        )

        mapped_count = 0
        review_count = 0
        for item in draft.items:
            resolved = aliases.resolve(draft.merchant, item.raw_name)
            detected_package = item.measured_amount or parse_package_size(item.raw_name)
            package = detected_package or resolved.package
            base_amount = None
            base_unit = None
            unit_price_micros = None
            if package is not None:
                effective = NormalizedAmount(
                    amount=package.amount * item.item_count,
                    unit=package.unit,
                )
                base_amount = _decimal_text(effective.amount)
                base_unit = effective.unit
                unit_price_micros = _unit_price_micros(item.total_cents, effective.amount)

            if resolved.product is not None:
                mapped_count += 1
                product_key = resolved.product.key
                canonical_name = resolved.product.name
                category = resolved.product.category
            else:
                review_count += 1
                product_key = None
                canonical_name = None
                category = None

            connection.execute(
                """
                INSERT INTO observations(
                    receipt_id, line_no, raw_name, suggested_key, product_key,
                    canonical_name, category, total_cents, item_count, base_amount,
                    base_unit, unit_price_micros, confidence, status, candidates_json,
                    parser_rule
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    item.line_no,
                    item.raw_name,
                    suggested_key(item.raw_name),
                    product_key,
                    canonical_name,
                    category,
                    item.total_cents,
                    _decimal_text(item.item_count),
                    base_amount,
                    base_unit,
                    unit_price_micros,
                    resolved.confidence,
                    resolved.status,
                    json.dumps(resolved.candidates, separators=(",", ":")),
                    item.parser_rule,
                ),
            )

    return IngestResult(
        receipt_id=receipt_id,
        source_name=source_path.name,
        duplicate=False,
        item_count=len(draft.items),
        mapped_count=mapped_count,
        review_count=review_count,
    )


def rematch(database: str | Path, aliases: AliasBook) -> tuple[int, int]:
    """Reapply an alias book to every observation without changing source evidence."""

    initialize(database)
    mapped = 0
    review = 0
    with connect(database) as connection:
        rows = connection.execute(
            """
            SELECT o.id, o.raw_name, o.base_amount, o.base_unit, o.item_count,
                   o.total_cents, r.merchant
            FROM observations o JOIN receipts r ON r.id = o.receipt_id
            ORDER BY o.id
            """
        ).fetchall()
        for row in rows:
            resolved = aliases.resolve(row["merchant"], row["raw_name"])
            product_key = canonical_name = category = None
            if resolved.product is not None:
                product_key = resolved.product.key
                canonical_name = resolved.product.name
                category = resolved.product.category
                mapped += 1
            else:
                review += 1

            base_amount = row["base_amount"]
            base_unit = row["base_unit"]
            unit_price_micros = None
            if base_amount is None and resolved.package is not None:
                amount = resolved.package.amount * Decimal(row["item_count"])
                base_amount = _decimal_text(amount)
                base_unit = resolved.package.unit
            if base_amount is not None:
                unit_price_micros = _unit_price_micros(
                    int(row["total_cents"]), Decimal(base_amount)
                )

            connection.execute(
                """
                UPDATE observations SET product_key = ?, canonical_name = ?, category = ?,
                    base_amount = ?, base_unit = ?, unit_price_micros = ?, confidence = ?,
                    status = ?, candidates_json = ? WHERE id = ?
                """,
                (
                    product_key,
                    canonical_name,
                    category,
                    base_amount,
                    base_unit,
                    unit_price_micros,
                    resolved.confidence,
                    resolved.status,
                    json.dumps(resolved.candidates, separators=(",", ":")),
                    row["id"],
                ),
            )
    return mapped, review


def _existing_result(
    connection: sqlite3.Connection, receipt_id: int, source_name: str
) -> IngestResult:
    counts = connection.execute(
        """
        SELECT COUNT(*) AS item_count,
               SUM(CASE WHEN status = 'mapped' THEN 1 ELSE 0 END) AS mapped_count,
               SUM(CASE WHEN status != 'mapped' THEN 1 ELSE 0 END) AS review_count
        FROM observations WHERE receipt_id = ?
        """,
        (receipt_id,),
    ).fetchone()
    return IngestResult(
        receipt_id=receipt_id,
        source_name=source_name,
        duplicate=True,
        item_count=int(counts["item_count"] or 0),
        mapped_count=int(counts["mapped_count"] or 0),
        review_count=int(counts["review_count"] or 0),
    )


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _unit_price_micros(total_cents: int, amount: Decimal) -> int:
    if amount <= 0:
        raise ValueError("base amount must be positive")
    currency_micros = Decimal(total_cents) * Decimal("10000")
    return int((currency_micros / amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
