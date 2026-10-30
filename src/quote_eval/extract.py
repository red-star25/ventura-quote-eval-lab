"""Ask a model to copy facts the customer stated. It does not quote.

The user message is only the customer sentence. Catalog rows, stock, expected
decisions, and labeled specs stay out of this prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from quote_eval.llm import TEMPERATURE, ModelCallError
from quote_eval.models import QuoteEvalError, SpecValue

EXTRACT_PROMPT_VERSION = "quote-extract-v1"
EXTRACT_PROMPT_VERSION_V2 = "quote-extract-v2"

EXTRACT_PROMPT = """You copy facts from one customer request for building materials.

Return only the facts the customer stated in that request. Use null for anything they did not state. Do not guess a length, size, quantity, grade, species, or product identifier.

Fields:
- product_type: a short product name such as plywood or lumber, or null
- grade: the grade they stated, or null
- species: the species they stated, or null
- thickness_in: thickness as an integer or a fraction such as 23/32, or null
- width_in: width in inches, or null
- width_ft: width in feet, or null
- length_ft: length in feet, or null
- quantity: how many units they asked to buy, or null
- model: a model or product identifier they stated, or null
- substitution_allowed: true if they allow a substitute, false if they forbid one, or null if they said nothing about substitutes
- evidence: one entry for every field above. When a field is not null, copy the exact words from the request that state it. When a field is null, the evidence entry is null.

Do not choose a product to sell. Do not fill a blank from general knowledge. If you cannot point to the words in the request, leave the field null.
"""

EXTRACT_PROMPT_V2 = """You copy facts from one customer request for building materials.

Return only the facts the customer stated in that request. Use null for anything they did not state. Do not guess a length, size, quantity, grade, species, or product identifier.

How to read common wording:
- 2×4, 2x4, 2 by 4, and two-by-four are lumber thickness 2 and width 4 inches. Put those in thickness_in and width_in. Do not put 2×4 in product_type, and do not invent a length from 2×4 alone.
- 2×4×8, 2×4×10, 2×4×8-foot, and 2×4 by 10 feet also state length_ft as the last number. Copy the whole phrase, such as 2×4×10-foot, into the evidence for each of those fields.
- 4×8 feet, 4×8-foot, and 4 by 8 feet on plywood are width_ft and length_ft. Do not convert feet into inches and do not write 48 for a 4-foot width.
- 23/32-inch is thickness_in as the fraction 23/32.
- A count such as 8 pieces or 15 sheets is quantity. That number is not a length.
- #2, number 2, and no. 2 are grade #2.

Fields:
- product_type: plywood or lumber, or null. Not a size.
- grade: the grade they stated, or null
- species: the species they stated, or null
- thickness_in: thickness as an integer or a fraction such as 23/32, or null
- width_in: width in inches, or null
- width_ft: width in feet, or null
- length_ft: length in feet, or null
- quantity: how many units they asked to buy, or null
- model: a model or product identifier they stated, or null
- substitution_allowed: true if they allow a substitute, false if they forbid one, or null if they said nothing about substitutes
- evidence: one entry for every field above. When a field is not null, copy the exact words from the request that state it. The same phrase may be copied for every field that phrase states. When a field is null, the evidence entry is null.

