"""Malformed catalogs and scenarios stop before anything can pass."""

import json
from pathlib import Path

import pytest

from quote_eval.evaluator import load_validated_dataset
from quote_eval.models import QuoteEvalError, load_catalog, load_scenarios

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "catalog.json"
SCENARIOS_PATH = ROOT / "data" / "scenarios.json"


def test_missing_file_is_rejected(tmp_path: Path):
    with pytest.raises(QuoteEvalError, match="File not found"):
        load_catalog(tmp_path / "missing.json")


def test_invalid_json_is_rejected(tmp_path: Path):
    path = tmp_path / "catalog.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(QuoteEvalError, match="Invalid JSON"):
        load_catalog(path)


def test_duplicate_sku_is_rejected(tmp_path: Path):
    payload = _catalog()
    payload["products"].append(dict(payload["products"][0]))
    path = _write(tmp_path / "catalog.json", payload)
    with pytest.raises(QuoteEvalError, match="Duplicate SKU"):
        load_catalog(path)


def test_negative_stock_is_rejected(tmp_path: Path):
    payload = _catalog()
    payload["products"][0]["stock"] = -1
    path = _write(tmp_path / "catalog.json", payload)
    with pytest.raises(QuoteEvalError, match="stock"):
        load_catalog(path)


def test_boolean_stock_is_rejected(tmp_path: Path):
    payload = _catalog()
    payload["products"][0]["stock"] = True
    path = _write(tmp_path / "catalog.json", payload)
    with pytest.raises(QuoteEvalError, match="stock"):
        load_catalog(path)


def test_unknown_catalog_field_is_rejected(tmp_path: Path):
    payload = _catalog()
    payload["products"][0]["price"] = 10
    path = _write(tmp_path / "catalog.json", payload)
    with pytest.raises(QuoteEvalError, match="unknown fields: price"):
        load_catalog(path)


def test_substitute_target_must_exist(tmp_path: Path):
    payload = _catalog()
    payload["products"][3]["substitutes_for"] = ["LUM-DOES-NOT-EXIST"]
    path = _write(tmp_path / "catalog.json", payload)
    with pytest.raises(QuoteEvalError, match="not in the catalog"):
        load_catalog(path)


def test_empty_product_list_is_rejected(tmp_path: Path):
    path = _write(tmp_path / "catalog.json", {"products": []})
    with pytest.raises(QuoteEvalError, match="does not list any products"):
        load_catalog(path)


def test_bad_decision_status_is_rejected(tmp_path: Path):
    payload = _scenarios()
    payload["scenarios"][0]["proposed"]["status"] = "MAYBE"
    path = _write(tmp_path / "scenarios.json", payload)
    with pytest.raises(QuoteEvalError, match="status must be one of"):
        load_scenarios(path)


def test_string_quantity_is_rejected(tmp_path: Path):
    payload = _scenarios()
    payload["scenarios"][0]["proposed"]["quantity"] = "120"
    path = _write(tmp_path / "scenarios.json", payload)
    with pytest.raises(QuoteEvalError, match="quantity"):
        load_scenarios(path)


def test_missing_proposed_decision_is_rejected(tmp_path: Path):
    payload = _scenarios()
    del payload["scenarios"][0]["proposed"]
    path = _write(tmp_path / "scenarios.json", payload)
    with pytest.raises(QuoteEvalError, match="proposed"):
        load_scenarios(path)


def test_decimal_spec_is_rejected(tmp_path: Path):
    payload = _catalog()
    payload["products"][1]["specs"]["length_ft"] = 8.0
    path = _write(tmp_path / "catalog.json", payload)
    with pytest.raises(QuoteEvalError, match="string or an integer"):
        load_catalog(path)


def test_expected_label_that_disagrees_with_the_catalog_is_rejected(tmp_path: Path):
    catalog_path = _write(tmp_path / "catalog.json", _catalog())
    payload = _scenarios()
    payload["scenarios"][0]["expected"]["quantity"] = 1
    scenarios_path = _write(tmp_path / "scenarios.json", payload)
    with pytest.raises(QuoteEvalError, match="case-1-correct-catalog-match"):
        load_validated_dataset(catalog_path, scenarios_path)


def test_unknown_primary_sku_is_rejected(tmp_path: Path):
    catalog_path = _write(tmp_path / "catalog.json", _catalog())
    payload = _scenarios()
    payload["scenarios"][0]["business_rules"]["primary_sku"] = "NO-SUCH-SKU"
    scenarios_path = _write(tmp_path / "scenarios.json", payload)
    with pytest.raises(QuoteEvalError, match="NO-SUCH-SKU"):
        load_validated_dataset(catalog_path, scenarios_path)


def test_primary_sku_that_breaks_the_requested_specs_is_rejected(tmp_path: Path):
    catalog_path = _write(tmp_path / "catalog.json", _catalog())
    payload = _scenarios()
    rules = payload["scenarios"][3]["business_rules"]
    rules["primary_sku"] = "LUM-SPF-2X4-10"
    scenarios_path = _write(tmp_path / "scenarios.json", payload)
    with pytest.raises(QuoteEvalError, match="does not match the provided specifications"):
        load_validated_dataset(catalog_path, scenarios_path)


def test_duplicate_scenario_id_is_rejected(tmp_path: Path):
    payload = _scenarios()
    payload["scenarios"].append(dict(payload["scenarios"][0]))
    path = _write(tmp_path / "scenarios.json", payload)
    with pytest.raises(QuoteEvalError, match="Duplicate scenario id"):
        load_scenarios(path)


def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _scenarios() -> dict:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
