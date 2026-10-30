"""Typed records for the catalog, a quoting decision, and an evaluation scenario.

Loading is strict on purpose. A misspelled field or a bad status should stop the
run instead of becoming a silent pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

SpecValue = str | int

_CATALOG_KEYS = {"note", "products"}
_PRODUCT_KEYS = {"sku", "name", "summary", "stock", "specs", "substitutes_for"}
_SCENARIO_FILE_KEYS = {"note", "scenarios"}
_SCENARIO_KEYS = {
    "id",
    "description",
    "customer_request",
    "business_rules",
    "expected",
    "proposed",
    "split",
}
_SPLITS = {"baseline", "development", "heldout", "final_validation"}
_RULE_KEYS = {
    "substitution_allowed",
    "required_fields",
    "provided_specs",
    "quantity",
    "primary_sku",
}
_DECISION_KEYS = {
    "status",
    "sku",
    "quantity",
    "missing_fields",
    "substitution_used",
    "rationale",
}


class QuoteEvalError(ValueError):
    """A catalog or scenario file cannot be evaluated as written."""


class DecisionStatus(str, Enum):
    READY_TO_QUOTE = "READY_TO_QUOTE"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    summary: str
    stock: int
    specs: dict[str, SpecValue]
    substitutes_for: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    products: tuple[Product, ...]

    def __post_init__(self) -> None:
        seen: dict[str, Product] = {}
        for product in self.products:
            if product.sku in seen:
                raise QuoteEvalError(f"Duplicate SKU in catalog: {product.sku}.")
            seen[product.sku] = product
        object.__setattr__(self, "_by_sku", seen)

    def get(self, sku: str | None) -> Product | None:
        if sku is None:
            return None
        return getattr(self, "_by_sku").get(sku)

    def require(self, sku: str) -> Product:
        product = self.get(sku)
        if product is None:
            raise QuoteEvalError(f"SKU {sku} is not in the catalog.")
        return product


@dataclass(frozen=True)
class Decision:
    """A structured quote decision.

    ``rationale`` is the free-text explanation that came with a proposed answer.
    Scoring never reads it. Two decisions can use the same words and still score
    differently when the fields below differ.
    """

    status: DecisionStatus
    sku: str | None
    quantity: int | None
    missing_fields: tuple[str, ...]
    substitution_used: bool
    rationale: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing_fields", tuple(sorted(self.missing_fields)))

    def scored(self) -> tuple[object, ...]:
        return (
            self.status,
            self.sku,
            self.quantity,
            self.missing_fields,
            self.substitution_used,
        )


@dataclass(frozen=True)
class BusinessRules:
    """What the customer asked for, already extracted into fields.

    The original sentence is stored on the scenario for the report. These fields
    are what the evaluator is allowed to use.
    """

    substitution_allowed: bool
    required_fields: tuple[str, ...]
    provided_specs: dict[str, SpecValue]
    quantity: int | None
    primary_sku: str | None


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    customer_request: str
    rules: BusinessRules
    expected: Decision
    proposed: Decision
    split: str = "baseline"


def default_data_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / "catalog.json").is_file():
            return parent / "data"
    raise QuoteEvalError(
        "Could not find data/catalog.json. Pass --catalog and --scenarios, "
        "or run the tool from the project directory."
    )


def load_catalog(path: Path) -> Catalog:
    return catalog_from_obj(_read_json(path), source=str(path))


def load_scenarios(path: Path) -> tuple[Scenario, ...]:
    return scenarios_from_obj(_read_json(path), source=str(path))


def catalog_from_obj(raw: object, *, source: str = "catalog") -> Catalog:
    data = _require_mapping(raw, source)
    _reject_unknown(data, _CATALOG_KEYS, source)
    products_raw = _require_list(data.get("products"), f"{source} products")
    if not products_raw:
        raise QuoteEvalError(f"{source} does not list any products.")
    products = tuple(
        _parse_product(item, f"{source} products[{index}]")
        for index, item in enumerate(products_raw)
    )
    try:
        catalog = Catalog(products)
    except QuoteEvalError as exc:
        raise QuoteEvalError(f"{source}: {exc}") from exc
    for product in catalog.products:
        if product.sku in product.substitutes_for:
            raise QuoteEvalError(
                f"{source}: {product.sku} lists itself as a substitute."
            )
        for target in product.substitutes_for:
            if catalog.get(target) is None:
                raise QuoteEvalError(
                    f"{source}: {product.sku} claims to substitute for {target}, "
                    "which is not in the catalog."
                )
    return catalog


def scenarios_from_obj(raw: object, *, source: str = "scenarios") -> tuple[Scenario, ...]:
    data = _require_mapping(raw, source)
    _reject_unknown(data, _SCENARIO_FILE_KEYS, source)
    rows = _require_list(data.get("scenarios"), f"{source} scenarios")
    if not rows:
        raise QuoteEvalError(f"{source} does not list any scenarios.")
    scenarios = tuple(
        _parse_scenario(item, f"{source} scenarios[{index}]")
        for index, item in enumerate(rows)
    )
    seen: set[str] = set()
    for scenario in scenarios:
        if scenario.id in seen:
            raise QuoteEvalError(f"Duplicate scenario id: {scenario.id}.")
        seen.add(scenario.id)
    return scenarios


def _parse_product(raw: object, source: str) -> Product:
    data = _require_mapping(raw, source)
    _reject_unknown(data, _PRODUCT_KEYS, source)
    sku = _require_token(data.get("sku"), f"{source} sku")
    specs = _parse_specs(data.get("specs"), f"{source} specs")
    substitutes = _require_string_list(
        data.get("substitutes_for"), f"{source} substitutes_for"
    )
    return Product(
        sku=sku,
        name=_require_text(data.get("name"), f"{source} name"),
        summary=_require_text(data.get("summary"), f"{source} summary"),
        stock=_require_non_negative_int(data.get("stock"), f"{source} stock"),
        specs=specs,
        substitutes_for=tuple(substitutes),
    )


def _parse_scenario(raw: object, source: str) -> Scenario:
    data = _require_mapping(raw, source)
    _reject_unknown(data, _SCENARIO_KEYS, source)
    scenario_id = _require_token(data.get("id"), f"{source} id")
    rules = _parse_rules(data.get("business_rules"), f"{scenario_id} business_rules")
    split = data.get("split", "baseline")
    if not isinstance(split, str) or split not in _SPLITS:
        allowed = ", ".join(sorted(_SPLITS))
        raise QuoteEvalError(f"{scenario_id} split must be one of: {allowed}.")
    return Scenario(
        id=scenario_id,
        description=_require_text(data.get("description"), f"{scenario_id} description"),
        customer_request=_require_text(
            data.get("customer_request"), f"{scenario_id} customer_request"
        ),
        rules=rules,
        expected=_parse_decision(data.get("expected"), f"{scenario_id} expected"),
        proposed=_parse_decision(data.get("proposed"), f"{scenario_id} proposed"),
        split=split,
    )


def _parse_rules(raw: object, source: str) -> BusinessRules:
    data = _require_mapping(raw, source)
    _reject_unknown(data, _RULE_KEYS, source)
    required = _require_string_list(data.get("required_fields"), f"{source} required_fields")
    if not required:
        raise QuoteEvalError(f"{source} required_fields must list at least one field.")
    if len(required) != len(set(required)):
        raise QuoteEvalError(f"{source} required_fields contains a duplicate.")
    specs = _parse_specs(data.get("provided_specs"), f"{source} provided_specs")
    unknown_specs = sorted(set(specs) - set(required))
    if unknown_specs:
        raise QuoteEvalError(
            f"{source} provided_specs has {', '.join(unknown_specs)}, "
            "which is not listed in required_fields."
        )
    primary = data.get("primary_sku")
    if primary is not None:
        primary = _require_token(primary, f"{source} primary_sku")
    return BusinessRules(
        substitution_allowed=_require_bool(
            data.get("substitution_allowed"), f"{source} substitution_allowed"
        ),
        required_fields=tuple(required),
        provided_specs=specs,
        quantity=_optional_positive_int(data.get("quantity"), f"{source} quantity"),
        primary_sku=primary,
    )


def decision_from_obj(raw: object, *, source: str = "decision") -> Decision:
    """Parse one decision object. Raises QuoteEvalError when the object is invalid."""

    return _parse_decision(raw, source)


def _parse_decision(raw: object, source: str) -> Decision:
    data = _require_mapping(raw, source)
    _reject_unknown(data, _DECISION_KEYS, source)
    status_raw = data.get("status")
    if not isinstance(status_raw, str) or status_raw not in DecisionStatus._value2member_map_:
        allowed = ", ".join(status.value for status in DecisionStatus)
        raise QuoteEvalError(f"{source} status must be one of: {allowed}.")
    sku = data.get("sku")
    if sku is not None:
        sku = _require_token(sku, f"{source} sku")
    missing = _require_string_list(data.get("missing_fields"), f"{source} missing_fields")
    if len(missing) != len(set(missing)):
        raise QuoteEvalError(f"{source} missing_fields contains a duplicate.")
    rationale = data.get("rationale", "")
    if not isinstance(rationale, str):
        raise QuoteEvalError(f"{source} rationale must be a string.")
    return Decision(
        status=DecisionStatus(status_raw),
        sku=sku,
        quantity=_optional_positive_int(data.get("quantity"), f"{source} quantity"),
        missing_fields=tuple(missing),
        substitution_used=_require_bool(
            data.get("substitution_used"), f"{source} substitution_used"
        ),
        rationale=rationale,
    )


def _parse_specs(raw: object, source: str) -> dict[str, SpecValue]:
    data = _require_mapping(raw, source)
    specs: dict[str, SpecValue] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.strip() or key != key.strip():
            raise QuoteEvalError(f"{source} has an invalid spec name: {key!r}.")
        specs[key] = _parse_spec_value(value, f"{source}.{key}")
    return specs


def _parse_spec_value(value: object, source: str) -> SpecValue:
    if isinstance(value, bool) or isinstance(value, float):
        raise QuoteEvalError(
            f"{source} must be a string or an integer. Decimals and booleans are rejected "
            "so matches stay exact."
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return value
    raise QuoteEvalError(f"{source} must be a non-empty string or an integer.")


def _read_json(path: Path) -> object:
    if not path.is_file():
        raise QuoteEvalError(f"File not found: {path}.")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QuoteEvalError(f"Could not read {path}: {exc}.") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise QuoteEvalError(f"Invalid JSON in {path}: {exc.msg} (line {exc.lineno}).") from exc


def _require_mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise QuoteEvalError(f"{source} must be a JSON object.")
    return value


def _require_list(value: object, source: str) -> list[object]:
    if not isinstance(value, list):
        raise QuoteEvalError(f"{source} must be a JSON array.")
    return value


def _require_string_list(value: object, source: str) -> list[str]:
    rows = _require_list(value, source)
    parsed: list[str] = []
    for index, item in enumerate(rows):
        parsed.append(_require_token(item, f"{source}[{index}]"))
    return parsed


def _require_text(value: object, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QuoteEvalError(f"{source} must be a non-empty string.")
    return value


def _require_token(value: object, source: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise QuoteEvalError(f"{source} must be a non-empty string without surrounding space.")
    return value


def _require_bool(value: object, source: str) -> bool:
    if not isinstance(value, bool):
        raise QuoteEvalError(f"{source} must be true or false.")
    return value


def _require_non_negative_int(value: object, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QuoteEvalError(f"{source} must be an integer greater than or equal to 0.")
    return value


def _optional_positive_int(value: object, source: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise QuoteEvalError(f"{source} must be a positive integer or null.")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], source: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise QuoteEvalError(
            f"{source} has unknown fields: {', '.join(unknown)}."
        )
