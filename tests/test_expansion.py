"""Expanded cases, failure categories, and prompt versions. No network calls."""

import hashlib
import json
from pathlib import Path

import pytest

from quote_eval.categories import classify
from quote_eval.compare import render_comparison
from quote_eval.evaluator import load_validated_dataset
from quote_eval.llm import TEMPERATURE, evaluate_with_model
from quote_eval.model_input import (
    PROMPT_VERSION,
    PROMPT_VERSION_V2,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_V2,
    build_messages,
)
from quote_eval.models import Decision, DecisionStatus, QuoteEvalError, default_data_dir
from quote_eval.cli import main

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
V1_SHA256 = "8b27741086d365fca49d9559116b41d0bb95f5a4d80b6ba66bef082d7a9a9f6a"

BASELINE_REQUESTS = {
    "case-1-correct-catalog-match": "Please quote 120 sheets of 23/32-inch plywood, 4×8 feet.",
    "case-2-missing-lumber-dimension": "Quote 60 pieces of #2 SPF 2×4 lumber.",
    "case-3-substitution-not-allowed": "Quote 10 pieces of #2 SPF 2×4×10-foot lumber. No substitutions.",
    "case-4-approved-substitution": (
        "Quote 25 pieces of #2 SPF 2×4×8-foot lumber. "
        "An approved equivalent is acceptable if the original is unavailable."
    ),
    "case-5-product-not-found": "Quote 5 units of acoustic insulation model AX99.",
}


def test_v1_prompt_text_is_unchanged():
    assert hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() == V1_SHA256
    assert "Work in this order" not in SYSTEM_PROMPT


def test_v2_checks_specifications_before_stock():
    assert SYSTEM_PROMPT_V2 != SYSTEM_PROMPT
    assert "Specifications and quantity come first" in SYSTEM_PROMPT_V2
    assert "before you consider stock" in SYSTEM_PROMPT_V2
    assert "Stock and substitution come last" in SYSTEM_PROMPT_V2


def test_prompt_versions_share_the_user_payload_and_hide_labels(catalog, scenarios):
    development, heldout = _expanded(catalog)
    for scenario in (*scenarios, *development, *heldout):
        v1 = build_messages(scenario, catalog, PROMPT_VERSION)
        v2 = build_messages(scenario, catalog, PROMPT_VERSION_V2)
        assert v1[1] == v2[1]
        assert v1[0]["content"] == SYSTEM_PROMPT
        assert v2[0]["content"] == SYSTEM_PROMPT_V2
        for prompt in (SYSTEM_PROMPT, SYSTEM_PROMPT_V2):
            assert scenario.id not in prompt
            assert scenario.description not in prompt
            assert scenario.customer_request not in prompt
            assert scenario.proposed.rationale not in prompt


def test_original_five_requests_are_unchanged(scenarios):
    assert {scenario.id: scenario.customer_request for scenario in scenarios} == BASELINE_REQUESTS
    assert {scenario.split for scenario in scenarios} == {"baseline"}


def test_development_and_heldout_are_separate_labeled_sets(catalog):
    development, heldout = _expanded(catalog)
    assert len(development) == 8
    assert len(heldout) == 7
    assert {scenario.split for scenario in development} == {"development"}
    assert {scenario.split for scenario in heldout} == {"heldout"}
    dev_ids = {scenario.id for scenario in development}
    hold_ids = {scenario.id for scenario in heldout}
    assert dev_ids.isdisjoint(hold_ids)
    assert dev_ids.isdisjoint(BASELINE_REQUESTS)
    assert hold_ids.isdisjoint(BASELINE_REQUESTS)
    assert {scenario.customer_request for scenario in development}.isdisjoint(
        {scenario.customer_request for scenario in heldout}
    )


def test_review_instead_of_clarification_has_two_categories():
    expected = Decision(
        status=DecisionStatus.NEEDS_CLARIFICATION,
        sku=None,
        quantity=60,
        missing_fields=("length_ft",),
        substitution_used=False,
    )
    proposed = Decision(
        status=DecisionStatus.NEEDS_REVIEW,
        sku=None,
        quantity=60,
        missing_fields=(),
        substitution_used=False,
        rationale="The lumber is out of stock and substitution is not allowed.",
    )
    assert classify(expected, proposed) == (
        "unnecessary_human_escalation",
        "missing_clarification",
    )


