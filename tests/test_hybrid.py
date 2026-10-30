"""Hybrid extraction plus catalog rules. Mocked responses only. No network calls."""

import json
from pathlib import Path

from quote_eval.cli import main
from quote_eval.decide import decide
from quote_eval.evaluator import load_validated_dataset
from quote_eval.extract import EXTRACT_PROMPT, build_extraction_messages, parse_extraction
from quote_eval.hybrid import HELD_OUT_NOTE, evaluate_hybrid, render_hybrid_report
from quote_eval.llm import ORIGIN_API, ORIGIN_PARSE
from quote_eval.models import Catalog, Product

ROOT = Path(__file__).resolve().parents[1]
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


def test_extraction_prompt_does_not_ask_for_a_quote_decision():
    for status in ("READY_TO_QUOTE", "NEEDS_CLARIFICATION", "NEEDS_REVIEW"):
        assert status not in EXTRACT_PROMPT
    assert "Quote 60 pieces" not in EXTRACT_PROMPT


def test_extraction_messages_hide_labels(by_id):
    scenario = by_id["case-2-missing-lumber-dimension"]
    messages = build_extraction_messages(scenario.customer_request)
    blob = json.dumps(messages)
    assert json.loads(messages[1]["content"]) == {"customer_request": scenario.customer_request}
    assert messages[0]["content"] == EXTRACT_PROMPT
    assert scenario.id not in blob
    assert scenario.description not in blob
    assert scenario.proposed.rationale not in blob
    assert "primary_sku" not in blob
    assert "catalog" not in messages[1]["content"]


def test_missing_length_is_clarified_before_stock(catalog, by_id):
    scenario = by_id["case-2-missing-lumber-dimension"]
    raw = _packed(
        {
            "product_type": "lumber",
            "grade": "#2",
            "species": "SPF",
            "thickness_in": 2,
            "width_in": 4,
            "quantity": 60,
        },
        {
            "product_type": "lumber",
            "grade": "#2",
            "species": "SPF",
            "thickness_in": "2×4",
            "width_in": "2×4",
            "quantity": "60 pieces",
        },
    )
    run = evaluate_hybrid((scenario,), catalog, _script({scenario.customer_request: raw}))[0]
    assert run.outcome == "PASS"
    assert run.parsed_decision is not None
    assert run.parsed_decision.status.value == "NEEDS_CLARIFICATION"
    assert run.parsed_decision.sku is None
    assert run.parsed_decision.missing_fields == ("length_ft",)
    assert "stock and substitutes were not considered" in run.parsed_decision.rationale


def test_hallucinated_length_is_ignored(catalog, by_id):
    scenario = by_id["case-2-missing-lumber-dimension"]
    raw = _packed(
        {
            "grade": "#2",
            "species": "SPF",
            "thickness_in": 2,
            "width_in": 4,
            "length_ft": 8,
            "quantity": 60,
        },
        {
            "grade": "#2",
            "species": "SPF",
            "thickness_in": "2×4",
            "width_in": "2×4",
            "length_ft": "2×4",
            "quantity": "60",
        },
    )
    run = evaluate_hybrid((scenario,), catalog, _script({scenario.customer_request: raw}))[0]
    assert run.outcome == "PASS"
    assert run.parsed_decision is not None
    assert run.parsed_decision.status.value == "NEEDS_CLARIFICATION"
    assert run.parsed_decision.sku is None
    assert any(item.startswith("length_ft=8") for item in run.rejected)


def test_invented_quantity_is_ignored(catalog):
    _, development = load_validated_dataset(
        ROOT / "data" / "catalog.json", ROOT / "data" / "development_scenarios.json"
    )
    scenario = next(item for item in development if item.id == "dev-missing-quantity")
    raw = _packed(
        {
            "product_type": "plywood",
            "thickness_in": "23/32",
            "width_ft": 4,
            "length_ft": 8,
            "quantity": 15,
        },
        {
            "product_type": "plywood",
            "thickness_in": "23/32-inch",
            "width_ft": "4×8",
            "length_ft": "4×8",
            "quantity": "15 sheets",
        },
    )
    run = evaluate_hybrid((scenario,), catalog, _script({scenario.customer_request: raw}))[0]
    assert run.outcome == "PASS"
    assert run.parsed_decision is not None
    assert run.parsed_decision.quantity is None
    assert run.parsed_decision.sku is None
    assert run.parsed_decision.missing_fields == ("quantity",)
    assert any(item.startswith("quantity=15") for item in run.rejected)


