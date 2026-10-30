from __future__ import annotations

from pathlib import Path

import pytest

from quote_eval.evaluator import load_validated_dataset

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "catalog.json"
SCENARIOS_PATH = ROOT / "data" / "scenarios.json"


@pytest.fixture(scope="session")
def dataset():
    return load_validated_dataset(CATALOG_PATH, SCENARIOS_PATH)


@pytest.fixture
def catalog(dataset):
    return dataset[0]


@pytest.fixture
def scenarios(dataset):
    return dataset[1]


@pytest.fixture
def by_id(scenarios):
    return {scenario.id: scenario for scenario in scenarios}
