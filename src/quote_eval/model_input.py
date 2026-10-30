"""Build the text a model is allowed to see.

The scenario still holds the labeled specs, primary SKU, expected decision,
and fixture proposal. None of those fields are copied into this payload.
The same system prompt is used for every scenario, so a case title such as
"Missing lumber dimension" cannot leak through the instructions.
"""

from __future__ import annotations

import json
from typing import Any

from quote_eval.models import Catalog, Product, QuoteEvalError, Scenario

PROMPT_VERSION = "quote-decision-v1"
PROMPT_VERSION_V2 = "quote-decision-v2"

SYSTEM_PROMPT = """You quote building products from the fictional catalog in the user message.

Decide from the customer request, the catalog, the stock counts, and the substitution policy. The user message is the whole case.

Return a structured decision with these fields:
- status: READY_TO_QUOTE, NEEDS_CLARIFICATION, or NEEDS_REVIEW
- sku: a SKU copied from the catalog, or null when you are not quoting a product
- quantity: the quantity the customer asked to buy, or null when the customer did not give one
- missing_fields: catalog spec names the customer still needs to supply, or an empty list
- substitution_used: true only when the quoted SKU is an approved substitute for the product the customer asked for
- rationale: one or two sentences explaining the choice

Rules:
- READY_TO_QUOTE requires a SKU that appears in the catalog and a quantity the customer stated.
- If the request omits a dimension that is needed to tell catalog products apart, use NEEDS_CLARIFICATION, leave sku null, and name that dimension in missing_fields. Do not guess the missing dimension.
- If no catalog product fits the request, use NEEDS_REVIEW and leave sku null. Do not invent a SKU.
- When substitution_allowed is false, do not replace the requested product with a different size, length, or brand.
- When substitution_allowed is true, quote a substitute only when the requested product does not have enough stock and that substitute lists the requested product in substitutes_for. If more than one approved substitute could be quoted, use NEEDS_REVIEW instead of choosing one.
- Set substitution_used to true only in the case where the quoted SKU is that approved substitute.
"""

SYSTEM_PROMPT_V2 = """You quote building products from the fictional catalog in the user message.

Decide from the customer request, the catalog, the stock counts, and the substitution policy. The user message is the whole case.

Return a structured decision with these fields:
- status: READY_TO_QUOTE, NEEDS_CLARIFICATION, or NEEDS_REVIEW
- sku: a SKU copied from the catalog, or null when you are not quoting a product
- quantity: the quantity the customer asked to buy, or null when the customer did not give one
- missing_fields: catalog spec names the customer still needs to supply, or an empty list
- substitution_used: true only when the quoted SKU is an approved substitute for the product the customer asked for
- rationale: one or two sentences explaining the choice

Work in this order. Do not skip ahead.

1. Specifications and quantity come first.
   Read the request and compare it with the spec names on the catalog products, such as length, thickness, width, grade, and species.
   If any spec needed to tell the products apart is missing, or the customer did not give a quantity, stop.
   Use NEEDS_CLARIFICATION, leave sku null, and list those gaps in missing_fields.
   Do this before you consider stock, substitutes, or human review.
   A missing length, thickness, width, or quantity is NEEDS_CLARIFICATION even when related products are out of stock.

2. Only after the request names the product and the quantity, look at the catalog.
   If no product fits, use NEEDS_REVIEW and leave sku null. Do not invent a SKU.
   If more than one product fits and the request does not identify which one, use NEEDS_REVIEW and leave sku null.

3. Stock and substitution come last.
   When substitution_allowed is false, quote the matching product only if it has enough stock. If it does not, use NEEDS_REVIEW and do not swap length, size, or brand.
   When substitution_allowed is true, quote an approved substitute only when the requested product does not have enough stock and exactly one in-stock product lists that product in substitutes_for. Set substitution_used to true only in that case.
   If no single approved substitute can fill the quantity, use NEEDS_REVIEW.

READY_TO_QUOTE requires a catalog SKU and a quantity the customer stated.
"""

_PROMPTS = {
    PROMPT_VERSION: SYSTEM_PROMPT,
    PROMPT_VERSION_V2: SYSTEM_PROMPT_V2,
}


def system_prompt(version: str = PROMPT_VERSION) -> str:
    try:
        return _PROMPTS[version]
    except KeyError as exc:
        choices = ", ".join(_PROMPTS)
        raise QuoteEvalError(f"Unknown prompt version {version}. Choose {choices}.") from exc


DECISION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["READY_TO_QUOTE", "NEEDS_CLARIFICATION", "NEEDS_REVIEW"],
        },
        "sku": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "quantity": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "substitution_used": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": [
        "status",
        "sku",
        "quantity",
        "missing_fields",
        "substitution_used",
        "rationale",
    ],
}

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "quote_decision",
        "strict": True,
        "schema": DECISION_JSON_SCHEMA,
    },
}


def response_format() -> dict[str, Any]:
    return _RESPONSE_FORMAT


def model_input_payload(scenario: Scenario, catalog: Catalog) -> dict[str, Any]:
    """Public case facts. This dict is the only scenario-specific model input."""

    return {
        "customer_request": scenario.customer_request,
        "substitution_allowed": scenario.rules.substitution_allowed,
        "substitution_policy": _policy_text(scenario.rules.substitution_allowed),
        "catalog": [_public_product(product) for product in catalog.products],
    }


def build_messages(
    scenario: Scenario,
    catalog: Catalog,
    prompt_version: str = PROMPT_VERSION,
) -> list[dict[str, str]]:
    payload = model_input_payload(scenario, catalog)
    return [
        {"role": "system", "content": system_prompt(prompt_version)},
        {
            "role": "user",
            "content": json.dumps(payload, indent=2, ensure_ascii=False),
        },
    ]


def _public_product(product: Product) -> dict[str, Any]:
    return {
        "sku": product.sku,
        "name": product.name,
        "summary": product.summary,
        "stock": product.stock,
        "specs": dict(product.specs),
        "substitutes_for": list(product.substitutes_for),
    }


def _policy_text(substitution_allowed: bool) -> str:
    if substitution_allowed:
        return (
            "An approved equivalent may be quoted when the product the customer asked for "
            "is unavailable. A product is an approved equivalent only when its substitutes_for "
            "list names the unavailable product. If several equivalents could apply, a person "
            "should choose."
        )
    return (
        "The customer does not allow a substitute. Quote a catalog product that fits the "
        "request, and do not swap in a different length, size, or brand."
    )
