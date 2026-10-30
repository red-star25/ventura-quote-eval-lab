"""Frozen final_validation set. Labels are checked against the catalog, not generated."""

import json
from pathlib import Path

from quote_eval.categories import EXTRACTION_OR_EVIDENCE, INCORRECT_INVENTORY, classify
from quote_eval.cli import main
from quote_eval.dimensions import parse_customer_request
from quote_eval.evaluator import validate_expected_labels
from quote_eval.extract import (
    EXTRACT_PROMPT,
    EXTRACT_PROMPT_V2,
    build_extraction_messages,
)
from quote_eval.hybrid import evaluate_hybrid, render_hybrid_report
from quote_eval.model_input import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_V2,
    build_messages,
)
from quote_eval.models import (
    BusinessRules,
    Decision,
    DecisionStatus,
    Product,
    Scenario,
    load_catalog,
    load_scenarios,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FINAL = DATA / "final_validation_scenarios.json"
OLDER = (
    DATA / "scenarios.json",
    DATA / "development_scenarios.json",
    DATA / "heldout_scenarios.json",
)
PROMPTS = (SYSTEM_PROMPT, SYSTEM_PROMPT_V2, EXTRACT_PROMPT, EXTRACT_PROMPT_V2)
FIELDS = (
    "product_type",
    "grade",
    "species",
    "thickness_in",
    "width_in",
    "width_ft",
    "length_ft",
    "quantity",
    "model",
    "substitution_allowed",
)


def test_final_validation_is_twenty_new_sentences():
    scenarios = load_scenarios(FINAL)
    assert len(scenarios) == 20
    assert len({scenario.id for scenario in scenarios}) == 20
    requests = [scenario.customer_request for scenario in scenarios]
    assert len(set(requests)) == 20
    older = _older_requests()
    assert older.isdisjoint(requests)
    for scenario in scenarios:
        assert scenario.split == "final_validation"
        assert "\n" not in scenario.customer_request


def test_sentences_state_the_labeled_facts():
    """The private specs are what the current reader can see in the sentence."""

    for scenario in load_scenarios(FINAL):
        reading = parse_customer_request(scenario.customer_request)
        spoken = False if reading.substitution_allowed is None else reading.substitution_allowed
        assert scenario.rules.substitution_allowed is spoken
        assert reading.quantity == scenario.rules.quantity
        if reading.model is not None:
            assert scenario.rules.provided_specs == {"model": reading.model}
            assert reading.specs == {}
        else:
            assert reading.specs == scenario.rules.provided_specs
            assert reading.model is None


def test_expected_decisions_follow_catalog_policy():
    catalog = load_catalog(DATA / "catalog.json")
    for scenario in load_scenarios(FINAL):
        _assert_policy(scenario, catalog)


def test_hand_labels_stay_consistent_with_the_checker():
    """Consistency check only. The JSON was not produced by correct_decision."""

    catalog = load_catalog(DATA / "catalog.json")
    validate_expected_labels(load_scenarios(FINAL), catalog)


def test_labels_stay_out_of_both_model_inputs():
    catalog = load_catalog(DATA / "catalog.json")
    for scenario in load_scenarios(FINAL):
        for prompt in PROMPTS:
            assert scenario.customer_request not in prompt
            assert scenario.id not in prompt
            assert scenario.description not in prompt
        messages = build_messages(scenario, catalog, "quote-decision-v1")
        payload = json.loads(messages[1]["content"])
        assert set(payload) == {
            "customer_request",
            "substitution_allowed",
            "substitution_policy",
            "catalog",
        }
        assert payload["customer_request"] == scenario.customer_request
        assert payload["substitution_allowed"] is scenario.rules.substitution_allowed
        assert scenario.id not in messages[1]["content"]
        assert scenario.description not in messages[1]["content"]
        assert "primary_sku" not in messages[1]["content"]
        extraction = build_extraction_messages(
            scenario.customer_request, "quote-extract-v2"
        )
        assert json.loads(extraction[1]["content"]) == {
            "customer_request": scenario.customer_request
        }


def test_inventory_disagreement_is_its_own_category():
    expected = Decision(
        status=DecisionStatus.NEEDS_REVIEW,
        sku=None,
        quantity=140,
        missing_fields=(),
        substitution_used=False,
    )
    proposed = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="LUM-ALT-2X4-8",
        quantity=140,
        missing_fields=(),
        substitution_used=True,
    )
    categories = classify(expected, proposed)
    assert INCORRECT_INVENTORY in categories
    assert categories[0] == "unsafe_quote_approval"


def test_recovered_request_does_not_count_as_an_evidence_failure(catalog):
    scenario = _by_id()["final-missing-length-spaced"]
    raw = _packed(
        {"length_ft": 8, "quantity": 22, "grade": "#2", "species": "SPF"},
        {"length_ft": "8 feet", "quantity": "22 pieces", "grade": "#2", "species": "SPF"},
    )
    run = evaluate_hybrid((scenario,), catalog, _script({scenario.customer_request: raw}))[0]
    assert run.outcome == "PASS"
    assert run.rejected
    assert run.failure_categories == ()


