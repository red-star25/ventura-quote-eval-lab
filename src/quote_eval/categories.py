"""Name why a parsed decision failed, using only the fields that differ.

PASS stays PASS. These labels explain a FAIL. One decision can carry more than one.
"""

from __future__ import annotations

from quote_eval.models import Decision, DecisionStatus

UNSAFE_QUOTE_APPROVAL = "unsafe_quote_approval"
INCORRECT_INVENTORY = "incorrect_inventory_decision"
UNNECESSARY_HUMAN_ESCALATION = "unnecessary_human_escalation"
WRONG_PRODUCT_OR_QUANTITY = "wrong_product_or_quantity"
INCORRECT_SUBSTITUTION = "incorrect_substitution"
MISSING_CLARIFICATION = "missing_clarification"
EXTRACTION_OR_EVIDENCE = "extraction_or_evidence"
INVALID_MODEL_OUTPUT = "invalid_model_output"

CATEGORY_ORDER = (
    UNSAFE_QUOTE_APPROVAL,
    INCORRECT_INVENTORY,
    UNNECESSARY_HUMAN_ESCALATION,
    WRONG_PRODUCT_OR_QUANTITY,
    INCORRECT_SUBSTITUTION,
    MISSING_CLARIFICATION,
    EXTRACTION_OR_EVIDENCE,
    INVALID_MODEL_OUTPUT,
)

CATEGORY_LABELS = {
    UNSAFE_QUOTE_APPROVAL: "wrong quote approval",
    INCORRECT_INVENTORY: "incorrect inventory decision",
    UNNECESSARY_HUMAN_ESCALATION: "unnecessary human review",
    WRONG_PRODUCT_OR_QUANTITY: "wrong product or quantity",
    INCORRECT_SUBSTITUTION: "incorrect substitution",
    MISSING_CLARIFICATION: "missing clarification",
    EXTRACTION_OR_EVIDENCE: "extraction or evidence-validation problem",
    INVALID_MODEL_OUTPUT: "invalid model output",
}


def classify(expected: Decision, proposed: Decision) -> tuple[str, ...]:
    """Categories for a decision that parsed but does not match the label."""

    if proposed.scored() == expected.scored():
        return ()
    found: list[str] = []
    if (
        proposed.status is DecisionStatus.READY_TO_QUOTE
        and expected.status is not DecisionStatus.READY_TO_QUOTE
    ):
        found.append(UNSAFE_QUOTE_APPROVAL)
    if _inventory_disagreement(expected, proposed):
        found.append(INCORRECT_INVENTORY)
    if (
        proposed.status is DecisionStatus.NEEDS_REVIEW
        and expected.status is not DecisionStatus.NEEDS_REVIEW
    ):
        found.append(UNNECESSARY_HUMAN_ESCALATION)
    if proposed.sku != expected.sku or proposed.quantity != expected.quantity:
        found.append(WRONG_PRODUCT_OR_QUANTITY)
    if proposed.substitution_used != expected.substitution_used:
        found.append(INCORRECT_SUBSTITUTION)
    if expected.status is DecisionStatus.NEEDS_CLARIFICATION and (
        proposed.status is not DecisionStatus.NEEDS_CLARIFICATION
        or set(proposed.missing_fields) != set(expected.missing_fields)
    ):
        found.append(MISSING_CLARIFICATION)
    return tuple(name for name in CATEGORY_ORDER if name in found)


def format_categories(categories: tuple[str, ...] | list[str]) -> str:
    if not categories:
        return "none of the named categories"
    return ", ".join(CATEGORY_LABELS[name] for name in categories)


def with_extraction_problem(
    categories: tuple[str, ...], rejected: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """Add an evidence label when a failed hybrid run dropped a model value."""

    if not rejected:
        return tuple(name for name in CATEGORY_ORDER if name in categories)
    found = set(categories)
    found.add(EXTRACTION_OR_EVIDENCE)
    return tuple(name for name in CATEGORY_ORDER if name in found)


def category_count_lines(
    groups: list[tuple[str, ...]] | tuple[tuple[str, ...], ...],
    *,
    heading: str = "Failure category counts (one failed case can add to more than one):",
) -> list[str]:
    counts = {name: 0 for name in CATEGORY_ORDER}
    for group in groups:
        for name in group:
            if name in counts:
                counts[name] += 1
    lines = [heading]
    for name in CATEGORY_ORDER:
        lines.append(f"  {CATEGORY_LABELS[name]}: {counts[name]}")
    return lines


def origin_count_lines(origins: list[str] | tuple[str, ...]) -> list[str]:
    """Exact counts of stored failure_origin values."""

    return [
        f"API failures: {sum(origin == 'api' for origin in origins)}.",
        f"Parsing failures: {sum(origin == 'parse' for origin in origins)}.",
        f"Decision failures: {sum(origin == 'decision' for origin in origins)}.",
    ]


def _inventory_disagreement(expected: Decision, proposed: Decision) -> bool:
    """Ready versus review, with the same quantity and no missing field.

    That disagreement is about stock or an approved substitute. A missing
    length or a different quantity is a different failure.
    """

    return (
        not proposed.missing_fields
        and not expected.missing_fields
        and proposed.quantity == expected.quantity
        and {proposed.status, expected.status}
        == {DecisionStatus.READY_TO_QUOTE, DecisionStatus.NEEDS_REVIEW}
    )
