"""Dimension reading, evidence recovery, and safety checks. No network calls."""

import hashlib
import inspect
from pathlib import Path

import pytest

from quote_eval.cli import main
from quote_eval.decide import decide
from quote_eval.dimensions import parse_customer_request
from quote_eval.extract import EXTRACT_PROMPT, EXTRACT_PROMPT_V2, parse_extraction
from quote_eval.hybrid import reprocess_saved_run
from quote_eval.models import Decision, DecisionStatus
from quote_eval.safety import safety_issues
import quote_eval.safety as safety_module

ROOT = Path(__file__).resolve().parents[1]
V1_EXTRACT_SHA256 = "34d138e2b5721543ae7f92758e70fc4e84c18ae6ed8ecedbcb1db4877a983913"
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


def test_extraction_v1_text_is_unchanged_and_v2_does_not_quote():
    assert hashlib.sha256(EXTRACT_PROMPT.encode()).hexdigest() == V1_EXTRACT_SHA256
    for prompt in (EXTRACT_PROMPT, EXTRACT_PROMPT_V2):
        for status in ("READY_TO_QUOTE", "NEEDS_CLARIFICATION", "NEEDS_REVIEW"):
            assert status not in prompt
    assert "two-by-four" in EXTRACT_PROMPT_V2
    assert "48" in EXTRACT_PROMPT_V2


def test_lumber_cross_section_is_not_a_length():
    for sentence in (
        "Quote 40 pieces of #2 SPF 2×4 lumber.",
        "Quote 40 pieces of #2 SPF 2x4 lumber.",
        "Quote 40 pieces of #2 SPF 2 by 4 lumber.",
        "Quote 40 pieces of #2 SPF two-by-four lumber.",
        "Quote 40 pieces of #2 SPF 2✕4 lumber.",
    ):
        reading = parse_customer_request(sentence)
        assert reading.specs["thickness_in"] == 2
        assert reading.specs["width_in"] == 4
        assert "length_ft" not in reading.specs
        assert reading.quantity == 40


def test_attached_lumber_length_and_plywood_sheet():
    ten = parse_customer_request("Quote 6 pieces of #2 SPF 2×4×10 lumber.")
    assert ten.specs["length_ft"] == 10
    assert ten.specs["width_in"] == 4
    by_feet = parse_customer_request("We need 8 pieces of #2 SPF 2×4 by 10 feet.")
    assert by_feet.specs["length_ft"] == 10
    assert by_feet.quantity == 8
    sheet = parse_customer_request("Quote 15 sheets of 23/32-inch plywood sheathing, 4×8 feet.")
    assert sheet.specs["thickness_in"] == "23/32"
    assert sheet.specs["width_ft"] == 4
    assert sheet.specs["length_ft"] == 8
    assert "width_in" not in sheet.specs
    spaced = parse_customer_request("Quote 30 sheets of plywood, 4 by 8 feet.")
    assert spaced.specs["width_ft"] == 4
    assert spaced.specs["length_ft"] == 8
    assert "thickness_in" not in spaced.specs
    bare = parse_customer_request("Quote 10 sheets of plywood, 4×8.")
    assert bare.specs["width_ft"] == 4
    assert bare.specs["length_ft"] == 8


def test_numbers_keep_their_role_and_ambiguous_sizes_stay_missing():
    pieces = parse_customer_request("Quote 8 pieces of #2 SPF 2×4 lumber.")
    assert pieces.quantity == 8
    assert "length_ft" not in pieces.specs
    assert parse_customer_request("Quote 200 pieces of lumber.").quantity == 200
    assert parse_customer_request("Quote 2000 pieces of lumber.").quantity == 2000
    assert parse_customer_request("Quote 20 pieces of lumber.").quantity == 20
    assert "width_ft" not in parse_customer_request("Quote 5 boards, 4×8.").specs
    inches = parse_customer_request("Quote 5 sheets of plywood, 4×8 inches.")
    assert "width_ft" not in inches.specs
    assert "width_in" not in inches.specs
    by_three = parse_customer_request("Quote 5 pieces of 2 by 4 by 8 lumber.")
    assert by_three.specs["width_in"] == 4
    assert "length_ft" not in by_three.specs


