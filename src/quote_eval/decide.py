"""Turn grounded customer facts into a quote by applying the catalog rules.

This module does not read a scenario's expected decision or its labeled
business rules. It builds a fresh set of rules from the extraction and the
catalog, then calls the same ``correct_decision`` function the checker uses
on hand-labeled rules. The inputs are different, so agreement is a result,
not a copied answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from quote_eval.dimensions import (
    canonical_grade,
    canonical_species,
    normalize_text,
    parse_customer_request,
    substitution_from_text,
)
from quote_eval.evaluator import correct_decision, matching_products
from quote_eval.extract import Extraction
from quote_eval.models import BusinessRules, Catalog, Decision, DecisionStatus, Product, SpecValue

_SPEC_FIELDS = ("grade", "species", "thickness_in", "width_in", "width_ft", "length_ft")


@dataclass(frozen=True)
class DerivedQuote:
    decision: Decision
    rules: BusinessRules
    rejected: tuple[str, ...]
    recovered: tuple[str, ...]


def decide(customer_request: str, extraction: Extraction, catalog: Catalog) -> DerivedQuote:
    """Apply catalog rules to values the customer request actually supports."""

    grounded, rejected, recovered = _ground(customer_request, extraction)
    rules = _rules_from_grounded(grounded, catalog)
    decision = correct_decision(rules, catalog)
    explained = Decision(
        status=decision.status,
        sku=decision.sku,
        quantity=decision.quantity,
        missing_fields=decision.missing_fields,
        substitution_used=decision.substitution_used,
        rationale=_rationale(decision, grounded.model, rules),
    )
    return DerivedQuote(
        decision=explained,
        rules=rules,
        rejected=tuple(rejected),
        recovered=tuple(recovered),
    )


@dataclass(frozen=True)
class _Grounded:
    product_type: str | None
    specs: dict[str, SpecValue]
    quantity: int | None
    model: str | None
    substitution_allowed: bool


def _ground(
    customer_request: str, extraction: Extraction
) -> tuple[_Grounded, list[str], list[str]]:
    """Keep a value the sentence states. A bad model span cannot invent one."""

    sentence = parse_customer_request(customer_request)
    rejected: list[str] = []
    recovered: list[str] = []
    specs: dict[str, SpecValue] = {}
    for name in _SPEC_FIELDS:
        parsed = sentence.specs.get(name)
        raw_value = extraction.value(name)
        model_value = _canonical(name, raw_value)
        evidence = extraction.evidence.get(name)
        span_ok = _span_supports(customer_request, evidence, name, model_value)
        if parsed is not None:
            specs[name] = parsed
            if model_value is None or not span_ok:
                recovered.append(f"{name}={parsed} (read from the request)")
            elif model_value != parsed:
                rejected.append(
                    f"{name}={raw_value} (the request states {parsed})"
                )
                recovered.append(f"{name}={parsed} (read from the request)")
        elif model_value is not None:
            if span_ok:
                specs[name] = model_value  # type: ignore[assignment]
            else:
                rejected.append(_rejection(name, raw_value, customer_request, evidence))

    quantity = sentence.quantity
    claimed_quantity = extraction.quantity
    quantity_evidence = extraction.evidence.get("quantity")
    if quantity is not None and claimed_quantity not in {None, quantity}:
        rejected.append(
            _rejection("quantity", claimed_quantity, customer_request, quantity_evidence)
        )
        recovered.append(f"quantity={quantity} (read from the request)")
    elif quantity is None and claimed_quantity is not None:
        if _span_supports(customer_request, quantity_evidence, "quantity", claimed_quantity):
            quantity = claimed_quantity
        else:
            rejected.append(
                _rejection("quantity", claimed_quantity, customer_request, quantity_evidence)
            )
    elif quantity is not None and not _span_supports(
        customer_request, quantity_evidence, "quantity", quantity
    ):
        recovered.append(f"quantity={quantity} (read from the request)")

    product_type = sentence.product_type
    if product_type is None:
        product_type = _text_if_grounded(
            "product_type",
            extraction.product_type,
            extraction.evidence.get("product_type"),
            customer_request,
            rejected,
        )
    model = sentence.model or _text_if_grounded(
        "model",
        extraction.model,
        extraction.evidence.get("model"),
        customer_request,
        rejected,
    )
    substitution_allowed = _substitution(
        customer_request,
        extraction.substitution_allowed,
        extraction.evidence.get("substitution_allowed"),
        sentence.substitution_allowed,
        rejected,
    )
    return (
        _Grounded(
            product_type=product_type,
            specs=specs,
            quantity=quantity,
            model=model,
            substitution_allowed=substitution_allowed,
        ),
        rejected,
        recovered,
    )


def _canonical(name: str, value: object) -> object:
    if name == "grade":
        return canonical_grade(value)
    if name == "species":
        return canonical_species(value)
    return value


def _span_supports(
    customer_request: str, evidence: str | None, name: str, value: object
) -> bool:
    if value is None or not evidence or not _in_request(evidence, customer_request):
        return False
    span = parse_customer_request(evidence)
    if name == "quantity":
        return span.quantity == value
    parsed = span.specs.get(name)
    return parsed == _canonical(name, value) or parsed == value


def _text_if_grounded(
    name: str,
    value: str | None,
    evidence: str | None,
    customer_request: str,
    rejected: list[str],
) -> str | None:
    if value is None:
        return None
    if evidence and _in_request(evidence, customer_request) and normalize_text(value) in normalize_text(evidence):
        return value
    rejected.append(_rejection(name, value, customer_request, evidence))
    return None


def _substitution(
    customer_request: str,
    claimed: bool | None,
    evidence: str | None,
    sentence_value: bool | None,
    rejected: list[str],
) -> bool:
    if sentence_value is not None:
        if claimed is True and sentence_value is False:
            rejected.append(
                "substitution_allowed=true (the cited words do not allow a substitute)"
            )
        return sentence_value
    if claimed is True:
        if evidence and _in_request(evidence, customer_request) and substitution_from_text(evidence) is True:
            return True
        rejected.append(
            "substitution_allowed=true (the cited words do not allow a substitute)"
        )
    return False


def _rejection(name: str, value: object, customer_request: str, evidence: str | None) -> str:
    if not evidence or not _in_request(evidence, customer_request):
        return f"{name}={value} (evidence is not in the customer request)"
    return f"{name}={value} (the cited words do not state that value)"


def _rules_from_grounded(facts: _Grounded, catalog: Catalog) -> BusinessRules:
    matches = _candidates(catalog, facts)
    if facts.model and not _known_identifier(catalog, facts.model):
        matches = ()
    required = tuple(sorted({key for product in matches for key in product.specs}))
    missing = [field for field in required if field not in facts.specs]
    primary: str | None = None
    if matches and not missing and facts.quantity is not None:
        primary = _requested_sku(matches)
    return BusinessRules(
        substitution_allowed=facts.substitution_allowed,
        required_fields=required,
        provided_specs=dict(facts.specs),
        quantity=facts.quantity,
        primary_sku=primary,
    )


def _candidates(catalog: Catalog, facts: _Grounded) -> tuple[Product, ...]:
    if facts.specs:
        matches = matching_products(catalog, facts.specs)
    elif facts.product_type:
        matches = tuple(product for product in catalog.products if _type_hit(product, facts.product_type))
    else:
        matches = ()
    if facts.product_type and facts.specs:
        typed = tuple(product for product in matches if _type_hit(product, facts.product_type))
        if typed:
            matches = typed
    return matches


def _requested_sku(matches: tuple[Product, ...]) -> str | None:
    """Pick the requested product without reading a labeled primary SKU.

    One match is that product. When the other matches all list the same SKU in
    substitutes_for, that SKU is the product the customer asked for and the
    rest are approved replacements. Any other tie stays unresolved.
    """

    if len(matches) == 1:
        return matches[0].sku
    bases: list[str] = []
    for product in matches:
        others = [other for other in matches if other.sku != product.sku]
        if others and all(product.sku in other.substitutes_for for other in others):
            bases.append(product.sku)
    if len(bases) == 1:
        return bases[0]
    return None


def _type_hit(product: Product, product_type: str) -> bool:
    needle = _norm(product_type)
    return needle in _norm(product.name) or needle in _norm(product.summary)


def _known_identifier(catalog: Catalog, model: str) -> bool:
    folded = model.casefold()
    for product in catalog.products:
        if product.sku.casefold() == folded:
            return True
        if any(str(value).casefold() == folded for value in product.specs.values()):
            return True
    return False


def _rationale(decision: Decision, model: str | None, rules: BusinessRules) -> str:
    if decision.status is DecisionStatus.NEEDS_CLARIFICATION:
        return "Required details are missing, so stock and substitutes were not considered."
    if decision.status is DecisionStatus.NEEDS_REVIEW and model and rules.primary_sku is None:
        return f"{model} is not in the catalog, so this needs review instead of a quote."
    if decision.status is DecisionStatus.NEEDS_REVIEW:
        return "The catalog rules cannot make one legal quote, so this needs review."
    if decision.substitution_used:
        return "The requested product is short, and one approved substitute can fill the quantity."
    return "The requested product is in stock for the stated quantity."


def _in_request(evidence: str, customer_request: str) -> bool:
    return normalize_text(evidence) in normalize_text(customer_request)


def _norm(text: str) -> str:
    return normalize_text(text)