def test_grade_words_do_not_invent_a_dimension(catalog):
    request = "Quote 12 pieces of number 2 SPF lumber."
    raw = _packed(
        {"grade": "#2", "species": "SPF", "thickness_in": 2, "quantity": 12},
        {"grade": "number 2", "species": "SPF", "thickness_in": "number 2", "quantity": "12"},
    )
    derived = decide(request, _must_parse(raw), catalog)
    assert derived.decision.sku is None
    assert "thickness_in" in derived.decision.missing_fields or any(
        item.startswith("thickness_in=2") for item in derived.rejected
    )
    assert any(item.startswith("thickness_in=2") for item in derived.rejected)


def test_unknown_model_needs_review_and_a_quote_body_is_rejected(catalog, by_id):
    scenario = by_id["case-5-product-not-found"]
    raw = _packed(
        {"model": "AX99", "quantity": 5},
        {"model": "AX99", "quantity": "5"},
    )
    run = evaluate_hybrid((scenario,), catalog, _script({scenario.customer_request: raw}))[0]
    assert run.outcome == "PASS"
    assert run.parsed_decision is not None
    assert run.parsed_decision.status.value == "NEEDS_REVIEW"
    assert run.parsed_decision.sku is None

    quote_body = json.dumps(
        {
            "status": "READY_TO_QUOTE",
            "sku": "AX99",
            "quantity": 5,
            "missing_fields": [],
            "substitution_used": False,
            "rationale": "Invented.",
        }
    )
    failed = evaluate_hybrid((scenario,), catalog, _script({scenario.customer_request: quote_body}))[0]
    assert failed.outcome == "FAIL"
    assert failed.failure_origin == ORIGIN_PARSE
    assert failed.failure_categories == ("invalid_model_output",)
    assert failed.parsed_decision is None


def test_ambiguous_matches_are_not_quoted():
    catalog = Catalog(
        (
            Product("BOARD-A", "Board", "Plain board", 10, {"width_ft": 4, "length_ft": 8}, ()),
            Product("BOARD-B", "Board", "Plain board", 10, {"width_ft": 4, "length_ft": 8}, ()),
        )
    )
    request = "Quote 2 pieces of board, 4 by 8 feet."
    raw = _packed(
        {"product_type": "board", "width_ft": 4, "length_ft": 8, "quantity": 2},
        {"product_type": "board", "width_ft": "4 by 8", "length_ft": "4 by 8", "quantity": "2 pieces"},
    )
    derived = decide(request, _must_parse(raw), catalog)
    assert derived.decision.status.value == "NEEDS_REVIEW"
    assert derived.decision.sku is None
    assert derived.rules.primary_sku is None


def test_substitute_tie_break_uses_the_catalog_not_a_labeled_primary(catalog, by_id):
    scenario = by_id["case-4-approved-substitution"]
    raw = _packed(
        {
            "grade": "#2",
            "species": "SPF",
            "thickness_in": 2,
            "width_in": 4,
            "length_ft": 8,
            "quantity": 25,
            "substitution_allowed": True,
        },
        {
            "grade": "#2",
            "species": "SPF",
            "thickness_in": "2×4×8-foot",
            "width_in": "2×4×8-foot",
            "length_ft": "2×4×8-foot",
            "quantity": "25",
            "substitution_allowed": "An approved equivalent is acceptable if the original is unavailable.",
        },
    )
    derived = decide(scenario.customer_request, _must_parse(raw), catalog)
    assert derived.rules.primary_sku == "LUM-SPF-2X4-8"
    assert derived.decision.status.value == "READY_TO_QUOTE"
    assert derived.decision.sku == "LUM-ALT-2X4-8"
    assert derived.decision.substitution_used is True

    denied = _packed(
        {
            "grade": "#2",
            "species": "SPF",
            "thickness_in": 2,
            "width_in": 4,
            "length_ft": 8,
            "quantity": 10,
            "substitution_allowed": True,
        },
        {
            "grade": "#2",
            "species": "SPF",
            "thickness_in": "2×4×8",
            "width_in": "2×4×8",
            "length_ft": "2×4×8",
            "quantity": "10",
            "substitution_allowed": "Do not substitute.",
        },
    )
    blocked = decide(
        "Quote 10 pieces of #2 SPF 2×4×8 lumber. Do not substitute.",
        _must_parse(denied),
        catalog,
    )
    assert blocked.decision.status.value == "NEEDS_REVIEW"
    assert blocked.decision.sku is None
    assert blocked.decision.substitution_used is False
    assert any(item.startswith("substitution_allowed=true") for item in blocked.rejected)