def test_categories_follow_the_field_differences(catalog, by_id):
    missing = by_id["case-2-missing-lumber-dimension"]
    guessed = evaluate_with_model(
        (missing,),
        catalog,
        _script({missing.customer_request: _body(missing.proposed, "Assuming 8 feet.")}),
    )[0]
    assert guessed.failure_categories == (
        "unsafe_quote_approval",
        "wrong_product_or_quantity",
        "missing_clarification",
    )

    quantity = by_id["case-1-correct-catalog-match"]
    short = evaluate_with_model(
        (quantity,),
        catalog,
        _script({quantity.customer_request: _body(quantity.expected, "Short.", quantity=119)}),
    )[0]
    assert short.failure_categories == ("wrong_product_or_quantity",)

    swapped = by_id["case-3-substitution-not-allowed"]
    wrong_sub = evaluate_with_model(
        (swapped,),
        catalog,
        _script({swapped.customer_request: _body(swapped.proposed, "Quoted a substitute.")}),
    )[0]
    assert wrong_sub.failure_categories == (
        "wrong_product_or_quantity",
        "incorrect_substitution",
    )

    broken = evaluate_with_model(
        (quantity,),
        catalog,
        _script({quantity.customer_request: "not json"}),
    )[0]
    assert broken.failure_categories == ("invalid_model_output",)


