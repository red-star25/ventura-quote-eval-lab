# Quote Evaluation Lab

Quote Evaluation Lab compares two ways of turning a customer request into a quote decision. One way asks a language model to choose the quote. The other asks the model only to copy facts from the sentence, then lets Python apply the catalog, inventory, and substitution rules.

The catalog, stock counts, customer requests, and business rules are fictional. The scores below come from one saved comparison of 20 synthetic requests. They are exploratory. They are not a measure of production accuracy and they are not statistical proof of generalization.

This is an independent educational engineering experiment. It is not affiliated with Ventura. It does not use Ventura systems, customers, prices, or production data.

## What it does

The project is an evaluation harness for AI quoting reliability.

- A fictional catalog holds four SKUs, with stock and an approved-substitute list.
- Each scenario is one customer sentence plus a hand-written expected decision.
- The direct architecture sends the sentence, the catalog, and the substitution policy to the model and asks for the quote.
- The hybrid architecture sends only the sentence. Python checks the extracted evidence and applies the catalog rules.
- The same checker scores both outputs against the hand-written expected decision.
- A static dashboard in `web/` shows the saved final comparison. Viewing it does not call a model and does not need an API key.

## Why it was built

Industrial quoting fails in specific ways: approving a quote the catalog cannot support, inventing a missing quantity or dimension, or sending a person to review a request that only needs one clarifying fact. This lab makes those failure modes visible on a small, frozen set of requests, with the model input and the private labels kept apart.

## Direct LLM versus hybrid

Both architectures used `gpt-4o-mini` at temperature 0. They saw the same customer sentences and the same substitution policy. They did not see the same model input, so this is not a prompt-only comparison.

**Direct.** Customer request, catalog, and policy go to the model. The model selects the quote. Prompt: `quote-decision-v1`.

**Hybrid.** The customer request goes to the model. The model returns fields and a span of evidence for each one. Python keeps a value only when the sentence supports it, then applies catalog, stock, and substitution rules. Prompt: `quote-extract-v2`.

The hybrid runtime and the score checker both call `correct_decision`. The checker passes the hand-labeled business rules. The hybrid path passes rules built from the grounded extraction. The inputs differ. The function does not. Separate safety checks on a finished ready quote do not call that function.

## Results

On the frozen 20-request set:

| Architecture | Passed |
| --- | --- |
| Direct LLM (`quote-decision-v1`) | 12/20 |
| Hybrid (`quote-extract-v2` plus Python rules) | 20/20 |

The direct run had 8 failures, 0 API failures, and 0 parsing failures. Five of those failures were unsupported quote approvals. Three sent the request to human review when the expected result was clarification. The hybrid run passed all 20, including the 8 the direct run missed.

One failure can carry more than one category, so the category counts are not a partition of the 8 failures. The direct categories were unsupported quote approval (5), missing clarification (7), wrong product or quantity (5), unnecessary human review (3), incorrect inventory decision (1), and incorrect substitution (1).

The case the dashboard opens on is `final-insufficient-alt`. The customer asked for 140 pieces and allowed an approved equivalent. The direct model approved substitute `LUM-ALT-2X4-8` at quantity 140. That SKU has 100 available, and the requested 8-foot product has none. The expected decision, and the hybrid decision, are needs review.

## Screenshot

Dashboard screenshot: not included yet.

Add a captured image of the running dashboard here when one exists. This repository does not link a hosted image or a deployed address.

## Python setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m quote_eval
```

`python -m quote_eval` scores the hand-written fixtures in `data/scenarios.json`. It does not call a model and it does not need an API key. The fixture sample includes failures on purpose. The command exits 0 after printing the report. Invalid catalog or scenario files exit 2.

## Dashboard setup

The site reads `web/data/experiment.json`, which is the sanitized export of the saved final runs. A clone can build the site without `runs/` and without `OPENAI_API_KEY`.

```bash
cd web
npm install
npm test
npm run dev
```

`npm run build` produces a static page. For Vercel, set the project root directory to `web`. No environment variable is required to build or view the dashboard. After a public repository exists, `NEXT_PUBLIC_GITHUB_URL` can be set to that address. Until then the page says the GitHub link is not configured.

Regenerate the export only when the local run files are present:

```bash
python -m quote_eval.dashboard_export
```

That command reads `runs/final-direct-v1.json` and `runs/final-hybrid-v2.json` and writes `web/data/experiment.json`. Those run files stay out of git because they contain raw model responses. The committed JSON keeps the scenario text, decisions, pass/fail outcomes, failure reasons, model name, prompt version, extracted fields, and evidence notes.

## Tests and reproducibility

```bash
pytest
cd web && npm test && npm run lint && npm run build
```

`pytest` never calls the network. The dashboard tests check the exported counts, the featured 140-piece case, the filters, and that the frontend source does not contain an API credential.

A live call is explicit and reads `OPENAI_API_KEY` from the environment. The key is not written into reports. The commands that produced the saved comparison are:

```bash
python -m quote_eval live --set final_validation --prompt quote-decision-v1 --model gpt-4o-mini --output runs/final-direct-v1.json
python -m quote_eval hybrid --set final_validation --prompt quote-extract-v2 --model gpt-4o-mini --output runs/final-hybrid-v2.json
```

`--set final_validation` is the frozen 20-request set. It is not included in `--set all`. Temperature is 0. `compare` only reads saved files. Because the model inputs differ, that pair is an architecture comparison, not a fair prompt pair.

`python -m quote_eval reprocess runs/hybrid-development.json` rescores a saved hybrid body with the current reader. It does not call the API and it does not replace the saved file.

## Methodology and limitations

- The catalog has four fictional SKUs.
- The comparison set has 20 newly written fictional requests. Expected decisions were written by hand and checked against the catalog policies.
- Both architectures used `gpt-4o-mini` at temperature 0.
- The direct model sees the customer request, the catalog, and the substitution policy. The extractor sees only the customer request. Expected decisions, fixture proposals, case titles, labeled specs, and the hand-entered primary SKU stay out of both model inputs.
- Evidence validation can recover a documented phrase the model cited poorly. It does not invent a length from a bare number.
- The hybrid decider and the evaluator share `correct_decision`. This repository does not claim that every evaluation step is independent.
- Twenty requests is a small sample.
- There is no production integration, no ERP, and no real customer data.
- Earlier development and held-out runs, and any offline reprocess of saved hybrid responses, are historical. They are not this comparison.

The checker passes a decision only when status, SKU, quantity, missing fields, and the substitution flag match the decision the rules require, and that decision is legal for the catalog. A missing required spec or quantity must be clarification, with no SKU. An unknown product or an ambiguous match must be review. Stock and substitutes are considered only after the request is specific enough to quote.

## Layout

- `src/quote_eval/evaluator.py` derives the allowed decision and explains a mismatch
- `src/quote_eval/model_input.py` builds the public prompt and keeps labels out of it
- `src/quote_eval/llm.py` calls the model when a live command is run
- `src/quote_eval/extract.py`, `decide.py`, and `hybrid.py` implement extraction plus deterministic quoting
- `src/quote_eval/safety.py` checks ready quotes without calling `correct_decision`
- `src/quote_eval/dashboard_export.py` writes `web/data/experiment.json`
- `data/catalog.json` holds the four fictional products
- `data/final_validation_scenarios.json` holds the 20 frozen requests
- `data/scenarios.json`, `data/development_scenarios.json`, and `data/heldout_scenarios.json` hold the earlier fixture sets
- `web/` is the Next.js dashboard
- `tests/` locks the checker and the mocked model path