def test_quantity_above_stock_is_not_approved(catalog):
    request = "Quote 500 sheets of 23/32-inch plywood, 4×8 feet."
    raw = _packed(
        {
            "product_type": "plywood",
            "thickness_in": "23/32",
            "width_ft": 4,
            "length_ft": 8,
            "quantity": 500,
        },
        {
            "product_type": "plywood",
            "thickness_in": "23/32-inch",
            "width_ft": "4×8",
            "length_ft": "4×8",
            "quantity": "500",
        },
    )
    derived = decide(request, _must_parse(raw), catalog)
    assert derived.decision.status.value == "NEEDS_REVIEW"
    assert derived.decision.sku is None
    assert derived.decision.substitution_used is False


def test_api_failure_is_redacted(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    secret = "sk-test-secret-value"

    class Boom:
        model_name = "fake-model"

        def generate(self, messages):
            raise RuntimeError(f"connection dropped for {secret}")

    run = evaluate_hybrid((scenario,), catalog, Boom(), redact_secret=secret)[0]
    assert run.outcome == "FAIL"
    assert run.failure_origin == ORIGIN_API
    assert secret not in run.reasons[0]
    assert "[redacted]" in run.reasons[0]


def test_hybrid_command_requires_a_key_and_records_the_extraction_prompt(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["hybrid"]) == 2
    assert "hybrid command was not sent" in capsys.readouterr().err

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")

    class FakeExtractor:
        def __init__(self, *, api_key: str, model: str, client=None) -> None:
            self.model_name = model

        def generate(self, messages):
            assert "READY_TO_QUOTE" not in messages[0]["content"]
            assert "catalog" not in messages[1]["content"]
            return "not json"

    monkeypatch.setattr("quote_eval.cli.OpenAIExtractor", FakeExtractor)
    output = tmp_path / "hybrid.json"
    assert main(["hybrid", "--prompt", "quote-decision-v2", "--model", "gpt-test", "--output", str(output)]) == 0
    report = capsys.readouterr().out
    assert "quote-extract-v2" in report
    assert "invalid model output" in report
    assert "not a statistically reliable measurement" in report
    assert "new unseen set" in report
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["prompt_version"] == "quote-extract-v2"
    assert saved["temperature"] == 0
    assert "sk-test-secret-value" not in output.read_text(encoding="utf-8")
    assert all("primary_sku" not in json.dumps(row["model_input"]) for row in saved["results"])
    rendered = render_hybrid_report([])
    assert HELD_OUT_NOTE.split(".")[0] in rendered or "Held-out" in report


def _packed(values: dict[str, object], evidence: dict[str, str]) -> str:
    body: dict[str, object] = {name: None for name in FIELDS}
    cited: dict[str, str | None] = {name: None for name in FIELDS}
    body.update(values)
    cited.update(evidence)
    body["evidence"] = cited
    return json.dumps(body)


def _must_parse(raw: str):
    extraction, error = parse_extraction(raw)
    assert error is None
    assert extraction is not None
    return extraction


class _Script:
    def __init__(self, raw_by_request: dict[str, str]) -> None:
        self.model_name = "fake-model"
        self.raw_by_request = raw_by_request

    def generate(self, messages: list[dict[str, str]]) -> str:
        request = json.loads(messages[1]["content"])["customer_request"]
        return self.raw_by_request[request]


def _script(raw_by_request: dict[str, str]) -> _Script:
    return _Script(raw_by_request)
