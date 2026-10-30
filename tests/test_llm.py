"""Live scoring uses fake model output. No test in this file calls the network."""

import json
from dataclasses import replace

from quote_eval.evaluator import PASS, FAIL, evaluate
from quote_eval.llm import (
    ORIGIN_API,
    ORIGIN_DECISION,
    ORIGIN_NONE,
    ORIGIN_PARSE,
    OpenAIQuoteModel,
    evaluate_with_model,
    model_run_to_dict,
    parse_model_response,
)
from quote_eval.model_input import PROMPT_VERSION, build_messages
from quote_eval.models import Decision

SECRET = "sk-test-secret-value"


class ScriptedModel:
    def __init__(self, raw_by_request: dict[str, str] | None = None, *, error: Exception | None = None):
        self.model_name = "fake-model"
        self.raw_by_request = raw_by_request or {}
        self.error = error
        self.messages: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        request = json.loads(messages[1]["content"])["customer_request"]
        return self.raw_by_request[request]


def test_correct_model_decision_passes(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    run = _one(catalog, scenario, _body(scenario.expected, "Plywood matches the request."))
    direct = evaluate(_swap(scenario, run.parsed_decision), catalog)
    assert run.outcome == PASS
    assert run.failure_origin == ORIGIN_NONE
    assert run.reasons == direct.reasons
    assert run.prompt_version == PROMPT_VERSION
    assert run.model_name == "fake-model"
    assert run.parsed_decision is not None
    assert run.parsed_decision.sku == "PLY-23-32-4X8"


def test_missing_dimension_is_a_decision_failure(catalog, by_id):
    scenario = by_id["case-2-missing-lumber-dimension"]
    guessed = scenario.proposed
    run = _one(catalog, scenario, _body(guessed, "Assuming 8 feet."))
    direct = evaluate(scenario, catalog)
    assert run.outcome == FAIL
    assert run.failure_origin == ORIGIN_DECISION
    assert run.reasons == direct.reasons
    assert any("did not specify" in reason for reason in run.reasons)
    assert not any(reason.startswith("Parsing failure") for reason in run.reasons)


def test_wrong_quantity_is_a_decision_failure(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    proposed = replace(scenario.expected, quantity=119, rationale="Short by one sheet.")
    run = _one(catalog, scenario, _body(proposed, "Short by one sheet."))
    assert run.outcome == FAIL
    assert run.failure_origin == ORIGIN_DECISION
    assert any("Quantity is 119; expected 120." == reason for reason in run.reasons)


def test_invented_sku_is_a_decision_failure(catalog, by_id):
    scenario = by_id["case-5-product-not-found"]
    run = _one(catalog, scenario, _body(scenario.proposed, "Using AX99."))
    assert run.outcome == FAIL
    assert run.failure_origin == ORIGIN_DECISION
    text = " ".join(run.reasons)
    assert "not in the catalog" in text
    assert "fabricated" in text


def test_unauthorized_substitution_is_a_decision_failure(catalog, by_id):
    scenario = by_id["case-3-substitution-not-allowed"]
    run = _one(catalog, scenario, _body(scenario.proposed, "Quoted an 8-foot substitute."))
    assert run.outcome == FAIL
    assert run.failure_origin == ORIGIN_DECISION
    assert any("Substitution is not allowed" in reason for reason in run.reasons)


def test_invalid_model_response_is_a_parse_failure(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    model = ScriptedModel({scenario.customer_request: "not json"})
    run = evaluate_with_model((scenario,), catalog, model)[0]
    assert run.outcome == FAIL
    assert run.failure_origin == ORIGIN_PARSE
    assert run.parsed_decision is None
    assert run.raw_response == "not json"
    assert run.reasons[0].startswith("Parsing failure:")

    missing, error = parse_model_response('{"status": "READY_TO_QUOTE"}')
    assert missing is None
    assert error is not None
    assert "missing" in error


def test_api_failure_is_recorded_and_later_scenarios_continue(catalog, by_id):
    first = by_id["case-1-correct-catalog-match"]
    second = by_id["case-4-approved-substitution"]

    class Flaky:
        model_name = "fake-model"

        def generate(self, messages: list[dict[str, str]]) -> str:
            request = json.loads(messages[1]["content"])["customer_request"]
            if request == first.customer_request:
                raise RuntimeError(f"connection dropped for {SECRET}")
            return _body(second.expected, "Approved substitute is in stock.")

    runs = evaluate_with_model((first, second), catalog, Flaky(), redact_secret=SECRET)
    assert runs[0].outcome == FAIL
    assert runs[0].failure_origin == ORIGIN_API
    assert runs[0].raw_response is None
    assert runs[0].parsed_decision is None
    assert SECRET not in runs[0].reasons[0]
    assert "[redacted]" in runs[0].reasons[0]
    assert runs[1].outcome == PASS
    assert runs[1].failure_origin == ORIGIN_NONE


def test_saved_record_keeps_the_prompt_and_hides_the_key(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]
    run = _one(catalog, scenario, _body(scenario.expected, "Ready to quote."))
    document = json.dumps(model_run_to_dict(run))
    assert SECRET not in document
    assert "api_key" not in json.loads(document)
    saved = json.loads(document)
    assert saved["prompt_version"] == PROMPT_VERSION
    assert saved["model_name"] == "fake-model"
    assert saved["raw_response"]
    assert saved["parsed_decision"]["sku"] == "PLY-23-32-4X8"
    assert saved["failure_origin"] == ORIGIN_NONE
    assert "primary_sku" not in saved["model_input"]
    assert saved["expected_decision"]["sku"] == "PLY-23-32-4X8"


def test_openai_adapter_sends_structured_output_without_labels(catalog, by_id):
    scenario = by_id["case-2-missing-lumber-dimension"]
    captured: dict[str, object] = {}

    class Completions:
        def create(self, **kwargs: object) -> object:
            captured.update(kwargs)
            message = type("Message", (), {"content": _body(scenario.expected, "Need the length."), "refusal": None})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class Client:
        def __init__(self) -> None:
            self.chat = type("Chat", (), {"completions": Completions()})()

    model = OpenAIQuoteModel(api_key=SECRET, model="gpt-test", client=Client())
    raw = model.generate(build_messages(scenario, catalog))
    parsed, error = parse_model_response(raw)
    assert error is None
    assert parsed is not None
    assert parsed.status.value == "NEEDS_CLARIFICATION"
    assert captured["model"] == "gpt-test"
    response_format = captured["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    blob = json.dumps(captured["messages"], ensure_ascii=False)
    assert SECRET not in blob
    assert scenario.id not in blob
    assert scenario.description not in blob
    assert scenario.proposed.rationale not in blob
    assert "primary_sku" not in blob
    assert SECRET not in repr(model)


def test_empty_model_body_is_an_api_failure(catalog, by_id):
    scenario = by_id["case-1-correct-catalog-match"]

    class EmptyClient:
        def __init__(self) -> None:
            message = type("Message", (), {"content": "  ", "refusal": None})()
            choice = type("Choice", (), {"message": message})()
            response = type("Response", (), {"choices": [choice]})()

            class Completions:
                def create(self, **kwargs: object) -> object:
                    return response

            self.chat = type("Chat", (), {"completions": Completions()})()

    model = OpenAIQuoteModel(api_key=SECRET, model="gpt-test", client=EmptyClient())
    runs = evaluate_with_model((scenario,), catalog, model, redact_secret=SECRET)
    assert runs[0].failure_origin == ORIGIN_API
    assert "empty response" in runs[0].reasons[0]


def _body(decision: Decision, rationale: str) -> str:
    return json.dumps(
        {
            "status": decision.status.value,
            "sku": decision.sku,
            "quantity": decision.quantity,
            "missing_fields": list(decision.missing_fields),
            "substitution_used": decision.substitution_used,
            "rationale": rationale,
        }
    )


def _swap(scenario, proposed: Decision):
    return replace(scenario, proposed=proposed)


def _one(catalog, scenario, raw: str):
    model = ScriptedModel({scenario.customer_request: raw})
    runs = evaluate_with_model((scenario,), catalog, model)
    assert model.messages
    blob = json.dumps(model.messages)
    assert scenario.id not in blob
    assert scenario.description not in blob
    assert "primary_sku" not in blob
    return runs[0]