def test_missing_evidence_can_be_recovered_only_from_the_sentence(catalog):
    request = "Please quote 40 pieces of #2 SPF 2×4 lumber for a wall."
    raw = _packed(
        {
            "product_type": "lumber",
            "grade": "#2",
            "species": "SPF",
            "thickness_in": 2,
            "width_in": 4,
            "quantity": 40,
        },
        {"product_type": "lumber", "grade": "#2", "species": "SPF", "thickness_in": "2", "quantity": "40"},
    )
    derived = decide(request, _must_parse(raw), catalog)
    assert derived.rules.provided_specs["width_in"] == 4
    assert "length_ft" not in derived.rules.provided_specs
    assert derived.decision.status.value == "NEEDS_CLARIFICATION"
    assert derived.decision.missing_fields == ("length_ft",)
    assert any(item.startswith("width_in=4") for item in derived.recovered)

    invented = _packed(
        {"length_ft": 8, "thickness_in": 2, "width_in": 4, "quantity": 40},
        {"length_ft": "8-foot", "thickness_in": "2×4", "width_in": "2×4", "quantity": "40"},
    )
    blocked = decide(request, _must_parse(invented), catalog)
    assert blocked.decision.status.value != "READY_TO_QUOTE"
    assert "length_ft" not in blocked.rules.provided_specs
    assert any(item.startswith("length_ft=8") for item in blocked.rejected)


def test_two_by_four_product_type_still_asks_for_length(catalog):
    request = "Can you quote 12 pieces of number 2 SPF two-by-four?"
    raw = _packed(
        {"product_type": "two-by-four", "grade": "number 2", "species": "SPF", "quantity": 12},
        {"product_type": "two-by-four", "grade": "number 2", "species": "SPF", "quantity": "12"},
    )
    derived = decide(request, _must_parse(raw), catalog)
    assert derived.rules.provided_specs["grade"] == "#2"
    assert derived.rules.provided_specs["thickness_in"] == 2
    assert derived.rules.provided_specs["width_in"] == 4
    assert derived.decision.status.value == "NEEDS_CLARIFICATION"
    assert derived.decision.missing_fields == ("length_ft",)
    assert derived.decision.sku is None


def test_plywood_conversion_to_inches_is_rejected(catalog):
    request = "Quote 15 sheets of 23/32-inch plywood sheathing, 4×8 feet."
    raw = _packed(
        {
            "product_type": "plywood",
            "thickness_in": "23/32",
            "width_in": 48,
            "length_ft": 8,
            "quantity": 15,
        },
        {"product_type": "plywood", "thickness_in": "23/32-inch", "quantity": "15 sheets"},
    )
    derived = decide(request, _must_parse(raw), catalog)
    assert derived.decision.status.value == "READY_TO_QUOTE"
    assert derived.decision.sku == "PLY-23-32-4X8"
    assert derived.decision.quantity == 15
    assert "width_in" not in derived.rules.provided_specs
    assert derived.rules.provided_specs["width_ft"] == 4
    assert derived.rules.provided_specs["length_ft"] == 8
    assert any(item.startswith("width_in=48") for item in derived.rejected)