def test_selected_prompt_version_is_recorded_and_does_not_change_settings(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    model = _script({scenario.customer_request: _body(scenario.expected, "Ready.")})
    run = evaluate_with_model(
        (scenario,),
        catalog,
        model,
        prompt_version=PROMPT_VERSION_V2,
    )[0]
    assert run.outcome == "PASS"
    assert run.failure_categories == ()
    assert run.prompt_version == PROMPT_VERSION_V2
    assert run.temperature == TEMPERATURE
    assert model.messages[0][0]["content"] == SYSTEM_PROMPT_V2
    assert json.loads(model.messages[0][1]["content"]) == json.loads(
        build_messages(scenario, catalog, PROMPT_VERSION)[1]["content"]
    )


def test_unknown_prompt_is_rejected_before_the_model_is_called(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]

    class Boom:
        model_name = "fake-model"

        def generate(self, messages):
            raise AssertionError("the model was called")

    with pytest.raises(QuoteEvalError, match="Unknown prompt"):
        evaluate_with_model((scenario,), catalog, Boom(), prompt_version="quote-decision-v9")


def test_fixture_sets_stay_separate(capsys):
    assert main(["fixtures", "--set", "development"]) == 0
    development = capsys.readouterr().out
    assert "dev-missing-length" in development
    assert "hold-unknown-product" not in development
    assert "case-1-correct-catalog-match" not in development
    assert "Report: development scenarios." in development
    assert "synthetic fixture baseline" not in development
    assert "Summary: 8 passed, 0 failed, 8 total." in development

    assert main(["fixtures", "--set", "heldout"]) == 0
    heldout = capsys.readouterr().out
    assert "hold-unknown-product" in heldout
    assert "dev-missing-length" not in heldout
    assert "Summary: 7 passed, 0 failed, 7 total." in heldout


def test_set_and_scenarios_flags_cannot_be_combined(capsys):
    assert main(["fixtures", "--set", "development", "--scenarios", str(DATA / "scenarios.json")]) == 2
    assert "not both" in capsys.readouterr().err


def test_live_prompt_flag_is_recorded_from_a_fake_model(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")

    class FakeModel:
        def __init__(self, *, api_key: str, model: str, client=None) -> None:
            self.model_name = model

        def generate(self, messages):
            assert messages[0]["content"] == SYSTEM_PROMPT_V2
            return "not json"

    monkeypatch.setattr("quote_eval.cli.OpenAIQuoteModel", FakeModel)
    output = tmp_path / "v2.json"
    assert main(["live", "--set", "heldout", "--prompt", "quote-decision-v2", "--model", "gpt-test", "--output", str(output)]) == 0
    report = capsys.readouterr().out
    assert "quote-decision-v2" in report
    assert "heldout: 0 passed, 7 failed, 7 total." in report
    assert "invalid model output" in report
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["prompt_version"] == "quote-decision-v2"
    assert saved["temperature"] == 0
    assert saved["model_name"] == "gpt-test"
    assert {row["split"] for row in saved["results"]} == {"heldout"}


def test_compare_flags_unfair_pairs_and_splits_the_summary(capsys, tmp_path):
    shared_input = {"customer_request": "Quote 40 pieces of lumber.", "substitution_allowed": False}
    left = _document(
        "quote-decision-v1",
        [
            _row("dev-missing-length", "development", "FAIL", shared_input, "NEEDS_REVIEW"),
            _row("hold-unknown-product", "heldout", "PASS", shared_input, "NEEDS_REVIEW"),
        ],
    )
    right = _document(
        "quote-decision-v2",
        [
            _row("dev-missing-length", "development", "PASS", shared_input, "NEEDS_CLARIFICATION"),
            _row(
                "hold-unknown-product",
                "heldout",
                "PASS",
                {**shared_input, "substitution_allowed": True},
                "NEEDS_REVIEW",
            ),
        ],
    )
    left_path = tmp_path / "v1.json"
    right_path = tmp_path / "v2.json"
    left_path.write_text(json.dumps(left), encoding="utf-8")
    right_path.write_text(json.dumps(right), encoding="utf-8")
    assert main(["compare", str(left_path), str(right_path)]) == 0
    report = capsys.readouterr().out
    assert "same model input and generation settings" in report
    assert "model input differs" in report
    assert "quote-decision-v1 development: 0 passed, 1 failed, 1 total." in report
    assert "quote-decision-v2 development: 1 passed, 0 failed, 1 total." in report
    assert "quote-decision-v1 heldout: 1 passed, 0 failed, 1 total." in report
    assert "not a statistically reliable measurement" in report
    assert "Fair pairs: 1 of 2." in report
    assert "OPENAI" not in report


def test_compare_renderer_names_the_live_failure_shape():
    expected = {
        "status": "NEEDS_CLARIFICATION",
        "sku": None,
        "quantity": 60,
        "missing_fields": ["length_ft"],
        "substitution_used": False,
        "rationale": "",
    }
    proposed = {
        "status": "NEEDS_REVIEW",
        "sku": None,
        "quantity": 60,
        "missing_fields": [],
        "substitution_used": False,
        "rationale": "Out of stock.",
    }
    report = render_comparison(
        _document("quote-decision-v1", [_saved("case-2-missing-lumber-dimension", "baseline", "FAIL", proposed, expected)]),
        _document("quote-decision-v2", [_saved("case-2-missing-lumber-dimension", "baseline", "PASS", expected, expected)]),
    )
    assert "unnecessary human review" in report
    assert "missing clarification" in report


def _expanded(catalog):
    _, development = load_validated_dataset(DATA / "catalog.json", DATA / "development_scenarios.json")
    _, heldout = load_validated_dataset(DATA / "catalog.json", DATA / "heldout_scenarios.json")
    assert catalog.get("PLY-23-32-4X8") is not None
    return development, heldout


def _body(decision: Decision, rationale: str, quantity: int | None = None) -> str:
    return json.dumps(
        {
            "status": decision.status.value,
            "sku": decision.sku,
            "quantity": decision.quantity if quantity is None else quantity,
            "missing_fields": list(decision.missing_fields),
            "substitution_used": decision.substitution_used,
            "rationale": rationale,
        }
    )


class _Script:
    def __init__(self, raw_by_request: dict[str, str]) -> None:
        self.model_name = "fake-model"
        self.raw_by_request = raw_by_request
        self.messages: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        request = json.loads(messages[1]["content"])["customer_request"]
        return self.raw_by_request[request]


def _script(raw_by_request: dict[str, str]) -> _Script:
    return _Script(raw_by_request)


def _document(version: str, results: list[dict]) -> dict:
    return {
        "prompt_version": version,
        "model_name": "gpt-4o-mini",
        "temperature": 0,
        "results": results,
    }


def _row(scenario_id: str, split: str, outcome: str, model_input: dict, status: str) -> dict:
    decision = {
        "status": status,
        "sku": None,
        "quantity": 40,
        "missing_fields": ["length_ft"] if status == "NEEDS_CLARIFICATION" else [],
        "substitution_used": False,
        "rationale": "scripted",
    }
    return _saved(scenario_id, split, outcome, decision, decision, model_input)


def _saved(
    scenario_id: str,
    split: str,
    outcome: str,
    parsed: dict,
    expected: dict,
    model_input: dict | None = None,
) -> dict:
    categories = []
    if outcome == "FAIL" and parsed.get("status") == "NEEDS_REVIEW" and expected.get("status") == "NEEDS_CLARIFICATION":
        categories = ["unnecessary_human_escalation", "missing_clarification"]
    return {
        "scenario_id": scenario_id,
        "model_name": "gpt-4o-mini",
        "prompt_version": "quote-decision-v1",
        "split": split,
        "temperature": 0,
        "outcome": outcome,
        "failure_categories": categories,
        "parsed_decision": parsed,
        "expected_decision": expected,
        "model_input": model_input or {"customer_request": scenario_id},
        "reasons": ["scripted"],
        "raw_response": "{}",
    }


def test_default_data_dir_still_sees_the_new_files():
    data_dir = default_data_dir()
    assert (data_dir / "scenarios.json").is_file()
    assert (data_dir / "development_scenarios.json").is_file()
    assert (data_dir / "heldout_scenarios.json").is_file()
