"""Invariant checks that do not call the quote decider.

These look at a finished decision, the catalog row it names, and the specs a
caller says were stated. They do not build the expected decision.
"""

from __future__ import annotations

from quote_eval.models import Catalog, Decision, DecisionStatus, SpecValue


def safety_issues(
    decision: Decision,
    catalog: Catalog,
    *,
    substitution_allowed: bool,
    stated_specs: dict[str, SpecValue],
) -> tuple[str, ...]:
    """Problems that make a ready quote unsafe. Empty when this quote is allowed."""

    if decision.status is not DecisionStatus.READY_TO_QUOTE:
        return ()
    issues: list[str] = []
    if decision.missing_fields:
        issues.append("ready quote still lists missing specifications")
    if decision.quantity is None:
        issues.append("ready quote has no quantity")
    product = catalog.get(decision.sku)
    if product is None:
        issues.append("ready quote uses an unknown SKU")
        return tuple(issues)
    for key, value in product.specs.items():
        if stated_specs.get(key) != value:
            issues.append(f"ready quote is missing {key}")
    if decision.quantity is not None and decision.quantity > product.stock:
        issues.append("ready quote quantity exceeds available stock")
    if product.substitutes_for and not substitution_allowed:
        issues.append("unauthorized substitution")
    if decision.substitution_used and not substitution_allowed:
        issues.append("unauthorized substitution")
    if decision.substitution_used and not product.substitutes_for:
        issues.append("substitution is not approved for this SKU")
    return tuple(dict.fromkeys(issues))