def test_stock_and_substitution_still_follow_the_catalog(catalog):
    short = decide(
        "Quote 10 pieces of #2 SPF 2×4×8 lumber. Do not substitute.",
        _must_parse(
            _packed(
                {
                    "grade": "#2",
                    "species": "SPF",
                    "thickness_in": 2,
                    "width_in": 4,
                    "length_ft": 8,
                    "quantity": 10,
                    "substitution_allowed": False,
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
        ),
        catalog,
    )
    assert short.decision.status.value == "NEEDS_REVIEW"
    assert short.decision.sku is None
    assert short.decision.substitution_used is False

    approved = decide(
        "Quote 30 pieces of #2 SPF 2×4×8-foot lumber. An approved equivalent is acceptable if the original is unavailable.",
        _must_parse(
            _packed(
                {
                    "grade": "#2",
                    "species": "SPF",
                    "thickness_in": 2,
                    "width_in": 4,
                    "length_ft": 8,
                    "quantity": 30,
                    "substitution_allowed": True,
                },
                {
                    "grade": "#2",
                    "species": "SPF",
                    "thickness_in": "2",
                    "quantity": "30",
                    "substitution_allowed": "An approved equivalent is acceptable if the original is unavailable.",
                },
            )
        ),
        catalog,
    )
    assert approved.decision.status.value == "READY_TO_QUOTE"
    assert approved.decision.sku == "LUM-ALT-2X4-8"
    assert approved.decision.substitution_used is True
    alt = catalog.get("LUM-ALT-2X4-8")
    assert alt is not None
    assert approved.decision.quantity is not None
    assert approved.decision.quantity <= alt.stock
    assert "LUM-SPF-2X4-8" in alt.substitutes_for


def test_safety_checks_do_not_use_the_decider(catalog):
    assert "correct_decision" not in inspect.getsource(safety_module)
    stated = {"thickness_in": "23/32", "width_ft": 4, "length_ft": 8}
    unknown = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="AX99",
        quantity=5,
        missing_fields=(),
        substitution_used=False,
    )
    assert "unknown SKU" in " ".join(safety_issues(unknown, catalog, substitution_allowed=False, stated_specs=stated))
    missing_qty = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="PLY-23-32-4X8",
        quantity=None,
        missing_fields=(),
        substitution_used=False,
    )
    assert "no quantity" in " ".join(
        safety_issues(missing_qty, catalog, substitution_allowed=False, stated_specs=stated)
    )
    too_many = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="PLY-23-32-4X8",
        quantity=500,
        missing_fields=(),
        substitution_used=False,
    )
    assert "exceeds available stock" in " ".join(
        safety_issues(too_many, catalog, substitution_allowed=False, stated_specs=stated)
    )
    unfinished = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="LUM-SPF-2X4-10",
        quantity=8,
        missing_fields=(),
        substitution_used=False,
    )
    partial = {"grade": "#2", "species": "SPF", "thickness_in": 2, "width_in": 4}
    assert "missing length_ft" in " ".join(
        safety_issues(unfinished, catalog, substitution_allowed=False, stated_specs=partial)
    )
    swapped = Decision(
        status=DecisionStatus.READY_TO_QUOTE,
        sku="LUM-ALT-2X4-8",
        quantity=10,
        missing_fields=(),
        substitution_used=True,
    )
    full = {**partial, "length_ft": 8}
    assert "unauthorized substitution" in " ".join(
        safety_issues(swapped, catalog, substitution_allowed=False, stated_specs=full)
    )
    review = Decision(
        status=DecisionStatus.NEEDS_REVIEW,
        sku=None,
        quantity=10,
        missing_fields=(),
        substitution_used=False,
    )
    assert safety_issues(review, catalog, substitution_allowed=False, stated_specs=full) == ()


def test_saved_hybrid_responses_can_be_reprocessed_offline(catalog):
    development = ROOT / "runs" / "hybrid-development.json"
    heldout = ROOT / "runs" / "hybrid-heldout.json"
    if not development.is_file() or not heldout.is_file():
        pytest.skip("saved hybrid responses are not in this checkout")
    dev_report = reprocess_saved_run(development, catalog)
    hold_report = reprocess_saved_run(heldout, catalog)
    for report in (dev_report, hold_report):
        assert "Offline reprocessing of saved hybrid responses." in report
        assert "not a new model evaluation" in report
        assert "not a new model score" in report
    assert "Reprocessed summary: 8 passed, 0 failed, 8 total." in dev_report
    assert "Reprocessed summary: 7 passed, 0 failed, 7 total." in hold_report
    assert main(["reprocess", str(development)]) == 0


def test_reprocess_does_not_need_an_api_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = ROOT / "runs" / "hybrid-development.json"
    if not path.is_file():
        pytest.skip("saved hybrid responses are not in this checkout")
    assert main(["reprocess", str(path)]) == 0
    report = capsys.readouterr().out
    assert "Offline reprocessing" in report


def _packed(values: dict[str, object], evidence: dict[str, str]) -> str:
    import json

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
