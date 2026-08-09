"""Database, evidence hash, and arithmetic verification."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pricewitness.db import SCHEMA_VERSION, connect


@dataclass(frozen=True, slots=True)
class Verification:
    ok: bool
    checks: tuple[str, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": list(self.checks),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def verify_database(database: str | Path, sources: Iterable[str | Path] = ()) -> Verification:
    """Verify SQLite integrity, stored calculations, and optional original files."""

    path = Path(database)
    if not path.is_file():
        return Verification(False, (), (f"database not found: {path}",), ())

    checks: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    with connect(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity == "ok":
            checks.append("sqlite-integrity")
        else:
            errors.append(f"SQLite integrity check failed: {integrity}")

        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if not foreign_keys:
            checks.append("foreign-keys")
        else:
            errors.append(f"foreign key violations: {len(foreign_keys)}")

        schema = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if schema is not None and int(schema["value"]) == SCHEMA_VERSION:
            checks.append("schema-version")
        else:
            errors.append("database schema version is missing or unsupported")

        receipts = connection.execute("SELECT * FROM receipts ORDER BY id").fetchall()
        observations = connection.execute("SELECT * FROM observations ORDER BY id").fetchall()
        hashes = [row["source_sha256"] for row in receipts]
        if len(hashes) == len(set(hashes)) and all(
            re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes
        ):
            checks.append("source-hash-index")
        else:
            errors.append("source hashes are duplicated or malformed")

        arithmetic_errors = 0
        for row in observations:
            if row["base_amount"] is None or row["unit_price_micros"] is None:
                continue
            amount = Decimal(row["base_amount"])
            expected = int(
                (Decimal(row["total_cents"]) * Decimal("10000") / amount).quantize(Decimal("1"))
            )
            if abs(expected - int(row["unit_price_micros"])) > 1:
                arithmetic_errors += 1
        if arithmetic_errors:
            errors.append(f"unit-price arithmetic mismatches: {arithmetic_errors}")
        else:
            checks.append("unit-price-arithmetic")

        for receipt in receipts:
            if (
                receipt["subtotal_cents"] is not None
                and receipt["tax_cents"] is not None
                and receipt["total_cents"] is not None
            ):
                delta = abs(
                    receipt["subtotal_cents"] + receipt["tax_cents"] - receipt["total_cents"]
                )
                if delta > 1:
                    warnings.append(
                        f"{receipt['source_name']}: subtotal + tax differs from total "
                        f"by {delta} cents"
                    )
        checks.append("receipt-total-review")

        source_by_name: dict[str, list[Path]] = {}
        for source in sources:
            source_path = Path(source)
            source_by_name.setdefault(source_path.name, []).append(source_path)
        if source_by_name:
            evidence_errors = 0
            for receipt in receipts:
                matches = source_by_name.get(receipt["source_name"], [])
                if len(matches) != 1:
                    evidence_errors += 1
                    errors.append(
                        f"expected one source named {receipt['source_name']}, found {len(matches)}"
                    )
                    continue
                try:
                    digest = hashlib.sha256(matches[0].read_bytes()).hexdigest()
                except OSError as exc:
                    evidence_errors += 1
                    errors.append(f"cannot read {matches[0]}: {exc}")
                    continue
                if digest != receipt["source_sha256"]:
                    evidence_errors += 1
                    errors.append(f"source hash mismatch: {matches[0]}")
            if evidence_errors == 0:
                checks.append("original-source-hashes")
        else:
            warnings.append(
                "original source hashes were not rechecked; pass source paths to verify them"
            )

    return Verification(not errors, tuple(checks), tuple(errors), tuple(warnings))
