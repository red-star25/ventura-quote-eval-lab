"""Compare two saved runs. This does not call a model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quote_eval.categories import category_count_lines, format_categories, origin_count_lines
from quote_eval.models import QuoteEvalError


def load_run_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise QuoteEvalError(f"File not found: {path}.")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QuoteEvalError(f"Invalid JSON in {path}: {exc.msg}.") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("results"), list):
        raise QuoteEvalError(f"{path} is not a saved evaluation run.")
    return loaded


def render_comparison(left: dict[str, Any], right: dict[str, Any]) -> str:
    left_rows = {row["scenario_id"]: row for row in left["results"]}
    right_rows = {row["scenario_id"]: row for row in right["results"]}
    left_version = left.get("prompt_version", "unknown")
    right_version = right.get("prompt_version", "unknown")
    lines = [
        "Quote Evaluation Lab — prompt comparison",
        "Independent synthetic proof of work. Not affiliated with Ventura.",
        "",
        f"Left prompt: {left_version}",
        f"Right prompt: {right_version}",
        f"Left model: {_model_name(left)}",
        f"Right model: {_model_name(right)}",
        f"Left temperature: {left.get('temperature', 'not recorded')}",
        f"Right temperature: {right.get('temperature', 'not recorded')}",
        "A fair pair uses the same model, temperature, and model input. Only the prompt version should change.",
        "When model input differs, the runs may be two architectures. That is not a prompt-only comparison.",
        "This comparison is exploratory. It is not a statistically reliable measurement of model accuracy.",
        "",
    ]
    scenario_ids = list(dict.fromkeys([*left_rows, *right_rows]))
    fair = 0
    for scenario_id in scenario_ids:
        left_row = left_rows.get(scenario_id)
        right_row = right_rows.get(scenario_id)
        lines.append(scenario_id)
        if left_row is None or right_row is None:
            lines.append("  Pair: missing from one run, so it cannot be compared.")
            lines.append("")
            continue
        issues = _fairness_issues(left_row, right_row, left, right)
        if issues:
            lines.append("  Pair: settings differ (" + "; ".join(issues) + ").")
        else:
            fair += 1
            lines.append("  Pair: same model input and generation settings.")
        lines.append(f"  Split: {left_row.get('split', 'baseline')}")
        lines.append(
            f"  {left_version}: {_outcome(left_row)} | {_categories(left_row)} | {_decision(left_row)}"
        )
        lines.append(
            f"  {right_version}: {_outcome(right_row)} | {_categories(right_row)} | {_decision(right_row)}"
        )
        lines.append(f"  Expected: {_decision(left_row, key='expected_decision')}")
        lines.append("")
    lines.extend(_split_summaries(left, left_version))
    lines.extend(_split_summaries(right, right_version))
    lines.append(f"Fair pairs: {fair} of {len(scenario_ids)}.")
    lines.append(
        "Fair pairs count prompt-only comparisons. An architecture comparison is expected to show model input differs."
    )
    lines.extend(origin_count_lines([str(row.get("failure_origin", "")) for row in left["results"]]))
    lines.extend(
        category_count_lines(
            [tuple(row.get("failure_categories") or []) for row in left["results"]],
            heading=f"{left_version} failure category counts (one failed case can add to more than one):",
        )
    )
    lines.extend(origin_count_lines([str(row.get("failure_origin", "")) for row in right["results"]]))
    lines.extend(
        category_count_lines(
            [tuple(row.get("failure_categories") or []) for row in right["results"]],
            heading=f"{right_version} failure category counts (one failed case can add to more than one):",
        )
    )
    lines.append(
        "Exploratory only: these scenarios are not a statistically reliable measurement of model accuracy."
    )
    return "\n".join(lines)


def _model_name(document: dict[str, Any]) -> str:
    if document.get("model_name"):
        return str(document["model_name"])
    results = document["results"]
    if results and results[0].get("model_name"):
        return str(results[0]["model_name"])
    return "unknown"


def _fairness_issues(
    left_row: dict[str, Any],
    right_row: dict[str, Any],
    left: dict[str, Any],
    right: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if left_row.get("model_name") != right_row.get("model_name"):
        issues.append("model name differs")
    if left_row.get("model_input") != right_row.get("model_input"):
        issues.append("model input differs")
    left_temperature = left_row.get("temperature", left.get("temperature"))
    right_temperature = right_row.get("temperature", right.get("temperature"))
    if left_temperature != right_temperature:
        issues.append("temperature differs")
    return issues


def _outcome(row: dict[str, Any]) -> str:
    return str(row.get("outcome", "unknown"))


def _categories(row: dict[str, Any]) -> str:
    categories = row.get("failure_categories") or []
    if row.get("outcome") == "PASS":
        return "no failure category"
    return format_categories(categories)


def _decision(row: dict[str, Any], *, key: str = "parsed_decision") -> str:
    decision = row.get(key)
    if not isinstance(decision, dict):
        return "unavailable"
    sku = decision.get("sku") or "no SKU"
    quantity = decision.get("quantity")
    quantity_text = f"quantity {quantity}" if quantity is not None else "no quantity"
    return f"{decision.get('status')}, {sku}, {quantity_text}"


def _split_summaries(document: dict[str, Any], version: str) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in document["results"]:
        grouped.setdefault(str(row.get("split", "baseline")), []).append(row)
    lines: list[str] = []
    for split, rows in grouped.items():
        passed = sum(1 for row in rows if row.get("outcome") == "PASS")
        failed = len(rows) - passed
        lines.append(f"{version} {split}: {passed} passed, {failed} failed, {len(rows)} total.")
    return lines
