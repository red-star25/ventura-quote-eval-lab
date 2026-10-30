"""Print fixture results, or run an explicit live model evaluation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from quote_eval.categories import (
    category_count_lines,
    classify,
    format_categories,
    origin_count_lines,
)
from quote_eval.compare import load_run_file, render_comparison
from quote_eval.evaluator import (
    Evaluation,
    PASS,
    evaluate_all,
    field_label,
    format_decision,
    format_spec,
    load_validated_dataset,
    unspecified_fields,
    validate_expected_labels,
)
from quote_eval.extract import (
    EXTRACT_PROMPT_VERSION,
    EXTRACT_PROMPT_VERSION_V2,
    OpenAIExtractor,
)
from quote_eval.hybrid import (
    HELD_OUT_NOTE,
    SHARED_RULE_NOTE,
    HybridRun,
    evaluate_hybrid,
    hybrid_run_to_dict,
    render_hybrid_report,
    reprocess_saved_run,
)
from quote_eval.llm import (
    DEFAULT_MODEL,
    ORIGIN_API,
    ORIGIN_DECISION,
    ORIGIN_PARSE,
    TEMPERATURE,
    ModelRun,
    OpenAIQuoteModel,
    evaluate_with_model,
    model_run_to_dict,
)
from quote_eval.model_input import PROMPT_VERSION
from quote_eval.models import (
    BusinessRules,
    Catalog,
    QuoteEvalError,
    Scenario,
    default_data_dir,
    load_catalog,
    load_scenarios,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score quoting decisions. "
            "fixtures scores the synthetic baseline and does not call a model. "
            "live asks a model for a quote. hybrid asks a model to extract facts, then applies catalog rules."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="fixtures",
        choices=("fixtures", "live", "compare", "hybrid", "reprocess"),
        help=(
            "fixtures scores labeled examples. live asks a model for a quote. "
            "compare reads two saved runs. hybrid extracts facts, then applies catalog rules. "
            "reprocess scores a saved hybrid file again without calling a model."
        ),
    )
    parser.add_argument("run_files", nargs="*", type=Path, help="Two saved run files for compare.")
    parser.add_argument("--catalog", type=Path, help="Path to catalog.json")
    parser.add_argument("--scenarios", type=Path, help="Path to one scenarios file.")
    parser.add_argument(
        "--set",
        choices=("baseline", "development", "heldout", "final_validation", "all"),
        help=(
            "Which labeled set to score. baseline is the original five scenarios. "
            "final_validation is the frozen architecture comparison and is not included in all."
        ),
    )
    parser.add_argument(
        "--model",
        help=f"Model name for live runs. Defaults to QUOTE_EVAL_MODEL or {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--prompt",
        choices=(
            "quote-decision-v1",
            "quote-decision-v2",
            EXTRACT_PROMPT_VERSION,
            EXTRACT_PROMPT_VERSION_V2,
        ),
        default=PROMPT_VERSION,
        help=(
            "Prompt version. Live runs use quote-decision-v1 or quote-decision-v2. "
            "Hybrid runs use quote-extract-v1 or quote-extract-v2."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON file for a live run. API keys are not written.",
    )
    args = parser.parse_args(argv)
    if args.run_files and args.command not in {"compare", "reprocess"}:
        print("Error: extra file arguments are only used with compare or reprocess.", file=sys.stderr)
        return 2
    if args.command == "compare":
        return _compare(args)
    if args.command == "reprocess":
        return _reprocess(args)
    if args.command == "live":
        return _live(args)
    if args.command == "hybrid":
        return _hybrid(args)
    return _fixtures(args)


def _fixtures(args: argparse.Namespace) -> int:
    try:
        catalog, scenarios = _load(args)
    except QuoteEvalError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    results = evaluate_all(scenarios, catalog)
    print(render_report(results, product_count=len(catalog.products), report_title=_fixture_title(args.set)))
    return 0


def _live(args: argparse.Namespace) -> int:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print(
            "Error: OPENAI_API_KEY is not set. The live command was not sent to a model.",
            file=sys.stderr,
        )
        return 2
    try:
        catalog, scenarios = _load(args)
    except QuoteEvalError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.prompt not in {"quote-decision-v1", "quote-decision-v2"}:
        print(
            "Error: live only accepts quote-decision-v1 or quote-decision-v2.",
            file=sys.stderr,
        )
        return 2
    model_name = args.model or os.environ.get("QUOTE_EVAL_MODEL", "").strip() or DEFAULT_MODEL
    model = OpenAIQuoteModel(api_key=api_key, model=model_name)
    runs = evaluate_with_model(
        scenarios,
        catalog,
        model,
        redact_secret=api_key,
        prompt_version=args.prompt,
    )
    print(render_live_report(runs))
    if args.output is not None:
        _write_run(args.output, runs)
    return 0


def _hybrid(args: argparse.Namespace) -> int:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print(
            "Error: OPENAI_API_KEY is not set. The hybrid command was not sent to a model.",
            file=sys.stderr,
        )
        return 2
    try:
        catalog, scenarios = _load(args)
    except QuoteEvalError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    prompt_version = (
        args.prompt
        if args.prompt in {EXTRACT_PROMPT_VERSION, EXTRACT_PROMPT_VERSION_V2}
        else EXTRACT_PROMPT_VERSION_V2
    )
    model_name = args.model or os.environ.get("QUOTE_EVAL_MODEL", "").strip() or DEFAULT_MODEL
    model = OpenAIExtractor(api_key=api_key, model=model_name)
    runs = evaluate_hybrid(
        scenarios,
        catalog,
        model,
        redact_secret=api_key,
        prompt_version=prompt_version,
    )
    print(render_hybrid_report(runs))
    if args.output is not None:
        _write_hybrid(args.output, runs)
    return 0


def _reprocess(args: argparse.Namespace) -> int:
    if len(args.run_files) != 1:
        print("Error: reprocess requires one saved hybrid run file.", file=sys.stderr)
        return 2
    catalog_path = args.catalog or default_data_dir() / "catalog.json"
    try:
        catalog = load_catalog(catalog_path)
        print(reprocess_saved_run(args.run_files[0], catalog))
    except QuoteEvalError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


def _compare(args: argparse.Namespace) -> int:
    if len(args.run_files) != 2:
        print("Error: compare requires two saved run files.", file=sys.stderr)
        return 2
    try:
        left = load_run_file(args.run_files[0])
        right = load_run_file(args.run_files[1])
    except QuoteEvalError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(render_comparison(left, right))
    return 0


def _load(args: argparse.Namespace) -> tuple[Catalog, tuple[Scenario, ...]]:
    if args.set and args.scenarios:
        raise QuoteEvalError("Pass either --set or --scenarios, not both.")
    data_dir = default_data_dir()
    catalog_path = args.catalog or data_dir / "catalog.json"
    if args.scenarios:
        return load_validated_dataset(catalog_path, args.scenarios)
    return _load_set(catalog_path, data_dir, args.set or "baseline")


def _load_set(catalog_path: Path, data_dir: Path, selection: str) -> tuple[Catalog, tuple[Scenario, ...]]:
    names = {
        "baseline": ("scenarios.json",),
        "development": ("development_scenarios.json",),
        "heldout": ("heldout_scenarios.json",),
        "final_validation": ("final_validation_scenarios.json",),
        "all": ("scenarios.json", "development_scenarios.json", "heldout_scenarios.json"),
    }[selection]
    catalog = load_catalog(catalog_path)
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for name in names:
        for scenario in load_scenarios(data_dir / name):
            if scenario.id in seen:
                raise QuoteEvalError(f"Duplicate scenario id across sets: {scenario.id}.")
            seen.add(scenario.id)
            scenarios.append(scenario)
    validate_expected_labels(tuple(scenarios), catalog)
    return catalog, tuple(scenarios)


def _write_hybrid(path: Path, runs: tuple[HybridRun, ...] | list[HybridRun]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    first = runs[0] if runs else None
    document = {
        "note": f"{SHARED_RULE_NOTE} {HELD_OUT_NOTE}",
        "prompt_version": first.prompt_version if first is not None else "quote-extract-v1",
        "model_name": first.model_name if first is not None else DEFAULT_MODEL,
        "temperature": TEMPERATURE,
        "results": [hybrid_run_to_dict(run) for run in runs],
    }
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_run(path: Path, runs: tuple[ModelRun, ...] | list[ModelRun]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prompt_version = runs[0].prompt_version if runs else PROMPT_VERSION
    model_name = runs[0].model_name if runs else DEFAULT_MODEL
    document = {
        "note": (
            "Exploratory evaluation of fictional scenarios. "
            "These results are not a statistically reliable measurement of model accuracy."
        ),
        "prompt_version": prompt_version,
        "model_name": model_name,
        "temperature": TEMPERATURE,
        "results": [model_run_to_dict(run) for run in runs],
    }
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _fixture_title(selection: str | None) -> str | None:
    titles = {
        "development": "Report: development scenarios. These are hand-written examples, separate from live model performance.",
        "heldout": "Report: held-out scenarios. These are hand-written examples, separate from live model performance.",
        "final_validation": (
            "Report: final validation scenarios. Hand-written expected decisions for a later "
            "architecture comparison. This is not a live model score."
        ),
        "all": "Report: baseline, development, and held-out scenarios. These are hand-written examples, separate from live model performance.",
    }
    return titles.get(selection or "baseline")


def render_report(
    results: tuple[Evaluation, ...] | list[Evaluation],
    *,
    product_count: int,
    report_title: str | None = None,
) -> str:
    passed = sum(1 for result in results if result.outcome == PASS)
    failed = len(results) - passed
    lines = [
        "Quote Evaluation Lab",
        "Independent synthetic proof of work. Not affiliated with Ventura.",
        "",
        report_title
        or "Report: synthetic fixture baseline. These are hand-written examples, separate from live model performance.",
        "This report scores the supplied proposed decisions against the catalog and the labeled expected result.",
        "It does not call a language model, and it is not a measurement of a live AI model.",
        "",
        f"Catalog products: {product_count}",
        f"Scenarios: {len(results)}",
        "",
    ]
    for index, result in enumerate(results, start=1):
        lines.append(f"[{index}] {result.scenario_id} — {result.outcome}")
        lines.append(f"Description: {result.description}")
        lines.append(f"Request: {result.customer_request}")
        lines.append(f"Rules: {format_rules(result.rules)}")
        lines.append(f"Expected: {format_decision(result.expected)}")
        lines.append(f"Proposed: {format_decision(result.proposed)}")
        if result.proposed.rationale:
            lines.append(f"Proposed rationale (not used for scoring): {result.proposed.rationale}")
        if result.outcome != PASS:
            lines.append(
                "Failure categories: " + format_categories(classify(result.expected, result.proposed))
            )
        lines.append("Reasons:")
        for reason in result.reasons:
            lines.append(f"  - {reason}")
        lines.append("")
    lines.append(f"Summary: {passed} passed, {failed} failed, {len(results)} total.")
    return "\n".join(lines)


def render_live_report(runs: tuple[ModelRun, ...] | list[ModelRun]) -> str:
    passed = sum(1 for run in runs if run.outcome == PASS)
    failed = len(runs) - passed
    model_name = runs[0].model_name if runs else DEFAULT_MODEL
    prompt_version = runs[0].prompt_version if runs else PROMPT_VERSION
    lines = [
        "Quote Evaluation Lab — live model run",
        "Independent synthetic proof of work. Not affiliated with Ventura.",
        "",
        f"Model: {model_name}",
        f"Prompt version: {prompt_version}",
        f"Temperature: {TEMPERATURE}",
        f"Scenarios: {len(runs)}",
        "Architecture: direct quote decision. The model chooses the status, SKU, and quantity.",
        "The hybrid run uses a different prompt and does not see the catalog.",
        "Comparing the two is an architecture comparison, not a test where only the prompt changes.",
        "This is an exploratory evaluation of these fictional requests.",
        "It is not a statistically reliable measurement of model accuracy.",
        "",
    ]
    for index, run in enumerate(runs, start=1):
        lines.append(f"[{index}] {run.scenario_id} — {run.outcome} [{run.failure_origin}]")
        lines.append(f"Split: {run.split}")
        lines.append(f"Model: {run.model_name}")
        lines.append(f"Prompt version: {run.prompt_version}")
        lines.append(f"Failure origin: {_origin_label(run.failure_origin)}")
        if run.outcome != PASS:
            lines.append("Failure categories: " + format_categories(run.failure_categories))
        lines.append(f"Expected: {format_decision(run.expected)}")
        if run.parsed_decision is None:
            lines.append("Parsed: unavailable")
        else:
            lines.append(f"Parsed: {format_decision(run.parsed_decision)}")
            if run.parsed_decision.rationale:
                lines.append(f"Parsed rationale: {run.parsed_decision.rationale}")
        lines.append(f"Raw response: {run.raw_response if run.raw_response is not None else '(none)'}")
        lines.append("Reasons:")
        for reason in run.reasons:
            lines.append(f"  - {reason}")
        lines.append("")
    origins = {
        ORIGIN_DECISION: sum(1 for run in runs if run.failure_origin == ORIGIN_DECISION),
        ORIGIN_PARSE: sum(1 for run in runs if run.failure_origin == ORIGIN_PARSE),
        ORIGIN_API: sum(1 for run in runs if run.failure_origin == ORIGIN_API),
    }
    lines.append(f"Summary: {passed} passed, {failed} failed, {len(runs)} total.")
    lines.extend(_split_summary_lines(runs))
    lines.append(
        "Failure origins: "
        f"decision {origins[ORIGIN_DECISION]}, "
        f"parse {origins[ORIGIN_PARSE]}, "
        f"api {origins[ORIGIN_API]}."
    )
    lines.extend(origin_count_lines([run.failure_origin for run in runs]))
    lines.extend(category_count_lines([run.failure_categories for run in runs]))
    lines.append(
        "The direct architecture has no extraction step, so extraction or evidence-validation problems stay at 0."
    )
    lines.append(
        "Exploratory only: these synthetic scenarios are not a statistically reliable "
        "measurement of model accuracy."
    )
    return "\n".join(lines)


def _split_summary_lines(runs: tuple[ModelRun, ...] | list[ModelRun]) -> list[str]:
    splits: list[str] = []
    for run in runs:
        if run.split not in splits:
            splits.append(run.split)
    lines: list[str] = []
    for split in splits:
        chosen = [run for run in runs if run.split == split]
        passed = sum(1 for run in chosen if run.outcome == PASS)
        failed = len(chosen) - passed
        lines.append(f"{split}: {passed} passed, {failed} failed, {len(chosen)} total.")
    return lines


def _origin_label(origin: str) -> str:
    labels = {
        "none": "none (the parsed decision passed the checker)",
        ORIGIN_DECISION: "decision (the response parsed, and the business decision was wrong)",
        ORIGIN_PARSE: "parse (the response was missing or invalid, so it was not scored as a quote)",
        ORIGIN_API: "api (the model call failed before a response could be parsed)",
    }
    return labels.get(origin, origin)


def format_rules(rules: BusinessRules) -> str:
    if rules.substitution_allowed:
        policy = "approved substitute allowed only when the original is unavailable"
    else:
        policy = "substitution is not allowed"
    if rules.provided_specs:
        specs = ", ".join(
            f"{field_label(key)} {format_spec(key, value)}"
            for key, value in rules.provided_specs.items()
        )
    else:
        specs = "none"
    missing = unspecified_fields(rules)
    missing_text = ", ".join(field_label(field) for field in missing) if missing else "none"
    quantity = str(rules.quantity) if rules.quantity is not None else "not provided"
    primary = rules.primary_sku or "not resolved"
    return (
        f"{policy}; requested specs: {specs}; quantity {quantity}; "
        f"primary SKU {primary}; missing {missing_text}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
