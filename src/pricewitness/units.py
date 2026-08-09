"""Package-size parsing and deterministic unit normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class NormalizedAmount:
    """A quantity expressed in the comparison base unit."""

    amount: Decimal
    unit: str


_UNIT_ALIASES = {
    "g": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "oz": "oz",
    "ounce": "oz",
    "ounces": "oz",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "ml": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "cl": "cl",
    "l": "l",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "fl oz": "floz",
    "floz": "floz",
    "ct": "each",
    "count": "each",
    "ea": "each",
    "each": "each",
    "pc": "each",
    "pcs": "each",
    "pack": "each",
}

_FACTORS: dict[str, tuple[str, Decimal]] = {
    "g": ("g", Decimal("1")),
    "kg": ("g", Decimal("1000")),
    "oz": ("g", Decimal("28.349523125")),
    "lb": ("g", Decimal("453.59237")),
    "ml": ("ml", Decimal("1")),
    "cl": ("ml", Decimal("10")),
    "l": ("ml", Decimal("1000")),
    "floz": ("ml", Decimal("29.5735295625")),
    "each": ("each", Decimal("1")),
}

_UNIT_PATTERN = (
    r"kg|kilograms?|g|grams?|lbs?|pounds?|oz|ounces?|"
    r"ml|millilit(?:er|re)s?|cl|l|lit(?:er|re)s?|fl\s*oz|floz|"
    r"ct|count|ea|each|pcs?|pack"
)

_MULTIPACK_RE = re.compile(
    rf"(?<!\w)(?P<count>\d+)\s*[x×]\s*(?P<amount>\d+(?:[.,]\d+)?)\s*"
    rf"(?P<unit>{_UNIT_PATTERN})(?!\w)",
    re.IGNORECASE,
)
_SIZE_RE = re.compile(
    rf"(?<![\w.])(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>{_UNIT_PATTERN})(?!\w)",
    re.IGNORECASE,
)


def decimal_from_text(value: str | int | float | Decimal) -> Decimal:
    """Parse a decimal using a conservative comma/dot rule."""

    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        text = text.replace(",", "")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"non-finite decimal value: {value!r}")
    return parsed


def canonical_unit(unit: str) -> str:
    """Return the canonical spelling of a supported unit."""

    compact = re.sub(r"\s+", " ", unit.strip().lower())
    if compact == "fl oz":
        compact = "floz"
    try:
        return _UNIT_ALIASES[compact]
    except KeyError as exc:
        raise ValueError(f"unsupported unit: {unit!r}") from exc


def normalize_amount(amount: str | int | float | Decimal, unit: str) -> NormalizedAmount:
    """Convert a supported measurement to grams, millilitres, or each."""

    parsed = decimal_from_text(amount)
    if parsed <= 0:
        raise ValueError("amount must be greater than zero")
    canonical = canonical_unit(unit)
    base_unit, factor = _FACTORS[canonical]
    return NormalizedAmount(amount=parsed * factor, unit=base_unit)


def parse_package_size(text: str) -> NormalizedAmount | None:
    """Extract a package size, including forms such as ``2 x 500 g``."""

    multipack = _MULTIPACK_RE.search(text)
    if multipack:
        normalized = normalize_amount(multipack.group("amount"), multipack.group("unit"))
        return NormalizedAmount(
            amount=normalized.amount * Decimal(multipack.group("count")),
            unit=normalized.unit,
        )

    matches = list(_SIZE_RE.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    return normalize_amount(match.group("amount"), match.group("unit"))


def parse_package_spec(spec: str) -> NormalizedAmount:
    """Parse an alias package specification and require a complete match."""

    stripped = spec.strip()
    parsed = parse_package_size(stripped)
    if parsed is None:
        raise ValueError(f"invalid package specification: {spec!r}")
    multipack = _MULTIPACK_RE.fullmatch(stripped)
    single = _SIZE_RE.fullmatch(stripped)
    if multipack is None and single is None:
        raise ValueError(f"package specification contains extra text: {spec!r}")
    return parsed


def comparison_scale(base_unit: str) -> tuple[Decimal, str]:
    """Return a human-readable price comparison scale."""

    if base_unit == "g":
        return Decimal("100"), "100 g"
    if base_unit == "ml":
        return Decimal("1000"), "1 L"
    if base_unit == "each":
        return Decimal("1"), "each"
    raise ValueError(f"unsupported base unit: {base_unit!r}")
