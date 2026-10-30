"""Score the catalog decision that follows an extraction, not a model quote.

The model sees the customer sentence. ``decide`` builds the rule inputs from
that extraction and the catalog. ``evaluate`` then scores the decision against
the hand-labeled expected result. Those labels stay out of both the prompt and
``decide``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from quote_eval.categories import (
    INVALID_MODEL_OUTPUT,
    category_count_lines,
    classify,
    format_categories,
    origin_count_lines,
    with_extraction_problem,
)
from quote_eval.decide import DerivedQuote, decide
from quote_eval.evaluator import FAIL, PASS, evaluate, format_decision
from quote_eval.extract import (
    EXTRACT_PROMPT_VERSION,
    EXTRACT_PROMPT_VERSION_V2,
    Extraction,
    build_extraction_messages,
    extraction_payload,
    extraction_to_dict,
    parse_extraction,
)
from quote_eval.llm import (
    ORIGIN_API,
    ORIGIN_DECISION,
    ORIGIN_NONE,
    ORIGIN_PARSE,
    TEMPERATURE,
)
from quote_eval.models import BusinessRules, Catalog, Decision, QuoteEvalError, Scenario

SHARED_RULE_NOTE = (
    "The model only extracts what the customer said. "
    "The quote is produced by correct_decision from those facts and the catalog. "
    "The score compares that quote with the hand-labeled expected result. "
    "The label was also checked with correct_decision, but from the scenario's "
    "labeled business rules. This run does not read those labels or the expected answer."
)

HELD_OUT_NOTE = (
    "Held-out scenarios have already been inspected, including the v1 and v2 prompt comparison. "
    "They are historical evidence, not untouched validation. "
    "A new unseen set is required before any comparative performance claim."
)


class Extractor(Protocol):
    model_name: str

    def generate(self, messages: list[dict[str, str]]) -> str:
        """Return the raw extraction text for one customer request."""


@dataclass(frozen=True)
class HybridRun:
    scenario_id: str
    model_name: str
    prompt_version: str
    split: str
    temperature: float
    raw_response: str | None
    extraction: Extraction | None
    rejected: tuple[str, ...]
    recovered: tuple[str, ...]
    derived_rules: BusinessRules | None
    parsed_decision: Decision | None
    expected: Decision
    outcome: str
    reasons: tuple[str, ...]
    failure_origin: str
    failure_categories: tuple[str, ...]
    model_input: dict[str, Any]


def evaluate_hybrid(
    scenarios: tuple[Scenario, ...] | list[Scenario],
    catalog: Catalog,
    model: Extractor,
    *,
    redact_secret: str | None = None,
    prompt_version: str = EXTRACT_PROMPT_VERSION_V2,
) -> tuple[HybridRun, ...]:
    """Extract, decide, and score. A bad body or a failed call is a recorded failure."""

    runs: list[HybridRun] = []
    for scenario in scenarios:
        payload = extraction_payload(scenario.customer_request)
        messages = build_extraction_messages(scenario.customer_request, prompt_version)
        try:
            raw = model.generate(messages)
        except Exception as exc:
            message = _redact(f"API failure: {exc}", redact_secret)
            runs.append(
                _failed(
                    scenario,
                    model.model_name,
                    payload,
                    raw_response=None,
                    reasons=(message or "API failure.",),
                    origin=ORIGIN_API,
                    prompt_version=prompt_version,
                )
            )
            continue
        extraction, error = parse_extraction(raw)
        if error is not None or extraction is None:
            runs.append(
                _failed(
                    scenario,
                    model.model_name,
                    payload,
                    raw_response=raw,
                    reasons=(error or "Parsing failure.",),
                    origin=ORIGIN_PARSE,
                    prompt_version=prompt_version,
                )
            )
            continue
        derived = decide(scenario.customer_request, extraction, catalog)
        evaluation = evaluate(_with_proposal(scenario, derived.decision), catalog)
        runs.append(
            _scored(
                scenario,
                model.model_name,
                payload,
                raw_response=raw,
                extraction=extraction,
                derived=derived,
                outcome=evaluation.outcome,
                reasons=evaluation.reasons,
                prompt_version=prompt_version,
            )
        )
    return tuple(runs)


def render_hybrid_report(runs: tuple[HybridRun, ...] | list[HybridRun]) -> str:
    passed = sum(1 for run in runs if run.outcome == PASS)
    failed = len(runs) - passed
    model_name = runs[0].model_name if runs else "unknown"
    lines = [
        "Quote Evaluation Lab — hybrid extraction run",
        "Independent synthetic proof of work. Not affiliated with Ventura.",
        "",
        f"Model: {model_name}",
        f"Prompt version: {runs[0].prompt_version if runs else EXTRACT_PROMPT_VERSION_V2}",
        f"Temperature: {TEMPERATURE}",
        f"Scenarios: {len(runs)}",
        "Architecture: extraction plus Python catalog rules. The model does not choose the quote status.",
        "The direct decision run sees the catalog and the substitution policy. This run sees the customer sentence.",
        "Same customer requests and the same substitution policy, different model-visible context.",
        "Comparing the two is an architecture comparison, not a test where only the prompt changes.",
        SHARED_RULE_NOTE,
        HELD_OUT_NOTE,
        "This is an exploratory evaluation. It is not a statistically reliable measurement of model accuracy.",
        "",
    ]
    for index, run in enumerate(runs, start=1):
        lines.append(f"[{index}] {run.scenario_id} — {run.outcome} [{run.failure_origin}]")
        lines.append(f"Split: {run.split}")
        if run.outcome != PASS:
            lines.append("Failure categories: " + format_categories(run.failure_categories))
        if run.rejected:
            lines.append("Ignored unsupported values: " + "; ".join(run.rejected))
        if run.recovered:
            lines.append("Read from the request: " + "; ".join(run.recovered))
        lines.append(f"Expected: {format_decision(run.expected)}")
        if run.parsed_decision is None:
            lines.append("Decision: unavailable")
        else:
            lines.append(f"Decision: {format_decision(run.parsed_decision)}")
            if run.parsed_decision.rationale:
                lines.append(f"Rule note: {run.parsed_decision.rationale}")
        if run.derived_rules is not None:
            lines.append(f"Derived rules: {_format_rules(run.derived_rules)}")
        lines.append(f"Raw response: {run.raw_response if run.raw_response is not None else '(none)'}")
        lines.append("Reasons:")
        for reason in run.reasons:
            lines.append(f"  - {reason}")
        lines.append("")
    lines.append(f"Summary: {passed} passed, {failed} failed, {len(runs)} total.")
    lines.extend(_split_lines(runs))
    lines.extend(origin_count_lines([run.failure_origin for run in runs]))
    lines.extend(category_count_lines([run.failure_categories for run in runs]))
    lines.append(
        "Extraction or evidence-validation problems are counted only when a failed case dropped a model value."
    )
    return "\n".join(lines)


def hybrid_run_to_dict(run: HybridRun) -> dict[str, Any]:
    return {
        "scenario_id": run.scenario_id,
        "model_name": run.model_name,
        "prompt_version": run.prompt_version,
        "split": run.split,
        "temperature": run.temperature,
        "failure_origin": run.failure_origin,
        "failure_categories": list(run.failure_categories),
        "outcome": run.outcome,
        "reasons": list(run.reasons),
        "raw_response": run.raw_response,
        "extraction": extraction_to_dict(run.extraction),
        "rejected": list(run.rejected),
        "recovered": list(run.recovered),
        "derived_rules": _rules_dict(run.derived_rules),
        "parsed_decision": _decision_dict(run.parsed_decision),
        "expected_decision": _decision_dict(run.expected),
        "model_input": run.model_input,
    }


def _scored(
    scenario: Scenario,
    model_name: str,
    payload: dict[str, Any],
    *,
    raw_response: str,
    extraction: Extraction,
    derived: DerivedQuote,
    outcome: str,
    reasons: tuple[str, ...],
    prompt_version: str,
) -> HybridRun:
    categories: tuple[str, ...] = ()
    if outcome != PASS:
        categories = with_extraction_problem(
            classify(scenario.expected, derived.decision), derived.rejected
        )
    return HybridRun(
        scenario_id=scenario.id,
        model_name=model_name,
        prompt_version=prompt_version,
        split=scenario.split,
        temperature=TEMPERATURE,
        raw_response=raw_response,
        extraction=extraction,
        rejected=derived.rejected,
        recovered=derived.recovered,
        derived_rules=derived.rules,
        parsed_decision=derived.decision,
        expected=scenario.expected,
        outcome=outcome,
        reasons=reasons,
        failure_origin=ORIGIN_NONE if outcome == PASS else ORIGIN_DECISION,
        failure_categories=categories,
        model_input=payload,
    )


def _failed(
    scenario: Scenario,
    model_name: str,
    payload: dict[str, Any],
    *,
    raw_response: str | None,
    reasons: tuple[str, ...],
    origin: str,
    prompt_version: str,
) -> HybridRun:
    return HybridRun(
        scenario_id=scenario.id,
        model_name=model_name,
        prompt_version=prompt_version,
        split=scenario.split,
        temperature=TEMPERATURE,
        raw_response=raw_response,
        extraction=None,
        rejected=(),
        recovered=(),
        derived_rules=None,
        parsed_decision=None,
        expected=scenario.expected,
        outcome=FAIL,
        reasons=reasons,
        failure_origin=origin,
        failure_categories=(INVALID_MODEL_OUTPUT,),
        model_input=payload,
    )


def _with_proposal(scenario: Scenario, proposed: Decision) -> Scenario:
    return Scenario(
        id=scenario.id,
        description=scenario.description,
        customer_request=scenario.customer_request,
        rules=scenario.rules,
        expected=scenario.expected,
        proposed=proposed,
        split=scenario.split,
    )


def _format_rules(rules: BusinessRules) -> str:
    primary = rules.primary_sku or "no primary"
    quantity = f"quantity {rules.quantity}" if rules.quantity is not None else "no quantity"
    substitution = "substitution allowed" if rules.substitution_allowed else "substitution not allowed"
    return f"{substitution}, {primary}, {quantity}"


def _rules_dict(rules: BusinessRules | None) -> dict[str, Any] | None:
    if rules is None:
        return None
    return {
        "substitution_allowed": rules.substitution_allowed,
        "required_fields": list(rules.required_fields),
        "provided_specs": dict(rules.provided_specs),
        "quantity": rules.quantity,
        "primary_sku": rules.primary_sku,
    }


def _decision_dict(decision: Decision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "status": decision.status.value,
        "sku": decision.sku,
        "quantity": decision.quantity,
        "missing_fields": list(decision.missing_fields),
        "substitution_used": decision.substitution_used,
        "rationale": decision.rationale,
    }


def _split_lines(runs: tuple[HybridRun, ...] | list[HybridRun]) -> list[str]:
    splits: list[str] = []
    for run in runs:
        if run.split not in splits:
            splits.append(run.split)
    lines: list[str] = []
    for split in splits:
        chosen = [run for run in runs if run.split == split]
        passed = sum(1 for run in chosen if run.outcome == PASS)
        failed = len(chosen) - passed
        lines.append(f"{split}: {passed} passed, {failed} failed, {len(chosen)} total.")
    return lines


def _redact(text: str | None, secret: str | None) -> str | None:
    if text is None or not secret or len(secret) < 8:
        return text
    return text.replace(secret, "[redacted]")


def reprocess_saved_run(path: Path, catalog: Catalog) -> str:
    """Score stored extraction bodies again. This does not call a model."""

    document = _load_saved(path)
    results = document.get("results")
    if not isinstance(results, list):
        raise QuoteEvalError(f"{path} does not contain a results list.")
    lines = [
        "Offline reprocessing of saved hybrid responses.",
        "This is not a new model evaluation and it does not call the API.",
        f"Source file: {path.name}",
        f"Original prompt recorded in the file: {document.get('prompt_version', 'unknown')}",
        "The validator and dimension reader are the current code. The model text is unchanged.",
        "",
    ]
    saved_passed = 0
    new_passed = 0
    for row in results:
        if not isinstance(row, dict):
            raise QuoteEvalError(f"{path} has a result that is not an object.")
        scenario_id = str(row.get("scenario_id", "unknown"))
        request = _saved_request(row, scenario_id)
        expected = row.get("expected_decision")
        saved_outcome = str(row.get("outcome", "unknown"))
        if saved_outcome == PASS:
            saved_passed += 1
        raw = row.get("raw_response")
        if not isinstance(raw, str):
            lines.append(f"{scenario_id}: saved {saved_outcome} -> reprocessed FAIL (no raw response)")
            lines.append("")
            continue
        extraction, error = parse_extraction(raw)
        if error is not None or extraction is None:
            lines.append(
                f"{scenario_id}: saved {saved_outcome} -> reprocessed FAIL (the saved body still does not parse)"
            )
            lines.append("")
            continue
        derived = decide(request, extraction, catalog)
        new_outcome = PASS if _same_decision(derived.decision, expected) else FAIL
        if new_outcome == PASS:
            new_passed += 1
        lines.append(
            f"{scenario_id}: saved {saved_outcome} -> reprocessed {new_outcome}"
        )
        lines.append(f"  Request: {request}")
        lines.append(f"  Decision: {format_decision(derived.decision)}")
        if isinstance(expected, dict):
            lines.append(
                "  Expected: "
                + ", ".join(
                    str(expected.get(key))
                    for key in ("status", "sku", "quantity", "missing_fields", "substitution_used")
                )
            )
        if derived.rejected:
            lines.append("  Ignored: " + "; ".join(derived.rejected))
        if derived.recovered:
            lines.append("  Read from the request: " + "; ".join(derived.recovered))
        lines.append("")
    total = len(results)
    lines.append(
        f"Saved summary: {saved_passed} passed, {total - saved_passed} failed, {total} total."
    )
    lines.append(
        f"Reprocessed summary: {new_passed} passed, {total - new_passed} failed, {total} total."
    )
    lines.append("Offline reprocessing only. These counts are not a new model score.")
    return "\n".join(lines)


def _load_saved(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise QuoteEvalError(f"File not found: {path}.")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QuoteEvalError(f"Invalid JSON in {path}: {exc.msg}.") from exc
    if not isinstance(loaded, dict):
        raise QuoteEvalError(f"{path} must be a JSON object.")
    return loaded


def _saved_request(row: dict[str, Any], scenario_id: str) -> str:
    model_input = row.get("model_input")
    if not isinstance(model_input, dict):
        raise QuoteEvalError(f"{scenario_id} has no model input.")
    request = model_input.get("customer_request")
    if not isinstance(request, str) or not request.strip():
        raise QuoteEvalError(f"{scenario_id} has no customer request.")
    return request


def _same_decision(decision: Decision, expected: object) -> bool:
    if not isinstance(expected, dict):
        return False
    missing = expected.get("missing_fields")
    if not isinstance(missing, list):
        missing = []
    return (
        decision.status.value == expected.get("status")
        and decision.sku == expected.get("sku")
        and decision.quantity == expected.get("quantity")
        and list(decision.missing_fields) == sorted(str(item) for item in missing)
        and decision.substitution_used is expected.get("substitution_used")
    )
