"""The model prompt is an allowlist. Private labels stay out of it."""

import json

from quote_eval.model_input import SYSTEM_PROMPT, build_messages, model_input_payload

_PUBLIC_TOP_KEYS = {
    "customer_request",
    "substitution_allowed",
    "substitution_policy",
    "catalog",
}
_PUBLIC_PRODUCT_KEYS = {"sku", "name", "summary", "stock", "specs", "substitutes_for"}
_PRIVATE_KEYS = {
    "expected",
    "proposed",
    "primary_sku",
    "provided_specs",
    "required_fields",
    "missing_fields",
    "business_rules",
    "description",
    "rules",
    "outcome",
    "reasons",
}


def test_payload_uses_only_public_fields(catalog, scenarios):
    for scenario in scenarios:
        payload = model_input_payload(scenario, catalog)
        assert set(payload) == _PUBLIC_TOP_KEYS
        assert payload["customer_request"] == scenario.customer_request
        assert payload["substitution_allowed"] is scenario.rules.substitution_allowed
        assert [product["sku"] for product in payload["catalog"]] == [
            product.sku for product in catalog.products
        ]
        for product in payload["catalog"]:
            assert set(product) == _PUBLIC_PRODUCT_KEYS
        assert _walk_keys(payload).isdisjoint(_PRIVATE_KEYS)


def test_messages_omit_labels_fixture_answers_and_case_titles(catalog, scenarios):
    assert "OPENAI_API_KEY" not in SYSTEM_PROMPT
    for scenario in scenarios:
        messages = build_messages(scenario, catalog)
        assert [message["role"] for message in messages] == ["system", "user"]
        assert messages[0]["content"] == SYSTEM_PROMPT
        blob = json.dumps(messages, ensure_ascii=False)
        assert scenario.id not in blob
        assert scenario.description not in blob
        assert scenario.proposed.rationale not in blob
        user = json.loads(messages[1]["content"])
        assert _walk_keys(user).isdisjoint(_PRIVATE_KEYS)
        user_text = messages[1]["content"]
        for status in ("READY_TO_QUOTE", "NEEDS_CLARIFICATION", "NEEDS_REVIEW", "PASS", "FAIL"):
            assert status not in user_text
        assert scenario.rules.primary_sku is None or f'"primary_sku": "{scenario.rules.primary_sku}"' not in user_text


def test_system_prompt_is_identical_for_every_scenario(catalog, scenarios):
    prompts = {build_messages(scenario, catalog)[0]["content"] for scenario in scenarios}
    assert prompts == {SYSTEM_PROMPT}
    for scenario in scenarios:
        assert scenario.id not in SYSTEM_PROMPT
        assert scenario.description not in SYSTEM_PROMPT
        assert scenario.customer_request not in SYSTEM_PROMPT
        assert scenario.proposed.rationale not in SYSTEM_PROMPT


def test_catalog_stock_and_substitutes_are_visible(catalog, scenarios):
    payload = model_input_payload(scenarios[0], catalog)
    by_sku = {product["sku"]: product for product in payload["catalog"]}
    assert by_sku["PLY-23-32-4X8"]["stock"] == 200
    assert by_sku["LUM-SPF-2X4-8"]["stock"] == 0
    assert by_sku["LUM-ALT-2X4-8"]["substitutes_for"] == ["LUM-SPF-2X4-8"]
    assert by_sku["LUM-SPF-2X4-10"]["stock"] == 100


def _walk_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key))
            found.update(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_walk_keys(item))
    return found
