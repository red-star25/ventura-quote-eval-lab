"""The five shipped fixtures are the milestone's demo set."""

from quote_eval.evaluator import PASS, FAIL, evaluate_all

CASE_1 = "case-1-correct-catalog-match"
CASE_2 = "case-2-missing-lumber-dimension"
CASE_3 = "case-3-substitution-not-allowed"
CASE_4 = "case-4-approved-substitution"
CASE_5 = "case-5-product-not-found"


def test_catalog_contains_the_four_synthetic_products(catalog):
    assert [product.sku for product in catalog.products] == [
        "PLY-23-32-4X8",
        "LUM-SPF-2X4-8",
        "LUM-SPF-2X4-10",
        "LUM-ALT-2X4-8",
    ]
    stock = {product.sku: product.stock for product in catalog.products}
    assert stock == {
        "PLY-23-32-4X8": 200,
        "LUM-SPF-2X4-8": 0,
        "LUM-SPF-2X4-10": 100,
        "LUM-ALT-2X4-8": 100,
    }
    alternative = catalog.get("LUM-ALT-2X4-8")
    assert alternative is not None
    assert alternative.substitutes_for == ("LUM-SPF-2X4-8",)


def test_five_scenarios_score_two_pass_and_three_fail(catalog, scenarios):
    results = evaluate_all(scenarios, catalog)
    outcomes = {result.scenario_id: result.outcome for result in results}
    assert outcomes == {
        CASE_1: PASS,
        CASE_2: FAIL,
        CASE_3: FAIL,
        CASE_4: PASS,
        CASE_5: FAIL,
    }
    assert list(outcomes.values()).count(PASS) == 2
    assert list(outcomes.values()).count(FAIL) == 3


def test_case_1_accepts_the_matching_plywood_quote(catalog, by_id):
    result = _score(by_id, catalog, CASE_1)
    assert result.outcome == PASS
    assert result.proposed.sku == "PLY-23-32-4X8"
    assert result.proposed.quantity == 120
    text = _text(result)
    assert "PLY-23-32-4X8" in text
    assert "120" in text


def test_case_2_fails_because_length_was_guessed(catalog, by_id):
    result = _score(by_id, catalog, CASE_2)
    assert result.outcome == FAIL
    assert result.expected.status.value == "NEEDS_CLARIFICATION"
    assert result.expected.sku is None
    text = _text(result)
    assert "NEEDS_CLARIFICATION" in text
    assert "length" in text
    assert "8 feet" in text
    assert "did not specify" in text
    assert "fabricated" not in text


def test_case_3_fails_for_wrong_length_and_prohibited_substitution(catalog, by_id):
    result = _score(by_id, catalog, CASE_3)
    assert result.outcome == FAIL
    assert result.expected.sku == "LUM-SPF-2X4-10"
    assert result.proposed.sku == "LUM-ALT-2X4-8"
    text = _text(result)
    assert "Substitution is not allowed" in text
    assert "8 feet" in text
    assert "10 feet" in text


def test_case_4_accepts_the_approved_substitute(catalog, by_id):
    result = _score(by_id, catalog, CASE_4)
    assert result.outcome == PASS
    assert result.proposed.sku == "LUM-ALT-2X4-8"
    assert result.proposed.quantity == 25
    assert result.proposed.substitution_used is True
    text = _text(result)
    assert "approved substitute" in text
    assert "LUM-SPF-2X4-8" in text


def test_case_5_fails_because_the_sku_is_fabricated(catalog, by_id):
    result = _score(by_id, catalog, CASE_5)
    assert result.outcome == FAIL
    assert result.expected.status.value == "NEEDS_REVIEW"
    assert result.expected.sku is None
    text = _text(result)
    assert "NEEDS_REVIEW" in text
    assert "AX99" in text
    assert "not in the catalog" in text
    assert "fabricated" in text


def test_repeated_runs_stay_identical(catalog, scenarios):
    first = evaluate_all(scenarios, catalog)
    second = evaluate_all(scenarios, catalog)
    assert [(item.outcome, item.reasons) for item in first] == [
        (item.outcome, item.reasons) for item in second
    ]


def _score(by_id, catalog, scenario_id):
    from quote_eval.evaluator import evaluate

    return evaluate(by_id[scenario_id], catalog)


def _text(result) -> str:
    return " ".join(result.reasons)
