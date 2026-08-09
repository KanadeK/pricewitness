from __future__ import annotations

import json
from pathlib import Path

import pytest

from pricewitness.aliases import (
    AliasBook,
    AliasConfigError,
    add_alias,
    normalize_descriptor,
    suggested_key,
)


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "products": [
            {
                "key": "oat-milk",
                "name": "Oat milk",
                "category": "dairy alternatives",
                "aliases": [
                    {"pattern": "OAT BRT 1 L", "match": "exact", "merchant": "*", "package": "1 L"},
                    {"pattern": "OAT*", "match": "glob", "merchant": "Corner Market"},
                ],
            }
        ],
    }


def test_wildcard_and_specific_alias_resolution() -> None:
    book = AliasBook.from_dict(_payload())
    wildcard = book.resolve("Other Store", "OAT BRT 1 L")
    assert wildcard.status == "mapped"
    assert wildcard.product is not None and wildcard.product.key == "oat-milk"
    assert wildcard.package is not None and str(wildcard.package.amount) == "1000"
    specific = book.resolve("Corner Market", "OAT SOMETHING")
    assert specific.status == "mapped"


def test_unmatched_alias_stays_reviewable() -> None:
    match = AliasBook.from_dict(_payload()).resolve("Shop", "MYSTERY ITEM")
    assert match.status == "review"
    assert match.product is None


def test_tied_products_are_ambiguous() -> None:
    payload = _payload()
    products = payload["products"]
    assert isinstance(products, list)
    products.append(
        {
            "key": "other-oat",
            "name": "Other oat",
            "category": "other",
            "aliases": [{"pattern": "OAT BRT 1 L", "match": "exact", "merchant": "*"}],
        }
    )
    match = AliasBook.from_dict(payload).resolve("Shop", "OAT BRT 1 L")
    assert match.status == "ambiguous"
    assert match.candidates == ("oat-milk", "other-oat")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update(schema_version=2),
        lambda payload: payload.update(products="bad"),
        lambda payload: payload["products"][0].update(key="Bad Key"),
        lambda payload: payload["products"][0]["aliases"][0].update(match="regex"),
        lambda payload: payload["products"][0]["aliases"][0].update(priority=100),
        lambda payload: payload["products"][0]["aliases"][0].update(package="huge"),
    ],
)
def test_invalid_alias_books_are_rejected(mutator: object) -> None:
    payload = _payload()
    mutator(payload)  # type: ignore[operator]
    with pytest.raises(AliasConfigError):
        AliasBook.from_dict(payload)


def test_add_alias_creates_and_updates_atomically(tmp_path: Path) -> None:
    path = tmp_path / "aliases.json"
    add_alias(
        path,
        product_key="tea",
        product_name="Black tea",
        category="pantry",
        pattern="BLK TEA 20CT",
        match_type="exact",
        merchant="*",
        package="20 ct",
    )
    assert AliasBook.from_path(path).resolve("Any", "BLK TEA 20CT").status == "mapped"
    with pytest.raises(AliasConfigError, match="already exists"):
        add_alias(
            path,
            product_key="tea",
            product_name="Black tea",
            category="pantry",
            pattern="BLK TEA 20CT",
            match_type="exact",
            merchant="*",
            package="20 ct",
        )
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_descriptor_helpers_are_deterministic() -> None:
    assert normalize_descriptor("Crème & tea") == "CRÈME AND TEA"
    assert suggested_key("Crème 250G") == "creme-250g"
