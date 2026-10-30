import json

from quote_eval.cli import main
from quote_eval.evaluator import evaluate_all, load_validated_dataset
from quote_eval.models import default_data_dir


def test_cli_prints_every_scenario_and_the_summary(capsys):
    assert main([]) == 0
    report = capsys.readouterr().out
    assert "Quote Evaluation Lab" in report
    assert "not a measurement of a live AI model" in report
    assert "Not affiliated with Ventura" in report
    for scenario_id in (
        "case-1-correct-catalog-match",
        "case-2-missing-lumber-dimension",
        "case-3-substitution-not-allowed",
        "case-4-approved-substitution",
        "case-5-product-not-found",
    ):
        assert scenario_id in report
    assert "case-1-correct-catalog-match — PASS" in report
    assert "case-2-missing-lumber-dimension — FAIL" in report
    assert "case-3-substitution-not-allowed — FAIL" in report
    assert "case-4-approved-substitution — PASS" in report
    assert "case-5-product-not-found — FAIL" in report
    assert "Summary: 2 passed, 3 failed, 5 total." in report
    assert "Proposed rationale (not used for scoring):" in report


def test_cli_returns_an_error_for_a_bad_file(capsys, tmp_path):
    bad = tmp_path / "catalog.json"
    bad.write_text("[]", encoding="utf-8")
    scenarios = default_data_dir() / "scenarios.json"
    assert main(["--catalog", str(bad), "--scenarios", str(scenarios)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error:" in captured.err


def test_live_command_refuses_to_call_a_model_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def boom(*args, **kwargs):
        raise AssertionError("live mode constructed a model without an API key")

    monkeypatch.setattr("quote_eval.cli.OpenAIQuoteModel", boom)
    assert main(["live"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "OPENAI_API_KEY" in captured.err


def test_blank_api_key_is_treated_as_missing(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    monkeypatch.setattr(
        "quote_eval.cli.OpenAIQuoteModel",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("constructed")),
    )
    assert main(["live"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_live_command_reports_parse_failures_without_the_key(monkeypatch, capsys, tmp_path):
    secret = "sk-test-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    class FakeModel:
        def __init__(self, *, api_key: str, model: str, client=None) -> None:
            assert api_key == secret
            self.model_name = model

        def generate(self, messages):
            assert secret not in json.dumps(messages)
            return "not json"

    monkeypatch.setattr("quote_eval.cli.OpenAIQuoteModel", FakeModel)
    output = tmp_path / "run.json"
    assert main(["live", "--model", "gpt-test", "--output", str(output)]) == 0
    report = capsys.readouterr().out
    assert "live model run" in report
    assert "gpt-test" in report
    assert "not a statistically reliable measurement" in report
    assert "[parse]" in report
    assert secret not in report
    saved = output.read_text(encoding="utf-8")
    assert secret not in saved
    document = json.loads(saved)
    assert document["prompt_version"] == "quote-decision-v1"
    assert document["results"]
    assert all(row["failure_origin"] == "parse" for row in document["results"])
    assert "primary_sku" not in json.dumps(document["results"][0]["model_input"])


def test_fixtures_do_not_construct_a_model(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")

    def boom(*args, **kwargs):
        raise AssertionError("fixture mode constructed a model")

    monkeypatch.setattr("quote_eval.cli.OpenAIQuoteModel", boom)
    monkeypatch.setattr("quote_eval.cli.OpenAIExtractor", boom)
    assert main(["fixtures"]) == 0
    report = capsys.readouterr().out
    assert "synthetic fixture baseline" in report
    assert "Summary: 2 passed, 3 failed, 5 total." in report


def test_default_data_dir_points_at_the_shipped_files():
    data_dir = default_data_dir()
    catalog, scenarios = load_validated_dataset(
        data_dir / "catalog.json", data_dir / "scenarios.json"
    )
    results = evaluate_all(scenarios, catalog)
    assert len(results) == 5
