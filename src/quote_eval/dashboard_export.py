"""Build the static dashboard dataset from saved runs.

Reads the frozen scenarios, the fictional catalog, and two saved evaluation
files. Writes nothing except when called as a script. Does not call a model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quote_eval.dimensions import substitution_from_text

_SECRET_MARKERS = ("openai_api_key", "sk-", "api_key", "bearer ")


def build_dataset(
    *,
    catalog_path: Path,
    scenarios_path: Path,
    direct_path: Path,
    hybrid_path: Path,
) -> dict[str, Any]:
    catalog_doc = _load_object(catalog_path)
    scenario_doc = _load_object(scenarios_path)
    direct_doc = _load_object(direct_path)
    hybrid_doc = _load_object(hybrid_path)
    direct_rows = _rows_by_id(direct_doc, direct_path.name)
    hybrid_rows = _rows_by_id(hybrid_doc, hybrid_path.name)
    scenarios = scenario_doc.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(f"{scenarios_path.name} has no scenarios.")
    products = catalog_doc.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError(f"{catalog_path.name} has no products.")

    exported_scenarios: list[dict[str, Any]] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("A scenario entry is not an object.")
        scenario_id = _text(scenario.get("id"), "scenario id")
        if scenario_id not in direct_rows or scenario_id not in hybrid_rows:
            raise ValueError(f"{scenario_id} is missing from one of the saved runs.")
        direct = direct_rows.pop(scenario_id)
        hybrid = hybrid_rows.pop(scenario_id)
        _same_request(scenario_id, scenario, direct, hybrid)
        exported_scenarios.append(_scenario(scenario, direct, hybrid))
    if direct_rows or hybrid_rows:
        extra = sorted({*direct_rows, *hybrid_rows})
        raise ValueError("Saved runs contain scenarios that are not in the frozen file: " + ", ".join(extra))

    dataset = {
        "meta": {
            "title": "Quote Evaluation Lab",
            "synthetic": True,
            "exploratory": True,
            "modelName": _same_meta(direct_doc, hybrid_doc, "model_name"),
            "temperature": _same_meta(direct_doc, hybrid_doc, "temperature"),
            "directPrompt": _text(direct_doc.get("prompt_version"), "direct prompt"),
            "hybridPrompt": _text(hybrid_doc.get("prompt_version"), "hybrid prompt"),
            "scenarioCount": len(exported_scenarios),
            "sources": [
                "data/catalog.json",
                "data/final_validation_scenarios.json",
                "runs/final-direct-v1.json",
                "runs/final-hybrid-v2.json",
            ],
        },
        "catalog": [_product(product) for product in products],
        "scenarios": exported_scenarios,
    }
    _reject_secrets(dataset)
    return dataset


def write_dataset(dataset: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def default_paths(root: Path) -> dict[str, Path]:
    return {
        "catalog_path": root / "data" / "catalog.json",
        "scenarios_path": root / "data" / "final_validation_scenarios.json",
        "direct_path": root / "runs" / "final-direct-v1.json",
        "hybrid_path": root / "runs" / "final-hybrid-v2.json",
        "output_path": root / "web" / "data" / "experiment.json",
    }


def _scenario(scenario: dict[str, Any], direct: dict[str, Any], hybrid: dict[str, Any]) -> dict[str, Any]:
    request = _text(scenario.get("customer_request"), "customer request")
    rules = scenario.get("business_rules")
    if not isinstance(rules, dict):
        raise ValueError(f"{scenario.get('id')} is missing business rules.")
    stance = substitution_from_text(request)
    spoken = "silent" if stance is None else "allowed" if stance else "forbidden"
    return {
        "id": scenario["id"],
        "description": _text(scenario.get("description"), "description"),
        "customerRequest": request,
        "substitutionStance": spoken,
        "substitutionPolicy": _policy(direct),
        "rules": {
            "substitutionAllowed": bool(rules.get("substitution_allowed")),
            "requiredFields": list(rules.get("required_fields") or []),
            "providedSpecs": dict(rules.get("provided_specs") or {}),
            "quantity": rules.get("quantity"),
            "primarySku": rules.get("primary_sku"),
        },
        "expected": _decision(direct.get("expected_decision"), required=True),
        "direct": _run(direct, include_extraction=False),
        "hybrid": _run(hybrid, include_extraction=True),
    }


def _run(row: dict[str, Any], *, include_extraction: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "outcome": _text(row.get("outcome"), "outcome"),
        "failureOrigin": _text(row.get("failure_origin"), "failure origin"),
        "failureCategories": list(row.get("failure_categories") or []),
        "reasons": list(row.get("reasons") or []),
        "decision": _decision(row.get("parsed_decision"), required=False),
        "modelName": _text(row.get("model_name"), "model name"),
        "promptVersion": _text(row.get("prompt_version"), "prompt version"),
        "temperature": row.get("temperature"),
    }
    if include_extraction:
        extraction = row.get("extraction")
        if not isinstance(extraction, dict):
            raise ValueError(f"{row.get('scenario_id')} is missing an extraction.")
        body["extraction"] = extraction
        body["rejected"] = list(row.get("rejected") or [])
        body["recovered"] = list(row.get("recovered") or [])
        derived = row.get("derived_rules")
        body["derivedRules"] = derived if isinstance(derived, dict) else None
    return body


def _decision(raw: object, *, required: bool) -> dict[str, Any] | None:
    if raw is None:
        if required:
            raise ValueError("Expected decision is missing.")
        return None
    if not isinstance(raw, dict):
        raise ValueError("A decision is not an object.")
    return {
        "status": raw.get("status"),
        "sku": raw.get("sku"),
        "quantity": raw.get("quantity"),
        "missingFields": list(raw.get("missing_fields") or []),
        "substitutionUsed": bool(raw.get("substitution_used")),
        "rationale": raw.get("rationale") or "",
    }


def _product(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A catalog product is not an object.")
    return {
        "sku": raw.get("sku"),
        "name": raw.get("name"),
        "summary": raw.get("summary"),
        "stock": raw.get("stock"),
        "specs": dict(raw.get("specs") or {}),
        "substitutesFor": list(raw.get("substitutes_for") or []),
    }


def _policy(direct: dict[str, Any]) -> str:
    model_input = direct.get("model_input")
    if not isinstance(model_input, dict):
        return ""
    policy = model_input.get("substitution_policy")
    return policy if isinstance(policy, str) else ""


def _same_request(
    scenario_id: str,
    scenario: dict[str, Any],
    direct: dict[str, Any],
    hybrid: dict[str, Any],
) -> None:
    request = scenario.get("customer_request")
    for label, row in (("direct", direct), ("hybrid", hybrid)):
        model_input = row.get("model_input")
        if not isinstance(model_input, dict) or model_input.get("customer_request") != request:
            raise ValueError(f"{scenario_id} {label} model input does not match the frozen request.")
    direct_expected = direct.get("expected_decision")
    hybrid_expected = hybrid.get("expected_decision")
    if not isinstance(direct_expected, dict) or not isinstance(hybrid_expected, dict):
        raise ValueError(f"{scenario_id} is missing an expected decision.")
    for key in ("status", "sku", "quantity", "missing_fields", "substitution_used"):
        if direct_expected.get(key) != hybrid_expected.get(key):
            raise ValueError(f"{scenario_id} expected decisions disagree between the two runs.")


def _rows_by_id(document: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    results = document.get("results")
    if not isinstance(results, list):
        raise ValueError(f"{name} has no results.")
    rows: dict[str, dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict) or not isinstance(row.get("scenario_id"), str):
            raise ValueError(f"{name} has a result without a scenario id.")
        scenario_id = row["scenario_id"]
        if scenario_id in rows:
            raise ValueError(f"{name} repeats {scenario_id}.")
        rows[scenario_id] = row
    return rows


def _same_meta(direct: dict[str, Any], hybrid: dict[str, Any], key: str) -> Any:
    left = direct.get(key)
    right = hybrid.get(key)
    if left != right:
        raise ValueError(f"The saved runs disagree on {key}: {left!r} vs {right!r}.")
    if left is None or left == "":
        raise ValueError(f"The saved runs are missing {key}.")
    return left


def _load_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"File not found: {path.name}.")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} is not a JSON object.")
    return loaded


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing {label}.")
    return value


def _reject_secrets(dataset: dict[str, Any]) -> None:
    blob = json.dumps(dataset).lower()
    for marker in _SECRET_MARKERS:
        if marker in blob:
            raise ValueError(f"Refusing to export a dataset that contains {marker!r}.")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = default_paths(root)
    output = paths.pop("output_path")
    dataset = build_dataset(**paths)
    write_dataset(dataset, output)
    print(f"Wrote {output.relative_to(root)} ({dataset['meta']['scenarioCount']} scenarios).")


if __name__ == "__main__":
    main()