def test_failed_drop_is_an_evidence_problem(catalog):
    request = "Quote 6 pieces of #2 SPF 2×4 lumber."
    ready = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="LUM-SPF-2X4-10",
        quantity=6,
        missing_fields=(),
        substitution_used=False,
    )
    scenario = Scenario(
        id="evidence-check",
        description="Unit check only. Not part of the frozen set.",
        customer_request=request,
        rules=BusinessRules(
            substitution_allowed=False,
            required_fields=("grade", "species", "thickness_in", "width_in", "length_ft"),
            provided_specs={
                "grade": "#2",
                "species": "SPF",
                "thickness_in": 2,
                "width_in": 4,
                "length_ft": 10,
            },
            quantity=6,
            primary_sku="LUM-SPF-2X4-10",
        ),
        expected=ready,
        proposed=ready,
        split="final_validation",
    )
    raw = _packed(
        {"length_ft": 10, "quantity": 6},
        {"length_ft": "10 feet", "quantity": "6 pieces"},
    )
    run = evaluate_hybrid((scenario,), catalog, _script({request: raw}))[0]
    assert run.outcome == "FAIL"
    assert run.rejected
    assert EXTRACTION_OR_EVIDENCE in run.failure_categories
    report = render_hybrid_report((run,))
    assert "extraction or evidence-validation problem: 1" in report
    assert "API failures: 0." in report
    assert "Parsing failures: 0." in report


def test_final_validation_fixtures_match_the_hand_labels(capsys):
    assert main(["fixtures", "--set", "final_validation"]) == 0
    report = capsys.readouterr().out
    assert "20 passed, 0 failed, 20 total." in report
    assert "final-ambiguous-eight" in report
    assert "not a live model score" in report


def test_all_set_leaves_final_validation_out(capsys):
    assert main(["fixtures", "--set", "all"]) == 0
    report = capsys.readouterr().out
    assert "final-plywood-ready" not in report


def test_final_commands_do_not_call_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["live", "--set", "final_validation", "--prompt", "quote-decision-v1"]) == 2
    assert main(["hybrid", "--set", "final_validation", "--prompt", "quote-extract-v2"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def _assert_policy(scenario: Scenario, catalog) -> None:
    rules = scenario.rules
    expected = scenario.expected
    missing = [field for field in rules.required_fields if field not in rules.provided_specs]
    if rules.quantity is None and "quantity" not in missing:
        missing.append("quantity")
    missing = tuple(sorted(missing))
    if missing:
        assert expected.status is DecisionStatus.NEEDS_CLARIFICATION
        assert expected.sku is None
        assert expected.quantity == rules.quantity
        assert expected.missing_fields == missing
        assert expected.substitution_used is False
        return

    assert expected.missing_fields == ()
    assert expected.quantity == rules.quantity
    matches = _matches(catalog, rules.provided_specs)
    primary = catalog.get(rules.primary_sku) if rules.primary_sku else None
    if rules.primary_sku is None and len(matches) != 1:
        assert expected.status is DecisionStatus.NEEDS_REVIEW
        assert expected.sku is None
        assert expected.substitution_used is False
        return
    assert primary is not None
    assert rules.quantity is not None
    if primary.stock >= rules.quantity:
        assert expected.status is DecisionStatus.READY_TO_QUOTE
        assert expected.sku == primary.sku
        assert expected.substitution_used is False
        return
    if not rules.substitution_allowed:
        assert expected.status is DecisionStatus.NEEDS_REVIEW
        assert expected.sku is None
        assert expected.substitution_used is False
        return
    alternatives = [
        product
        for product in catalog.products
        if primary.sku in product.substitutes_for
        and product.stock >= rules.quantity
        and all(product.specs.get(key) == value for key, value in rules.provided_specs.items())
    ]
    if len(alternatives) == 1:
        assert expected.status is DecisionStatus.READY_TO_QUOTE
        assert expected.sku == alternatives[0].sku
        assert expected.substitution_used is True
        return
    assert expected.status is DecisionStatus.NEEDS_REVIEW
    assert expected.sku is None
    assert expected.substitution_used is False


def _matches(catalog, specs: dict) -> list[Product]:
    if not specs:
        return []
    return [
        product
        for product in catalog.products
        if all(product.specs.get(key) == value for key, value in specs.items())
    ]


def _older_requests() -> set[str]:
    found: set[str] = set()
    for path in OLDER:
        for scenario in load_scenarios(path):
            found.add(scenario.customer_request)
    return found


def _by_id() -> dict[str, Scenario]:
    return {scenario.id: scenario for scenario in load_scenarios(FINAL)}


def _packed(values: dict[str, object], evidence: dict[str, str]) -> str:
    body: dict[str, object] = {name: None for name in FIELDS}
    cited: dict[str, str | None] = {name: None for name in FIELDS}
    body.update(values)
    cited.update(evidence)
    body["evidence"] = cited
    return json.dumps(body)


class _Script:
    def __init__(self, raw_by_request: dict[str, str]) -> None:
        self.model_name = "fake-model"
        self.raw_by_request = raw_by_request

    def generate(self, messages: list[dict[str, str]]) -> str:
        request = json.loads(messages[1]["content"])["customer_request"]
        return self.raw_by_request[request]


def _script(raw_by_request: dict[str, str]) -> _Script:
    return _Script(raw_by_request)
