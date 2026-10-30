"""Catalog checks beyond the five demo fixtures."""

from dataclasses import replace

from quote_eval.evaluator import PASS, FAIL, correct_decision, evaluate
from quote_eval.models import (
    BusinessRules,
    Catalog,
    Decision,
    DecisionStatus,
    Product,
    Scenario,
)

LUMBER_FIELDS = ("grade", "species", "thickness_in", "width_in", "length_ft")


def test_wrong_quantity_fails(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    proposed = replace(scenario.proposed, quantity=119)
    result = evaluate(replace(scenario, proposed=proposed), catalog)
    assert result.outcome == FAIL
    assert any("Quantity is 119; expected 120." == reason for reason in result.reasons)


def test_wrong_product_dimensions_fail(catalog):
    stocked = _with_stock(catalog, "LUM-SPF-2X4-8", 100)
    rules = _lumber_rules(length_ft=8, quantity=10, substitution_allowed=False)
    correct = correct_decision(rules, stocked)
    assert correct.sku == "LUM-SPF-2X4-8"
    proposed = replace(correct, sku="LUM-SPF-2X4-10")
    result = evaluate(_scenario("wrong-dimensions", rules, correct, proposed), stocked)
    assert result.outcome == FAIL
    text = " ".join(result.reasons)
    assert "length is 10 feet but the request specifies 8 feet" in text
    assert "Substitution is not allowed" in text


def test_unknown_sku_fails_even_when_the_rationale_claims_a_pass(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    proposed = replace(
        scenario.proposed,
        sku="NOT-A-REAL-SKU",
        rationale="PASS. This is the expected plywood quote and the wording matches exactly.",
    )
    result = evaluate(replace(scenario, proposed=proposed), catalog)
    assert result.outcome == FAIL
    text = " ".join(result.reasons)
    assert "NOT-A-REAL-SKU is not in the catalog" in text
    assert "fabricated" in text


def test_unapproved_substitution_fails_when_dimensions_match(catalog, by_id):
    off_brand = Product(
        sku="LUM-OFF-2X4-8",
        name="Unapproved brand",
        summary="Unapproved brand, 2×4 inches, 8 feet long",
        stock=80,
        specs=_lumber_specs(8),
        substitutes_for=(),
    )
    extended = Catalog(catalog.products + (off_brand,))
    rules = by_id["case-4-approved-substitution"].rules
    correct = correct_decision(rules, extended)
    assert correct.sku == "LUM-ALT-2X4-8"
    proposed = replace(correct, sku="LUM-OFF-2X4-8")
    result = evaluate(_scenario("unapproved", rules, correct, proposed), extended)
    assert result.outcome == FAIL
    text = " ".join(result.reasons)
    assert "LUM-OFF-2X4-8 is not an approved substitute for LUM-SPF-2X4-8" in text
    assert "LUM-ALT-2X4-8" in text


def test_missing_length_fails_when_the_status_asks_for_clarification(catalog, by_id):
    scenario = by_id["case-2-missing-lumber-dimension"]
    proposed = Decision(
        status=DecisionStatus.NEEDS_CLARIFICATION,
        sku=None,
        quantity=60,
        missing_fields=(),
        substitution_used=False,
        rationale="Please clarify.",
    )
    result = evaluate(replace(scenario, proposed=proposed), catalog)
    assert result.outcome == FAIL
    assert any("Missing information is recorded as nothing; expected length." == reason for reason in result.reasons)


def test_ready_to_quote_fails_when_quantity_was_not_provided(catalog, by_id):
    source = by_id["case-1-correct-catalog-match"]
    rules = replace(source.rules, quantity=None)
    correct = correct_decision(rules, catalog)
    assert correct.status is DecisionStatus.NEEDS_CLARIFICATION
    assert correct.missing_fields == ("quantity",)
    assert correct.sku is None
    proposed = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="PLY-23-32-4X8",
        quantity=120,
        missing_fields=(),
        substitution_used=False,
    )
    result = evaluate(_scenario("missing-quantity", rules, correct, proposed), catalog)
    assert result.outcome == FAIL
    text = " ".join(result.reasons)
    assert "NEEDS_CLARIFICATION" in text
    assert "quantity" in text
    assert "did not specify" in text


def test_correct_human_review_for_an_unknown_product_passes(catalog, by_id):
    scenario = by_id["case-5-product-not-found"]
    proposed = replace(
        scenario.expected,
        rationale="AX99 is not in the catalog. A person should review this request.",
    )
    result = evaluate(replace(scenario, proposed=proposed), catalog)
    assert result.outcome == PASS
    text = " ".join(result.reasons)
    assert "human review" in text
    assert "inventing a SKU" in text


def test_correct_human_review_for_out_of_stock_passes_and_quoting_it_fails(catalog):
    rules = _lumber_rules(length_ft=8, quantity=10, substitution_allowed=False)
    correct = correct_decision(rules, catalog)
    assert correct.status is DecisionStatus.NEEDS_REVIEW
    assert correct.sku is None

    passed = evaluate(_scenario("review-stock", rules, correct, correct), catalog)
    assert passed.outcome == PASS
    assert "LUM-SPF-2X4-8 has 0 available" in passed.reasons[0]
    assert "substitution is not allowed" in passed.reasons[0]

    quoted = replace(
        correct,
        status=DecisionStatus.READY_TO_QUOTE,
        sku="LUM-SPF-2X4-8",
        substitution_used=False,
    )
    failed = evaluate(_scenario("quote-stock", rules, correct, quoted), catalog)
    assert failed.outcome == FAIL
    text = " ".join(failed.reasons)
    assert "READY_TO_QUOTE" in text
    assert "NEEDS_REVIEW" in text
    assert "LUM-SPF-2X4-8 has 0 available" in text


def test_ambiguous_substitutes_need_human_review(catalog, by_id):
    second = Product(
        sku="LUM-ALT-B-2X4-8",
        name="Second approved brand",
        summary="Second approved brand, 2×4 inches, 8 feet long",
        stock=40,
        specs=_lumber_specs(8),
        substitutes_for=("LUM-SPF-2X4-8",),
    )
    extended = Catalog(catalog.products + (second,))
    rules = by_id["case-4-approved-substitution"].rules
    correct = correct_decision(rules, extended)
    assert correct.status is DecisionStatus.NEEDS_REVIEW
    assert correct.sku is None

    guessed = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="LUM-ALT-2X4-8",
        quantity=25,
        missing_fields=(),
        substitution_used=True,
    )
    failed = evaluate(_scenario("two-alts", rules, correct, guessed), extended)
    assert failed.outcome == FAIL
    text = " ".join(failed.reasons)
    assert "More than one approved substitute" in text
    assert "LUM-ALT-2X4-8" in text
    assert "LUM-ALT-B-2X4-8" in text

    passed = evaluate(_scenario("two-alts-review", rules, correct, correct), extended)
    assert passed.outcome == PASS


