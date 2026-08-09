"""Deterministic parser for OCR text and exported e-receipt text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from pricewitness.units import NormalizedAmount, decimal_from_text, normalize_amount

MAX_SOURCE_BYTES = 2_000_000
MAX_LINES = 10_000
MAX_LINE_LENGTH = 1_000


class ReceiptParseError(ValueError):
    """Raised when a receipt source is invalid or contains no usable lines."""


@dataclass(frozen=True, slots=True)
class ItemDraft:
    line_no: int
    raw_name: str
    total_cents: int
    item_count: Decimal
    measured_amount: NormalizedAmount | None
    stated_unit_price_cents: Decimal | None
    parser_rule: str


@dataclass(frozen=True, slots=True)
class ParsedLine:
    line_no: int
    raw_text: str
    kind: str


@dataclass(frozen=True, slots=True)
class ReceiptDraft:
    merchant: str
    purchased_at: str
    currency: str
    subtotal_cents: int | None
    tax_cents: int | None
    total_cents: int | None
    items: tuple[ItemDraft, ...]
    lines: tuple[ParsedLine, ...]


_DATE_PATTERNS = (
    re.compile(
        r"(?<!\d)(?P<year>20\d{2})[-/.](?P<month>0?[1-9]|1[0-2])[-/.](?P<day>0?[1-9]|[12]\d|3[01])(?!\d)"
    ),
    re.compile(
        r"(?<!\d)(?P<month>0?[1-9]|1[0-2])[-/.](?P<day>0?[1-9]|[12]\d|3[01])[-/.](?P<year>20\d{2})(?!\d)"
    ),
)
_MONEY_AT_END = re.compile(r"(?P<amount>[-−]?\s*(?:[$€£]\s*)?\d{1,6}(?:[,.]\d{2})-?)\s*$")
_WEIGHTED_ITEM = re.compile(
    r"^(?P<name>.+?)\s+(?P<quantity>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>kg|g|lb|lbs|oz)\s*(?:@|x)\s*[$€£]?\s*"
    r"(?P<unit_price>\d+(?:[.,]\d{2}))\s*(?:/\s*(?:kg|g|lb|lbs|oz))?\s+"
    r"[$€£]?\s*(?P<total>\d+(?:[.,]\d{2}))$",
    re.IGNORECASE,
)
_QUANTITY_ITEM = re.compile(
    r"^(?P<quantity>\d+)\s*[x×]\s*(?P<name>.+?)\s+(?:@\s*)?[$€£]?\s*"
    r"(?P<unit_price>\d+(?:[.,]\d{2}))\s+[$€£]?\s*(?P<total>\d+(?:[.,]\d{2}))$",
    re.IGNORECASE,
)
_TOTAL_LABELS = {
    "subtotal": re.compile(r"^(?:SUB\s*TOTAL|SUBTOTAL)\b", re.IGNORECASE),
    "tax": re.compile(r"^(?:TAX|GST|VAT|HST)\b", re.IGNORECASE),
    "total": re.compile(r"^(?:GRAND\s+TOTAL|AMOUNT\s+DUE|TOTAL)\b", re.IGNORECASE),
}
_ADJUSTMENT = re.compile(r"^(?:COUPON|DISCOUNT|SAVINGS?|LOYALTY|PROMO|REFUND)\b", re.IGNORECASE)
_IGNORE = re.compile(
    r"(?:THANK\s+YOU|CASHIER|REGISTER|TRANSACTION|AUTH(?:ORIZATION)?|"
    r"VISA|MASTERCARD|AMEX|CHANGE\b|BALANCE\b|CARD\s+ENDING|www\.|https?://)",
    re.IGNORECASE,
)


def money_to_cents(value: str) -> int:
    """Convert a receipt amount to integer minor units."""

    cleaned = value.strip().replace("$", "").replace("€", "").replace("£", "")
    cleaned = cleaned.replace("−", "-").replace(" ", "")
    negative_suffix = cleaned.endswith("-")
    if negative_suffix:
        cleaned = cleaned[:-1]
    amount = decimal_from_text(cleaned)
    if negative_suffix:
        amount = -amount
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_receipt_text(text: str, *, currency: str = "USD") -> ReceiptDraft:
    """Parse receipt text while preserving every source line and classification."""

    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ReceiptParseError(f"receipt exceeds {MAX_SOURCE_BYTES} bytes")
    source_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(source_lines) > MAX_LINES:
        raise ReceiptParseError(f"receipt exceeds {MAX_LINES} lines")
    if any(len(line) > MAX_LINE_LENGTH for line in source_lines):
        raise ReceiptParseError(f"receipt line exceeds {MAX_LINE_LENGTH} characters")

    nonempty = [
        (index + 1, line.strip()) for index, line in enumerate(source_lines) if line.strip()
    ]
    if not nonempty:
        raise ReceiptParseError("receipt contains no text")

    purchased_at = _find_date(nonempty)
    merchant = _find_merchant(nonempty)
    detected_currency = _detect_currency(text, currency)
    totals: dict[str, int | None] = {"subtotal": None, "tax": None, "total": None}
    items: list[ItemDraft] = []
    parsed_lines: list[ParsedLine] = []

    for line_no, line in nonempty:
        total_kind = _total_kind(line)
        if total_kind:
            amount_match = _MONEY_AT_END.search(line)
            if amount_match:
                totals[total_kind] = money_to_cents(amount_match.group("amount"))
            parsed_lines.append(ParsedLine(line_no, line, total_kind))
            continue
        if _ADJUSTMENT.search(line):
            parsed_lines.append(ParsedLine(line_no, line, "adjustment"))
            continue

        item = _parse_item(line_no, line)
        if item is not None:
            items.append(item)
            parsed_lines.append(ParsedLine(line_no, line, "item"))
            continue

        kind = "metadata" if _looks_like_metadata(line, purchased_at, merchant) else "unparsed"
        parsed_lines.append(ParsedLine(line_no, line, kind))

    if not items:
        raise ReceiptParseError("receipt contains no recognizable line items")
    return ReceiptDraft(
        merchant=merchant,
        purchased_at=purchased_at,
        currency=detected_currency,
        subtotal_cents=totals["subtotal"],
        tax_cents=totals["tax"],
        total_cents=totals["total"],
        items=tuple(items),
        lines=tuple(parsed_lines),
    )


def _parse_item(line_no: int, line: str) -> ItemDraft | None:
    quantity = _QUANTITY_ITEM.fullmatch(line)
    if quantity:
        return ItemDraft(
            line_no=line_no,
            raw_name=quantity.group("name").strip(),
            total_cents=money_to_cents(quantity.group("total")),
            item_count=Decimal(quantity.group("quantity")),
            measured_amount=None,
            stated_unit_price_cents=decimal_from_text(quantity.group("unit_price")) * 100,
            parser_rule="quantity",
        )

    weighted = _WEIGHTED_ITEM.fullmatch(line)
    if weighted:
        measured = normalize_amount(weighted.group("quantity"), weighted.group("unit"))
        return ItemDraft(
            line_no=line_no,
            raw_name=weighted.group("name").strip(),
            total_cents=money_to_cents(weighted.group("total")),
            item_count=Decimal("1"),
            measured_amount=measured,
            stated_unit_price_cents=decimal_from_text(weighted.group("unit_price")) * 100,
            parser_rule="weighted",
        )

    amount_match = _MONEY_AT_END.search(line)
    if amount_match is None or _IGNORE.search(line):
        return None
    raw_name = line[: amount_match.start()].strip(" .:-\t")
    if not raw_name or not any(character.isalpha() for character in raw_name):
        return None
    amount = money_to_cents(amount_match.group("amount"))
    if amount < 0:
        return None
    return ItemDraft(
        line_no=line_no,
        raw_name=raw_name,
        total_cents=amount,
        item_count=Decimal("1"),
        measured_amount=None,
        stated_unit_price_cents=None,
        parser_rule="simple",
    )


def _find_date(lines: list[tuple[int, str]]) -> str:
    for _, line in lines:
        for pattern in _DATE_PATTERNS:
            match = pattern.search(line)
            if match:
                try:
                    parsed = date(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    )
                except ValueError:
                    continue
                return parsed.isoformat()
    return datetime.now().astimezone().date().isoformat()


def _find_merchant(lines: list[tuple[int, str]]) -> str:
    for _, line in lines[:8]:
        if any(pattern.search(line) for pattern in _DATE_PATTERNS):
            continue
        if _TOTAL_LABELS["total"].search(line) or _IGNORE.search(line):
            continue
        if _MONEY_AT_END.search(line):
            continue
        return line[:120]
    return "Unknown merchant"


def _detect_currency(text: str, fallback: str) -> str:
    if "€" in text:
        return "EUR"
    if "£" in text:
        return "GBP"
    if "$" in text:
        return fallback.upper()
    candidate = fallback.upper().strip()
    if not re.fullmatch(r"[A-Z]{3}", candidate):
        raise ReceiptParseError("currency must be a three-letter code")
    return candidate


def _total_kind(line: str) -> str | None:
    for kind, pattern in _TOTAL_LABELS.items():
        if pattern.search(line):
            return kind
    return None


def _looks_like_metadata(line: str, purchased_at: str, merchant: str) -> bool:
    return (
        line == merchant
        or purchased_at in line
        or any(pattern.search(line) for pattern in _DATE_PATTERNS)
        or bool(_IGNORE.search(line))
    )
