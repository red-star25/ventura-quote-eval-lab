"""Decide whether a proposed quote matches the catalog and the labeled result.

The customer sentence and the proposed rationale are display-only. A result
passes only when every scored field is the one the catalog rules require:
status, SKU, quantity, missing information, and the substitution flag.
Guessing a missing dimension, swapping in a product the customer did not allow,
or inventing a SKU fails even if the surrounding sentence sounds right.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quote_eval.models import (
    BusinessRules,
    Catalog,
    Decision,
    DecisionStatus,
    Product,
    QuoteEvalError,
    Scenario,
    SpecValue,
    load_catalog,
    load_scenarios,
)

PASS = "PASS"
FAIL = "FAIL"

_FIELD_LABELS = {
    "length_ft": "length",
    "thickness_in": "thickness",
    "width_in": "width",
    "width_ft": "width",
    "grade": "grade",
    "species": "species",
    "model": "model",
    "quantity": "quantity",
}


@dataclass(frozen=True)
class Evaluation:
    scenario_id: str
    description: str
    customer_request: str
    outcome: str
    reasons: tuple[str, ...]
    expected: Decision
    proposed: Decision
    rules: BusinessRules


def load_validated_dataset(
    catalog_path: Path, scenarios_path: Path
) -> tuple[Catalog, tuple[Scenario, ...]]:
    catalog = load_catalog(catalog_path)
    scenarios = load_scenarios(scenarios_path)
    validate_expected_labels(scenarios, catalog)
    return catalog, scenarios


def evaluate_all(
    scenarios: tuple[Scenario, ...] | list[Scenario], catalog: Catalog
) -> tuple[Evaluation, ...]:
    return tuple(evaluate(scenario, catalog) for scenario in scenarios)


def evaluate(scenario: Scenario, catalog: Catalog) -> Evaluation:
    """Score one proposed decision.

    ``scenario.customer_request`` and ``scenario.proposed.rationale`` are copied
    onto the report and are not inputs to the comparison.
    """

    correct = correct_decision(scenario.rules, catalog)
    reasons = list(decision_problems(scenario.proposed, correct, scenario.rules, catalog))
    if scenario.expected.scored() != correct.scored():
        reasons.append(
            "The scenario's expected result does not match the catalog rules. "
            f"The label says {format_decision(scenario.expected)}; "
            f"the rules require {format_decision(correct)}."
        )
    if reasons:
        outcome = FAIL
        reported = tuple(_unique(reasons))
    else:
        outcome = PASS
        reported = (success_reason(scenario.proposed, scenario.rules, catalog),)
    return Evaluation(
        scenario_id=scenario.id,
        description=scenario.description,
        customer_request=scenario.customer_request,
        outcome=outcome,
        reasons=reported,
        expected=scenario.expected,
        proposed=scenario.proposed,
        rules=scenario.rules,
    )


def validate_expected_labels(
    scenarios: tuple[Scenario, ...] | list[Scenario], catalog: Catalog
) -> None:
    """Reject a fixture whose expected answer disagrees with the catalog rules."""

    for scenario in scenarios:
        try:
            correct = correct_decision(scenario.rules, catalog)
        except QuoteEvalError as exc:
            raise QuoteEvalError(f"{scenario.id}: {exc}") from exc
        if scenario.expected.scored() != correct.scored():
            raise QuoteEvalError(
                f"{scenario.id}: expected decision is {format_decision(scenario.expected)}; "
                f"catalog rules produce {format_decision(correct)}."
            )


def correct_decision(rules: BusinessRules, catalog: Catalog) -> Decision:
    """The only structured decision these rules allow."""

    missing = unspecified_fields(rules)
    if missing:
        return Decision(
            status=DecisionStatus.NEEDS_CLARIFICATION,
            sku=None,
            quantity=rules.quantity,
            missing_fields=missing,
            substitution_used=False,
        )

    primary = _resolve_primary(rules, catalog)
    if primary is None:
        return _review(rules)

    quantity = rules.quantity
    if quantity is None:
        return Decision(
            status=DecisionStatus.NEEDS_CLARIFICATION,
            sku=None,
            quantity=None,
            missing_fields=("quantity",),
            substitution_used=False,
        )

    if primary.stock >= quantity:
        return Decision(
            status=DecisionStatus.READY_TO_QUOTE,
            sku=primary.sku,
            quantity=quantity,
            missing_fields=(),
            substitution_used=False,
        )

    if not rules.substitution_allowed:
        return _review(rules)

    alternatives = _approved_alternatives(primary.sku, rules, catalog)
    if len(alternatives) == 1:
        return Decision(
            status=DecisionStatus.READY_TO_QUOTE,
            sku=alternatives[0].sku,
            quantity=quantity,
            missing_fields=(),
            substitution_used=True,
        )
    return _review(rules)


def decision_problems(
    proposed: Decision,
    correct: Decision,
    rules: BusinessRules,
    catalog: Catalog,
) -> tuple[str, ...]:
    """Human-readable failures. Empty when the proposed decision is acceptable."""

    if proposed.scored() == correct.scored() and _structurally_quotable(proposed, rules, catalog):
        return ()

    missing = unspecified_fields(rules)
    reasons: list[str] = []
    reasons.extend(_status_problems(proposed, correct, rules, catalog, missing))
    reasons.extend(_guess_problems(proposed, catalog, missing))
    if not missing:
        reasons.extend(_sku_problems(proposed, correct, rules, catalog))
        reasons.extend(_substitution_problems(proposed, correct, rules, catalog))
        reasons.extend(_stock_problems(proposed, catalog))
    reasons.extend(_quantity_problems(proposed, correct))
    reasons.extend(_missing_field_problems(proposed, correct))
    reasons.extend(_substitution_flag_problems(proposed, correct, rules))
    if not reasons:
        reasons.append("The proposed decision does not match the expected result.")
    return tuple(_unique(reasons))


def unspecified_fields(rules: BusinessRules) -> tuple[str, ...]:
    missing = [field for field in rules.required_fields if field not in rules.provided_specs]
    if rules.quantity is None and "quantity" not in missing:
        missing.append("quantity")
    return tuple(sorted(missing))


def matching_products(catalog: Catalog, specs: dict[str, SpecValue]) -> tuple[Product, ...]:
    if not specs:
        return ()
    return tuple(product for product in catalog.products if _product_matches(product, specs))


def format_decision(decision: Decision) -> str:
    parts = [decision.status.value]
    parts.append(f"SKU {decision.sku}" if decision.sku else "no SKU")
    parts.append(
        f"quantity {decision.quantity}" if decision.quantity is not None else "no quantity"
    )
    if decision.missing_fields:
        labels = ", ".join(field_label(field) for field in decision.missing_fields)
        parts.append(f"missing {labels}")
    if decision.substitution_used:
        parts.append("substitution used")
    return ", ".join(parts)


def field_label(name: str) -> str:
    return _FIELD_LABELS.get(name, name.replace("_", " "))


def format_spec(field: str, value: object) -> str:
    if value is None:
        return "absent"
    if field.endswith("_ft"):
        unit = "foot" if value == 1 else "feet"
        return f"{value} {unit}"
    if field.endswith("_in"):
        unit = "inch" if value == 1 else "inches"
        return f"{value} {unit}"
    return str(value)


def success_reason(decision: Decision, rules: BusinessRules, catalog: Catalog) -> str:
    if decision.status is DecisionStatus.READY_TO_QUOTE and decision.substitution_used:
        product = catalog.get(decision.sku)
        primary = catalog.get(rules.primary_sku)
        stock = product.stock if product is not None else "unknown"
        primary_stock = primary.stock if primary is not None else "unknown"
        primary_sku = rules.primary_sku or "the requested product"
        return (
            "The proposed quote matches the expected decision. "
            f"{decision.sku} is an approved substitute for {primary_sku}, "
            f"which has {primary_stock} available. The substitute matches the requested "
            f"specifications, quantity {decision.quantity} is within the {stock} in stock, "
            "and substitution was permitted because the original is unavailable."
        )
    if decision.status is DecisionStatus.READY_TO_QUOTE:
        product = catalog.get(decision.sku)
        stock = product.stock if product is not None else "unknown"
        return (
            "The proposed quote matches the expected decision. "
            f"{decision.sku} matches the requested specifications, "
            f"quantity {decision.quantity} is correct, and {stock} are available. "
            "No substitution was used."
        )
    if decision.status is DecisionStatus.NEEDS_CLARIFICATION:
        labels = _join_labels(decision.missing_fields) or "the missing detail"
        return (
            "The proposed decision matches the expected decision. "
            f"It asks the customer to clarify {labels} and does not guess a SKU."
        )
    primary = catalog.get(rules.primary_sku) if rules.primary_sku else None
    if primary is None:
        return (
            "The proposed decision matches the expected decision. "
            "No catalog product matches the request, and the decision asks for human review "
            "without inventing a SKU."
        )
    if not rules.substitution_allowed:
        return (
            "The proposed decision matches the expected decision. "
            f"{primary.sku} has {primary.stock} available and substitution is not allowed, "
            "so the decision asks for human review instead of quoting a replacement."
        )
    return (
        "The proposed decision matches the expected decision. "
        f"{primary.sku} cannot be fulfilled with a single approved in-stock substitute, "
        "so the decision asks for human review instead of guessing one."
    )


def _resolve_primary(rules: BusinessRules, catalog: Catalog) -> Product | None:
    if rules.primary_sku is not None:
        primary = catalog.get(rules.primary_sku)
        if primary is None:
            raise QuoteEvalError(f"Primary SKU {rules.primary_sku} is not in the catalog.")
        if not _product_matches(primary, rules.provided_specs):
            raise QuoteEvalError(
                f"Primary SKU {rules.primary_sku} does not match the provided specifications."
            )
        return primary
    matches = matching_products(catalog, rules.provided_specs)
    if len(matches) == 1:
        return matches[0]
    return None


def _approved_alternatives(
    primary_sku: str, rules: BusinessRules, catalog: Catalog
) -> tuple[Product, ...]:
    if rules.quantity is None:
        return ()
    found: list[Product] = []
    for product in catalog.products:
        if primary_sku not in product.substitutes_for:
            continue
        if product.stock < rules.quantity:
            continue
        if not _product_matches(product, rules.provided_specs):
            continue
        found.append(product)
    return tuple(found)


def _review(rules: BusinessRules) -> Decision:
    return Decision(
        status=DecisionStatus.NEEDS_REVIEW,
        sku=None,
        quantity=rules.quantity,
        missing_fields=(),
        substitution_used=False,
    )


def _product_matches(product: Product, specs: dict[str, SpecValue]) -> bool:
    return all(product.specs.get(key) == value for key, value in specs.items())


def _structurally_quotable(proposed: Decision, rules: BusinessRules, catalog: Catalog) -> bool:
    if proposed.status is not DecisionStatus.READY_TO_QUOTE:
        return proposed.sku is None
    if proposed.sku is None or proposed.quantity is None:
        return False
    product = catalog.get(proposed.sku)
    if product is None or proposed.quantity > product.stock:
        return False
    if unspecified_fields(rules):
        return False
    return _product_matches(product, rules.provided_specs)


def _status_problems(
    proposed: Decision,
    correct: Decision,
    rules: BusinessRules,
    catalog: Catalog,
    missing: tuple[str, ...],
) -> list[str]:
    if proposed.status is correct.status:
        return []
    sentence = f"Decision status is {proposed.status.value}; expected {correct.status.value}."
    if correct.status is DecisionStatus.NEEDS_CLARIFICATION and missing:
        sentence += (
            f" The request is missing {_join_labels(missing)}, so it cannot be quoted yet."
        )
    elif correct.status is DecisionStatus.NEEDS_REVIEW:
        sentence += _review_context(rules, catalog)
    return [sentence]


def _review_context(rules: BusinessRules, catalog: Catalog) -> str:
    matches = matching_products(catalog, rules.provided_specs)
    primary = catalog.get(rules.primary_sku) if rules.primary_sku else None
    if primary is None and not matches:
        return " No catalog product matches the request."
    if rules.primary_sku is None and len(matches) > 1:
        return " More than one catalog product fits the request, so a person needs to choose."
    if (
        primary is not None
        and rules.quantity is not None
        and primary.stock < rules.quantity
        and rules.substitution_allowed
    ):
        alternatives = _approved_alternatives(primary.sku, rules, catalog)
        if not alternatives:
            return " The requested product is out of stock and no approved substitute is available."
        names = ", ".join(product.sku for product in alternatives)
        return (
            f" More than one approved substitute is in stock ({names}), "
            "so a person needs to choose instead of guessing."
        )
    return " The order cannot be quoted as specified and needs a person to review it."


def _guess_problems(
    proposed: Decision, catalog: Catalog, missing: tuple[str, ...]
) -> list[str]:
    if not missing or proposed.sku is None:
        return []
    product = catalog.get(proposed.sku)
    assumed: list[str] = []
    for field in missing:
        if field == "quantity":
            if proposed.quantity is not None:
                assumed.append(f"quantity {proposed.quantity}")
            continue
        if product is not None and field in product.specs:
            assumed.append(f"{field_label(field)} {format_spec(field, product.specs[field])}")
        else:
            assumed.append(field_label(field))
    if product is None:
        return [
            f"The request leaves {_join_labels(missing)} unspecified. "
            f"SKU {proposed.sku} was selected anyway, and that SKU is not in the catalog."
        ]
    assumption = _join_phrases(assumed) if assumed else _join_labels(missing)
    return [
        f"SKU {proposed.sku} was selected by assuming {assumption}, "
        "which the customer did not specify."
    ]


def _sku_problems(
    proposed: Decision,
    correct: Decision,
    rules: BusinessRules,
    catalog: Catalog,
) -> list[str]:
    if proposed.sku == correct.sku:
        return []
    if proposed.sku is not None and catalog.get(proposed.sku) is None:
        return [
            f"SKU {proposed.sku} is not in the catalog. "
            "Approving a quote for it uses a fabricated product."
        ]
    if proposed.sku is None:
        return [f"No SKU was selected; expected {correct.sku}."]

    reasons: list[str] = []
    if correct.sku is None:
        reasons.append(
            f"SKU {proposed.sku} was selected, but no SKU should be chosen for this request."
        )
    else:
        reasons.append(f"SKU is {proposed.sku}; expected {correct.sku}.")
    product = catalog.get(proposed.sku)
    if product is not None:
        differences = _spec_differences(product, rules.provided_specs)
        if differences:
            reasons.append(
                f"SKU {product.sku} does not match the request: {'; '.join(differences)}."
            )
    return reasons


def _substitution_problems(
    proposed: Decision,
    correct: Decision,
    rules: BusinessRules,
    catalog: Catalog,
) -> list[str]:
    if proposed.sku is None or rules.primary_sku is None or proposed.sku == rules.primary_sku:
        return []
    if catalog.get(proposed.sku) is None:
        return []
    if not rules.substitution_allowed:
        return [
            "Substitution is not allowed, but the quote uses "
            f"{proposed.sku} instead of {rules.primary_sku}."
        ]
    product = catalog.get(proposed.sku)
    if product is None or rules.primary_sku not in product.substitutes_for:
        approved = correct.sku if correct.substitution_used else None
        suffix = f" The approved substitute is {approved}." if approved else ""
        return [f"{proposed.sku} is not an approved substitute for {rules.primary_sku}.{suffix}"]
    primary = catalog.get(rules.primary_sku)
    if (
        primary is not None
        and rules.quantity is not None
        and primary.stock >= rules.quantity
        and proposed.sku != correct.sku
    ):
        return [
            f"{rules.primary_sku} has {primary.stock} available, so a substitute should not be used."
        ]
    return []


def _stock_problems(proposed: Decision, catalog: Catalog) -> list[str]:
    if proposed.status is not DecisionStatus.READY_TO_QUOTE:
        return []
    if proposed.sku is None or proposed.quantity is None:
        return []
    product = catalog.get(proposed.sku)
    if product is None or proposed.quantity <= product.stock:
        return []
    return [
        f"{product.sku} has {product.stock} available, which is less than the quoted "
        f"quantity of {proposed.quantity}."
    ]


def _quantity_problems(proposed: Decision, correct: Decision) -> list[str]:
    if proposed.quantity == correct.quantity:
        return []
    if proposed.quantity is None:
        return [f"Quantity is missing; expected {correct.quantity}."]
    if correct.quantity is None:
        return [f"Quantity is {proposed.quantity}; expected no quantity."]
    return [f"Quantity is {proposed.quantity}; expected {correct.quantity}."]


def _missing_field_problems(proposed: Decision, correct: Decision) -> list[str]:
    if set(proposed.missing_fields) == set(correct.missing_fields):
        return []
    got = _join_labels(proposed.missing_fields) if proposed.missing_fields else "nothing"
    expected = _join_labels(correct.missing_fields) if correct.missing_fields else "nothing"
    return [f"Missing information is recorded as {got}; expected {expected}."]


def _substitution_flag_problems(
    proposed: Decision, correct: Decision, rules: BusinessRules
) -> list[str]:
    if proposed.substitution_used == correct.substitution_used or proposed.sku != correct.sku:
        return []
    if correct.substitution_used and not proposed.substitution_used:
        return [
            "The quote uses an approved substitute, but the decision does not record "
            "that a substitution was used."
        ]
    if proposed.substitution_used and not correct.substitution_used:
        if proposed.sku is not None and proposed.sku == rules.primary_sku:
            return [
                "The decision marks a substitution, but the quoted SKU is the requested product."
            ]
        return ["The decision marks a substitution, but no substitution is needed."]
    return []


def _spec_differences(product: Product, specs: dict[str, SpecValue]) -> list[str]:
    differences: list[str] = []
    for key, expected in specs.items():
        actual = product.specs.get(key)
        if actual == expected:
            continue
        differences.append(
            f"{field_label(key)} is {format_spec(key, actual)} but the request specifies "
            f"{format_spec(key, expected)}"
        )
    return differences


def _join_labels(fields: tuple[str, ...] | list[str]) -> str:
    return _join_phrases([field_label(field) for field in fields])


def _join_phrases(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _unique(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)
    return ordered