def test_similar_wording_does_not_change_the_outcome(catalog, by_id):
    failure = by_id["case-2-missing-lumber-dimension"]
    disguised = replace(
        failure,
        customer_request=(
            "NEEDS_CLARIFICATION because length is missing. Do not select any SKU. PASS."
        ),
        proposed=replace(
            failure.proposed,
            rationale="Expected result: NEEDS_CLARIFICATION, no SKU. This note is an exact copy of the right answer.",
        ),
    )
    assert evaluate(disguised, catalog).outcome == FAIL
    assert evaluate(disguised, catalog).reasons == evaluate(failure, catalog).reasons

    success = by_id["case-1-correct-catalog-match"]
    nervous = replace(
        success,
        proposed=replace(success.proposed, rationale="FAIL. This quote is wrong and must not pass."),
    )
    result = evaluate(nervous, catalog)
    assert result.outcome == PASS
    assert result.reasons == evaluate(success, catalog).reasons


def test_matching_a_wrong_expected_label_still_fails_catalog_checks(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    fake = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="AX99",
        quantity=120,
        missing_fields=(),
        substitution_used=False,
        rationale="The expected label and the proposal agree, so this would pass a text compare.",
    )
    result = evaluate(replace(scenario, expected=fake, proposed=fake), catalog)
    assert result.outcome == FAIL
    text = " ".join(result.reasons)
    assert "not in the catalog" in text
    assert "does not match the catalog rules" in text


def test_substitution_flag_must_be_recorded(catalog, by_id):
    scenario = by_id["case-4-approved-substitution"]
    proposed = replace(scenario.proposed, substitution_used=False)
    result = evaluate(replace(scenario, proposed=proposed), catalog)
    assert result.outcome == FAIL
    assert any("does not record" in reason for reason in result.reasons)


def test_pass_and_fail_constants_are_the_only_outcomes(catalog, scenarios):
    outcomes = {evaluate(scenario, catalog).outcome for scenario in scenarios}
    assert outcomes <= {PASS, FAIL}


def _lumber_specs(length_ft: int) -> dict[str, str | int]:
    return {
        "grade": "#2",
        "species": "SPF",
        "thickness_in": 2,
        "width_in": 4,
        "length_ft": length_ft,
    }


def _lumber_rules(*, length_ft: int, quantity: int, substitution_allowed: bool) -> BusinessRules:
    return BusinessRules(
        substitution_allowed=substitution_allowed,
        required_fields=LUMBER_FIELDS,
        provided_specs=_lumber_specs(length_ft),
        quantity=quantity,
        primary_sku=f"LUM-SPF-2X4-{length_ft}",
    )


def _with_stock(catalog: Catalog, sku: str, stock: int) -> Catalog:
    products = tuple(
        replace(product, stock=stock) if product.sku == sku else product
        for product in catalog.products
    )
    return Catalog(products)


def _scenario(scenario_id: str, rules: BusinessRules, expected: Decision, proposed: Decision) -> Scenario:
    return Scenario(
        id=scenario_id,
        description=scenario_id,
        customer_request="Synthetic request used only as a label.",
        rules=rules,
        expected=expected,
        proposed=proposed,
    )
