"""Call a language model and score the parsed decision with the existing checker.

Automated tests inject a fake model. The OpenAI client is constructed only for
an explicit live run that already has OPENAI_API_KEY.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from quote_eval.categories import INVALID_MODEL_OUTPUT, classify
from quote_eval.evaluator import FAIL, PASS, evaluate
from quote_eval.model_input import PROMPT_VERSION, build_messages, model_input_payload, response_format, system_prompt
from quote_eval.models import Catalog, Decision, QuoteEvalError, Scenario, decision_from_obj

DEFAULT_MODEL = "gpt-4o-mini"
TEMPERATURE = 0

ORIGIN_NONE = "none"
ORIGIN_PARSE = "parse"
ORIGIN_DECISION = "decision"
ORIGIN_API = "api"

_DECISION_FIELDS = {
    "status",
    "sku",
    "quantity",
    "missing_fields",
    "substitution_used",
    "rationale",
}


class ModelCallError(Exception):
    """The model call did not return a response body."""


class QuoteModel(Protocol):
    model_name: str

    def generate(self, messages: list[dict[str, str]]) -> str:
        """Return the raw model text for one public prompt."""


@dataclass(frozen=True)
class ModelRun:
    scenario_id: str
    model_name: str
    prompt_version: str
    raw_response: str | None
    parsed_decision: Decision | None
    outcome: str
    reasons: tuple[str, ...]
    failure_origin: str
    failure_categories: tuple[str, ...]
    model_input: dict[str, Any]
    expected: Decision
    split: str
    temperature: float


class OpenAIQuoteModel:
    """Structured-output adapter. The API key is not part of the object's repr."""

    def __init__(self, *, api_key: str, model: str = DEFAULT_MODEL, client: Any | None = None) -> None:
        self._api_key = api_key
        self.model_name = model
        self._client = client

    def __repr__(self) -> str:
        return f"OpenAIQuoteModel(model={self.model_name!r})"

    def generate(self, messages: list[dict[str, str]]) -> str:
        client = self._client if self._client is not None else _openai_client(self._api_key)
        try:
            response = client.chat.completions.create(
                model=self.model_name,
                temperature=TEMPERATURE,
                messages=messages,
                response_format=response_format(),
            )
        except ModelCallError:
            raise
        except Exception as exc:
            raise ModelCallError(f"The model request failed: {exc}") from exc
        return _message_text(response)


def evaluate_with_model(
    scenarios: tuple[Scenario, ...] | list[Scenario],
    catalog: Catalog,
    model: QuoteModel,
    *,
    redact_secret: str | None = None,
    prompt_version: str = PROMPT_VERSION,
) -> tuple[ModelRun, ...]:
    """Score every scenario. A bad response or a failed call is a recorded failure."""

    system_prompt(prompt_version)
    runs: list[ModelRun] = []
    for scenario in scenarios:
        payload = model_input_payload(scenario, catalog)
        messages = build_messages(scenario, catalog, prompt_version=prompt_version)
        try:
            raw = model.generate(messages)
        except Exception as exc:
            message = _redact(f"API failure: {exc}", redact_secret)
            runs.append(
                _run(
                    scenario,
                    model.model_name,
                    payload,
                    raw_response=None,
                    parsed=None,
                    outcome=FAIL,
                    reasons=(message,),
                    origin=ORIGIN_API,
                    prompt_version=prompt_version,
                )
            )
            continue
        raw = _redact(raw, redact_secret) or ""
        parsed, parse_error = parse_model_response(raw)
        if parsed is None:
            reason = parse_error or "Parsing failure: the model response could not be read."
            runs.append(
                _run(
                    scenario,
                    model.model_name,
                    payload,
                    raw_response=raw,
                    parsed=None,
                    outcome=FAIL,
                    reasons=(_redact(reason, redact_secret) or reason,),
                    origin=ORIGIN_PARSE,
                    prompt_version=prompt_version,
                )
            )
            continue
        evaluation = evaluate(_with_proposal(scenario, parsed), catalog)
        origin = ORIGIN_NONE if evaluation.outcome == PASS else ORIGIN_DECISION
        runs.append(
            _run(
                scenario,
                model.model_name,
                payload,
                raw_response=raw,
                parsed=parsed,
                outcome=evaluation.outcome,
                reasons=evaluation.reasons,
                origin=origin,
                prompt_version=prompt_version,
            )
        )
    return tuple(runs)


def parse_model_response(raw: str) -> tuple[Decision | None, str | None]:
    """Validate a model body before it can reach the evaluator."""

    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"Parsing failure: the model response is not valid JSON ({exc.msg})."
    if not isinstance(loaded, dict):
        return None, "Parsing failure: the model response must be a JSON object."
    missing = sorted(_DECISION_FIELDS - set(loaded))
    extra = sorted(set(loaded) - _DECISION_FIELDS)
    if missing:
        return None, f"Parsing failure: the model response is missing {', '.join(missing)}."
    if extra:
        return None, (
            "Parsing failure: the model response has unsupported fields: " + ", ".join(extra) + "."
        )
    try:
        decision = decision_from_obj(loaded, source="model response")
    except QuoteEvalError as exc:
        return None, f"Parsing failure: {exc}"
    if not decision.rationale.strip():
        return None, "Parsing failure: rationale must explain the decision in a sentence or two."
    return decision, None


def model_run_to_dict(run: ModelRun) -> dict[str, Any]:
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
        "parsed_decision": _decision_dict(run.parsed_decision),
        "expected_decision": _decision_dict(run.expected),
        "model_input": run.model_input,
    }


def _run(
    scenario: Scenario,
    model_name: str,
    payload: dict[str, Any],
    *,
    raw_response: str | None,
    parsed: Decision | None,
    outcome: str,
    reasons: tuple[str, ...],
    origin: str,
    prompt_version: str,
) -> ModelRun:
    if origin in {ORIGIN_PARSE, ORIGIN_API} or parsed is None:
        categories: tuple[str, ...] = (INVALID_MODEL_OUTPUT,)
    elif outcome == PASS:
        categories = ()
    else:
        categories = classify(scenario.expected, parsed)
    return ModelRun(
        scenario_id=scenario.id,
        model_name=model_name,
        prompt_version=prompt_version,
        raw_response=raw_response,
        parsed_decision=parsed,
        outcome=outcome,
        reasons=reasons,
        failure_origin=origin,
        failure_categories=categories,
        model_input=payload,
        expected=scenario.expected,
        split=scenario.split,
        temperature=TEMPERATURE,
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


def _message_text(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        raise ModelCallError("The model returned no choices.")
    message = choices[0].message
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise ModelCallError(f"The model refused the request: {refusal}")
    content = getattr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ModelCallError("The model returned an empty response.")
    return content


def _openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ModelCallError(
            "The openai package is not installed. Install this project's dependencies before a live run."
        ) from exc
    return OpenAI(api_key=api_key, timeout=60.0)


def _redact(text: str | None, secret: str | None) -> str | None:
    if text is None or not secret or len(secret) < 8:
        return text
    return text.replace(secret, "[redacted]")
