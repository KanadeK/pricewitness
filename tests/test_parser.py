from decimal import Decimal

import pytest

from pricewitness.parser import ReceiptParseError, money_to_cents, parse_receipt_text

RECEIPT = """Corner Market
2026-04-05
MILK 1L $2.99
APPLES 1.25 KG @ 2.40/KG $3.00
2 x PASTA 500 G @ $1.50 $3.00
DISCOUNT -$0.50
SUBTOTAL $8.99
TAX $0.00
TOTAL $8.99
VISA ENDING 1111
"""


def test_parse_receipt_covers_simple_weighted_and_quantity() -> None:
    result = parse_receipt_text(RECEIPT)
    assert result.merchant == "Corner Market"
    assert result.purchased_at == "2026-04-05"
    assert result.currency == "USD"
    assert result.total_cents == 899
    assert [item.parser_rule for item in result.items] == ["simple", "weighted", "quantity"]
    assert result.items[1].measured_amount is not None
    assert result.items[1].measured_amount.amount == Decimal("1250")
    assert result.items[2].raw_name == "PASTA 500 G"
    assert result.items[2].item_count == Decimal("2")
    assert {line.kind for line in result.lines} >= {"item", "adjustment", "total", "metadata"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("$1.25", 125), ("1,25", 125), ("-$0.50", -50), ("0.99-", -99)],
)
def test_money_to_cents(raw: str, expected: int) -> None:
    assert money_to_cents(raw) == expected


def test_currency_and_us_date_detection() -> None:
    result = parse_receipt_text("Shop\n04/06/2026\nTEA 20CT €4.50\nTOTAL €4.50")
    assert result.currency == "EUR"
    assert result.purchased_at == "2026-04-06"


def test_fallback_currency_validation() -> None:
    with pytest.raises(ReceiptParseError, match="three-letter"):
        parse_receipt_text("Shop\n2026-01-01\nTEA 4.50", currency="US")


@pytest.mark.parametrize("text", ["", "Shop\n2026-01-01\nTHANK YOU"])
def test_parse_receipt_rejects_no_items(text: str) -> None:
    with pytest.raises(ReceiptParseError):
        parse_receipt_text(text)


def test_parse_receipt_rejects_long_line() -> None:
    with pytest.raises(ReceiptParseError, match="line exceeds"):
        parse_receipt_text("X" * 1001 + " $1.00")


def test_invalid_calendar_date_is_not_accepted() -> None:
    result = parse_receipt_text("Shop\n2026-02-31\nTEA $1.00")
    assert result.purchased_at != "2026-02-31"
