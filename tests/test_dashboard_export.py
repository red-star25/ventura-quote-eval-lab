"""The dashboard export copies saved runs and does not invent scores."""

import json
from pathlib import Path

import pytest

from quote_eval.dashboard_export import build_dataset, default_paths

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
DIRECT = RUNS / "final-direct-v1.json"
HYBRID = RUNS / "final-hybrid-v2.json"


pytestmark = pytest.mark.skipif(
    not DIRECT.is_file() or not HYBRID.is_file(),
    reason="Saved final_validation runs are local and are not part of the git tree.",
)


def test_export_matches_saved_runs_and_hides_secrets():
    paths = default_paths(ROOT)
    output = paths.pop("output_path")
    dataset = build_dataset(**paths)
    direct = json.loads(DIRECT.read_text(encoding="utf-8"))
    hybrid = json.loads(HYBRID.read_text(encoding="utf-8"))
    scenarios = json.loads((ROOT / "data" / "final_validation_scenarios.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))

    assert dataset["meta"]["modelName"] == direct["model_name"] == hybrid["model_name"]
    assert dataset["meta"]["temperature"] == direct["temperature"] == hybrid["temperature"]
    assert dataset["meta"]["directPrompt"] == direct["prompt_version"]
    assert dataset["meta"]["hybridPrompt"] == hybrid["prompt_version"]
    assert dataset["meta"]["scenarioCount"] == 20
    assert [item["sku"] for item in dataset["catalog"]] == [item["sku"] for item in catalog["products"]]
    assert [item["stock"] for item in dataset["catalog"]] == [item["stock"] for item in catalog["products"]]

    direct_rows = {row["scenario_id"]: row for row in direct["results"]}
    hybrid_rows = {row["scenario_id"]: row for row in hybrid["results"]}
    assert [item["id"] for item in dataset["scenarios"]] == [item["id"] for item in scenarios["scenarios"]]
    assert len(dataset["scenarios"]) == 20
    featured = next(item for item in dataset["scenarios"] if item["id"] == "final-insufficient-alt")
    assert featured["direct"]["decision"]["sku"] == "LUM-ALT-2X4-8"
    assert featured["direct"]["decision"]["quantity"] == 140
    assert featured["direct"]["outcome"] == "FAIL"
    assert "unsafe_quote_approval" in featured["direct"]["failureCategories"]
    assert featured["hybrid"]["outcome"] == "PASS"
    assert featured["customerRequest"] == direct_rows["final-insufficient-alt"]["model_input"]["customer_request"]

    for item in dataset["scenarios"]:
        left = direct_rows[item["id"]]
        right = hybrid_rows[item["id"]]
        assert item["customerRequest"] == left["model_input"]["customer_request"]
        assert item["direct"]["outcome"] == left["outcome"]
        assert item["direct"]["reasons"] == left["reasons"]
        assert item["direct"]["failureCategories"] == left["failure_categories"]
        assert item["direct"]["modelName"] == left["model_name"]
        assert item["direct"]["promptVersion"] == left["prompt_version"]
        assert item["direct"]["decision"]["status"] == left["parsed_decision"]["status"]
        assert item["direct"]["decision"]["sku"] == left["parsed_decision"]["sku"]
        assert item["direct"]["decision"]["quantity"] == left["parsed_decision"]["quantity"]
        assert item["direct"]["decision"]["rationale"] == (left["parsed_decision"]["rationale"] or "")
        assert item["hybrid"]["outcome"] == right["outcome"]
        assert item["hybrid"]["reasons"] == right["reasons"]
        assert item["hybrid"]["extraction"] == right["extraction"]
        assert item["hybrid"]["recovered"] == right["recovered"]
        assert item["hybrid"]["rejected"] == right["rejected"]
        assert item["expected"]["status"] == left["expected_decision"]["status"]
        assert "raw_response" not in json.dumps(item)
        assert "model_input" not in item["direct"]

    blob = json.dumps(dataset).lower()
    for marker in ("openai_api_key", "sk-", "api_key", "bearer "):
        assert marker not in blob
    assert "/users/" not in blob

    if output.is_file():
        committed = json.loads(output.read_text(encoding="utf-8"))
        assert committed == dataset
