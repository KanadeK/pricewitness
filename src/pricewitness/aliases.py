"""Validated product aliases for terse and inconsistent receipt descriptions."""

from __future__ import annotations

import fnmatch
import json
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pricewitness.units import NormalizedAmount, parse_package_spec

SCHEMA_VERSION = 1
_KEY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_MATCH_TYPES = {"exact", "contains", "glob"}


class AliasConfigError(ValueError):
    """Raised when an alias configuration is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class Product:
    key: str
    name: str
    category: str


@dataclass(frozen=True, slots=True)
class AliasRule:
    product: Product
    pattern: str
    match: str
    merchant: str
    package: NormalizedAmount | None
    priority: int


@dataclass(frozen=True, slots=True)
class AliasMatch:
    product: Product | None
    package: NormalizedAmount | None
    confidence: float
    status: str
    candidates: tuple[str, ...]


def normalize_descriptor(text: str) -> str:
    """Normalize receipt shorthand without hiding the original evidence."""

    normalized = unicodedata.normalize("NFKC", text).upper()
    normalized = normalized.replace("&", " AND ")
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def suggested_key(text: str) -> str:
    """Create a deterministic suggestion for an unmapped descriptor."""

    normalized = unicodedata.normalize("NFKD", normalize_descriptor(text))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    tokens = [token for token in re.findall(r"[a-z0-9]+", ascii_text) if not token.isdigit()]
    stem = "-".join(tokens[:8]).strip("-") or "unmapped-item"
    return stem[:64].rstrip("-")


class AliasBook:
    """Immutable, validated alias rules loaded from a JSON file."""

    def __init__(self, products: tuple[Product, ...], rules: tuple[AliasRule, ...]) -> None:
        self.products = products
        self.rules = rules

    @classmethod
    def empty(cls) -> AliasBook:
        return cls((), ())

    @classmethod
    def from_path(cls, path: str | Path | None) -> AliasBook:
        if path is None:
            return cls.empty()
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AliasConfigError(f"cannot read alias file {source}: {exc}") from exc
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Any) -> AliasBook:
        if not isinstance(payload, dict):
            raise AliasConfigError("alias file must contain a JSON object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise AliasConfigError(f"schema_version must be {SCHEMA_VERSION}")
        raw_products = payload.get("products")
        if not isinstance(raw_products, list):
            raise AliasConfigError("products must be a list")

        products: list[Product] = []
        rules: list[AliasRule] = []
        seen_keys: set[str] = set()
        for raw_product in raw_products:
            if not isinstance(raw_product, dict):
                raise AliasConfigError("each product must be an object")
            key = _bounded_text(raw_product.get("key"), "product key", 64)
            if not _KEY_RE.fullmatch(key):
                raise AliasConfigError(f"invalid product key: {key!r}")
            if key in seen_keys:
                raise AliasConfigError(f"duplicate product key: {key}")
            seen_keys.add(key)
            product = Product(
                key=key,
                name=_bounded_text(raw_product.get("name"), f"name for {key}", 120),
                category=_bounded_text(
                    raw_product.get("category", "uncategorized"), "category", 80
                ),
            )
            products.append(product)

            raw_aliases = raw_product.get("aliases")
            if not isinstance(raw_aliases, list) or not raw_aliases:
                raise AliasConfigError(f"product {key} must define at least one alias")
            for raw_alias in raw_aliases:
                rules.append(_parse_rule(product, raw_alias))

        return cls(tuple(products), tuple(rules))

    def resolve(self, merchant: str, descriptor: str) -> AliasMatch:
        """Resolve a descriptor and surface ties instead of guessing."""

        candidate_text = normalize_descriptor(descriptor)
        merchant_text = normalize_descriptor(merchant)
        ranked: list[tuple[int, AliasRule]] = []
        for rule in self.rules:
            wildcard_merchant = rule.merchant == "*"
            rule_merchant = "*" if wildcard_merchant else normalize_descriptor(rule.merchant)
            if not wildcard_merchant and rule_merchant != merchant_text:
                continue
            pattern = _normalize_pattern(rule.pattern, rule.match)
            matched = (
                (rule.match == "exact" and candidate_text == pattern)
                or (rule.match == "contains" and pattern in candidate_text)
                or (rule.match == "glob" and fnmatch.fnmatchcase(candidate_text, pattern))
            )
            if not matched:
                continue
            match_score = {"exact": 300, "contains": 200, "glob": 100}[rule.match]
            merchant_score = 50 if not wildcard_merchant else 0
            ranked.append((match_score + merchant_score + rule.priority, rule))

        if not ranked:
            return AliasMatch(None, None, 0.0, "review", ())

        ranked.sort(key=lambda item: (-item[0], item[1].product.key, item[1].pattern))
        best_score = ranked[0][0]
        best = [rule for score, rule in ranked if score == best_score]
        product_keys = tuple(sorted({rule.product.key for rule in best}))
        if len(product_keys) > 1:
            return AliasMatch(None, None, 0.0, "ambiguous", product_keys)

        rule = best[0]
        base_confidence = {"exact": 1.0, "contains": 0.9, "glob": 0.8}[rule.match]
        return AliasMatch(rule.product, rule.package, base_confidence, "mapped", product_keys)


def _bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AliasConfigError(f"{label} must be a non-empty string")
    stripped = value.strip()
    if len(stripped) > maximum:
        raise AliasConfigError(f"{label} exceeds {maximum} characters")
    return stripped


def _normalize_pattern(pattern: str, match_type: str) -> str:
    if match_type != "glob":
        return normalize_descriptor(pattern)
    normalized = unicodedata.normalize("NFKC", pattern).upper().replace("&", " AND ")
    normalized = re.sub(r"[^\w*?]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _parse_rule(product: Product, raw_alias: Any) -> AliasRule:
    if not isinstance(raw_alias, dict):
        raise AliasConfigError(f"alias for {product.key} must be an object")
    match_type = raw_alias.get("match", "exact")
    if match_type not in _MATCH_TYPES:
        raise AliasConfigError(f"unsupported alias match type: {match_type!r}")
    pattern = _bounded_text(raw_alias.get("pattern"), f"alias pattern for {product.key}", 120)
    merchant = _bounded_text(raw_alias.get("merchant", "*"), "merchant", 120)
    raw_priority = raw_alias.get("priority", 0)
    if isinstance(raw_priority, bool) or not isinstance(raw_priority, int):
        raise AliasConfigError("alias priority must be an integer")
    if not -50 <= raw_priority <= 50:
        raise AliasConfigError("alias priority must be between -50 and 50")
    raw_package = raw_alias.get("package")
    package = None
    if raw_package is not None:
        try:
            package = parse_package_spec(_bounded_text(raw_package, "package", 40))
        except ValueError as exc:
            raise AliasConfigError(str(exc)) from exc
    return AliasRule(product, pattern, match_type, merchant, package, raw_priority)


def add_alias(
    path: str | Path,
    *,
    product_key: str,
    product_name: str,
    category: str,
    pattern: str,
    match_type: str,
    merchant: str,
    package: str | None,
) -> None:
    """Atomically append a validated alias rule to a JSON alias book."""

    destination = Path(path)
    if destination.exists():
        payload: dict[str, Any] = json.loads(destination.read_text(encoding="utf-8"))
    else:
        payload = {"schema_version": SCHEMA_VERSION, "products": []}
    products = payload.setdefault("products", [])
    if not isinstance(products, list):
        raise AliasConfigError("products must be a list")

    product = next(
        (
            entry
            for entry in products
            if isinstance(entry, dict) and entry.get("key") == product_key
        ),
        None,
    )
    if product is None:
        product = {
            "key": product_key,
            "name": product_name,
            "category": category,
            "aliases": [],
        }
        products.append(product)
    aliases = product.setdefault("aliases", [])
    if not isinstance(aliases, list):
        raise AliasConfigError(f"aliases for {product_key} must be a list")
    new_rule: dict[str, Any] = {
        "pattern": pattern,
        "match": match_type,
        "merchant": merchant,
    }
    if package:
        new_rule["package"] = package
    if new_rule in aliases:
        raise AliasConfigError("that alias rule already exists")
    aliases.append(new_rule)

    products.sort(key=lambda entry: str(entry.get("key", "")) if isinstance(entry, dict) else "")
    AliasBook.from_dict(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=destination.parent
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(destination)