Do not choose a product to sell. Do not fill a blank from general knowledge. If you cannot point to the words in the request, leave the field null.
"""

_PROMPTS = {
    EXTRACT_PROMPT_VERSION: EXTRACT_PROMPT,
    EXTRACT_PROMPT_VERSION_V2: EXTRACT_PROMPT_V2,
}

_FIELDS = (
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
_STRING_FIELDS = {"product_type", "grade", "species", "model"}
_INTEGER_FIELDS = {"width_in", "width_ft", "length_ft", "quantity"}
_SPEC_FIELDS = ("grade", "species", "thickness_in", "width_in", "width_ft", "length_ft")

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_INTEGER = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
_NULLABLE_SPEC = {
    "anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}],
}

EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_type": _NULLABLE_STRING,
        "grade": _NULLABLE_STRING,
        "species": _NULLABLE_STRING,
        "thickness_in": _NULLABLE_SPEC,
        "width_in": _NULLABLE_INTEGER,
        "width_ft": _NULLABLE_INTEGER,
        "length_ft": _NULLABLE_INTEGER,
        "quantity": _NULLABLE_INTEGER,
        "model": _NULLABLE_STRING,
        "substitution_allowed": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        "evidence": {
            "type": "object",
            "additionalProperties": False,
            "properties": {name: _NULLABLE_STRING for name in _FIELDS},
            "required": list(_FIELDS),
        },
    },
    "required": [*_FIELDS, "evidence"],
}

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "customer_extraction",
        "strict": True,
        "schema": EXTRACTION_JSON_SCHEMA,
    },
}


@dataclass(frozen=True)
class Extraction:
    """Facts copied from the customer sentence. Null means they did not say it."""

    product_type: str | None
    grade: str | None
    species: str | None
    thickness_in: SpecValue | None
    width_in: int | None
    width_ft: int | None
    length_ft: int | None
    quantity: int | None
    model: str | None
    substitution_allowed: bool | None
    evidence: dict[str, str | None]

    def value(self, name: str) -> object:
        return getattr(self, name)

    def specs(self) -> dict[str, SpecValue]:
        found: dict[str, SpecValue] = {}
        for name in _SPEC_FIELDS:
            value = self.value(name)
            if value is not None:
                found[name] = value  # type: ignore[assignment]
        return found


def extraction_response_format() -> dict[str, Any]:
    return _RESPONSE_FORMAT


def extraction_prompt(version: str = EXTRACT_PROMPT_VERSION) -> str:
    try:
        return _PROMPTS[version]
    except KeyError as exc:
        choices = ", ".join(_PROMPTS)
        raise QuoteEvalError(f"Unknown prompt version {version}. Choose {choices}.") from exc


def extraction_payload(customer_request: str) -> dict[str, str]:
    return {"customer_request": customer_request}


def build_extraction_messages(
    customer_request: str, prompt_version: str = EXTRACT_PROMPT_VERSION
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": extraction_prompt(prompt_version)},
        {
            "role": "user",
            "content": json.dumps(extraction_payload(customer_request), ensure_ascii=False),
        },
    ]


def parse_extraction(raw: str) -> tuple[Extraction | None, str | None]:
    """Validate an extraction body. A quote decision in this body is rejected."""

    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"Parsing failure: the model response is not valid JSON ({exc.msg})."
    if not isinstance(loaded, dict):
        return None, "Parsing failure: the model response must be a JSON object."
    missing = sorted(set(_FIELDS) - set(loaded))
    if "evidence" not in loaded:
        missing.append("evidence")
    extra = sorted(set(loaded) - set(_FIELDS) - {"evidence"})
    if missing:
        return None, f"Parsing failure: the model response is missing {', '.join(missing)}."
    if extra:
        return None, (
            "Parsing failure: the model response has unsupported fields: " + ", ".join(extra) + "."
        )
    try:
        return _extraction_from_obj(loaded), None
    except QuoteEvalError as exc:
        return None, f"Parsing failure: {exc}"


class OpenAIExtractor:
    """Extraction adapter. The API key is not part of the object's repr."""

    def __init__(self, *, api_key: str, model: str, client: Any | None = None) -> None:
        self._api_key = api_key
        self.model_name = model
        self._client = client

    def __repr__(self) -> str:
        return f"OpenAIExtractor(model={self.model_name!r})"

    def generate(self, messages: list[dict[str, str]]) -> str:
        client = self._client if self._client is not None else _openai_client(self._api_key)
        try:
            response = client.chat.completions.create(
                model=self.model_name,
                temperature=TEMPERATURE,
                messages=messages,
                response_format=extraction_response_format(),
            )
        except ModelCallError:
            raise
        except Exception as exc:
            raise ModelCallError(f"The model request failed: {exc}") from exc
        return _message_text(response)


def extraction_to_dict(extraction: Extraction | None) -> dict[str, Any] | None:
    if extraction is None:
        return None
    payload: dict[str, Any] = {name: extraction.value(name) for name in _FIELDS}
    payload["evidence"] = dict(extraction.evidence)
    return payload


def _extraction_from_obj(raw: dict[str, Any]) -> Extraction:
    evidence_raw = raw.get("evidence")
    if not isinstance(evidence_raw, dict):
        raise QuoteEvalError("model response evidence must be a JSON object.")
    evidence_extra = sorted(set(evidence_raw) - set(_FIELDS))
    evidence_missing = sorted(set(_FIELDS) - set(evidence_raw))
    if evidence_missing:
        raise QuoteEvalError(
            "model response evidence is missing " + ", ".join(evidence_missing) + "."
        )
    if evidence_extra:
        raise QuoteEvalError(
            "model response evidence has unsupported fields: " + ", ".join(evidence_extra) + "."
        )
    evidence = {
        name: _optional_text(evidence_raw.get(name), f"model response evidence.{name}")
        for name in _FIELDS
    }
    values = {name: _field_value(name, raw.get(name)) for name in _FIELDS}
    return Extraction(evidence=evidence, **values)


def _field_value(name: str, value: object) -> object:
    source = f"model response {name}"
    if name in _STRING_FIELDS:
        return _optional_text(value, source)
    if name == "substitution_allowed":
        if value is None:
            return None
        if not isinstance(value, bool):
            raise QuoteEvalError(f"{source} must be true, false, or null.")
        return value
    if name == "thickness_in":
        return _optional_spec(value, source)
    if name in _INTEGER_FIELDS:
        return _optional_positive_int(value, source)
    raise QuoteEvalError(f"{source} is not an extraction field.")


def _optional_text(value: object, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise QuoteEvalError(f"{source} must be a non-empty string without surrounding space, or null.")
    return value


def _optional_spec(value: object, source: str) -> SpecValue | None:
    if value is None:
        return None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, bool) or isinstance(value, float):
        raise QuoteEvalError(f"{source} must be a string, an integer, or null.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip() and value == value.strip():
        return value
    raise QuoteEvalError(f"{source} must be a non-empty string, an integer, or null.")


def _optional_positive_int(value: object, source: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise QuoteEvalError(f"{source} must be a positive integer or null.")
    return value


def _openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ModelCallError(
            "The openai package is not installed. Install this project's dependencies before a live run."
        ) from exc
    return OpenAI(api_key=api_key, timeout=60.0)


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
