from decimal import Decimal

import pytest

from pricewitness.units import (
    canonical_unit,
    comparison_scale,
    decimal_from_text,
    normalize_amount,
    parse_package_size,
    parse_package_spec,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1.25", Decimal("1.25")), ("1,25", Decimal("1.25")), (2, Decimal("2"))],
)
def test_decimal_from_text(raw: object, expected: Decimal) -> None:
    assert decimal_from_text(raw) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["nan", "inf", "bad"])
def test_decimal_from_text_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        decimal_from_text(raw)


@pytest.mark.parametrize(
    ("amount", "unit", "expected_amount", "expected_unit"),
    [
        ("1", "kg", Decimal("1000"), "g"),
        ("2", "lb", Decimal("907.18474"), "g"),
        ("1", "L", Decimal("1000"), "ml"),
        ("12", "ct", Decimal("12"), "each"),
    ],
)
def test_normalize_amount(
    amount: str, unit: str, expected_amount: Decimal, expected_unit: str
) -> None:
    result = normalize_amount(amount, unit)
    assert result.amount == expected_amount
    assert result.unit == expected_unit


def test_normalize_amount_rejects_nonpositive_and_unknown() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_amount("0", "g")
    with pytest.raises(ValueError, match="unsupported unit"):
        canonical_unit("bucket")


def test_parse_package_size_handles_single_and_multipack() -> None:
    assert parse_package_size("PASTA 500G").amount == Decimal("500")  # type: ignore[union-attr]
    multipack = parse_package_size("YOGURT 2 x 150 g")
    assert multipack is not None
    assert multipack.amount == Decimal("300")
    assert multipack.unit == "g"
    assert parse_package_size("NO SIZE") is None


def test_parse_package_spec_requires_only_a_size() -> None:
    assert parse_package_spec("1 L").unit == "ml"
    with pytest.raises(ValueError, match="extra text"):
        parse_package_spec("bottle 1 L")
    with pytest.raises(ValueError, match="invalid package"):
        parse_package_spec("large")


def test_comparison_scales() -> None:
    assert comparison_scale("g") == (Decimal("100"), "100 g")
    assert comparison_scale("ml") == (Decimal("1000"), "1 L")
    assert comparison_scale("each") == (Decimal("1"), "each")
    with pytest.raises(ValueError):
        comparison_scale("m")
