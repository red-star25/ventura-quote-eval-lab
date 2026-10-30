"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DecisionColumn, specLine } from "@/components/DecisionColumn";
import { fieldLabel, hybridContrast } from "@/lib/format";
import {
  FEATURED_SCENARIO_ID,
  FILTERS,
  MISSING_LENGTH_SCENARIO_ID,
  matchesFilter,
  relevantProducts,
  type FilterId,
} from "@/lib/metrics";
import type { Experiment, Scenario } from "@/lib/types";

const EXTRACTION_FIELDS = [
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
] as const;

export function Explorer({ data }: { data: Experiment }) {
  const [filter, setFilter] = useState<FilterId>("all");
  const [selectedId, setSelectedId] = useState(() => initialId(data));
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const applyHash = () => {
      const id = window.location.hash.replace("#scenario-", "");
      if (data.scenarios.some((scenario) => scenario.id === id)) {
        setFilter("all");
        setSelectedId(id);
      }
    };
    applyHash();
    window.addEventListener("hashchange", applyHash);
    return () => window.removeEventListener("hashchange", applyHash);
  }, [data.scenarios]);

  useEffect(() => {
    const container = listRef.current;
    const current = container?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!container || !current) return;
    const delta = current.getBoundingClientRect().top - container.getBoundingClientRect().top;
    if (delta < 0 || delta > container.clientHeight - current.offsetHeight) {
      container.scrollTop += delta - 8;
    }
  }, [selectedId, filter]);

  const visible = useMemo(
    () => data.scenarios.filter((scenario) => matchesFilter(scenario, filter, data.catalog)),
    [data.catalog, data.scenarios, filter],
  );
  const selected = data.scenarios.find((scenario) => scenario.id === selectedId) ?? visible[0];

  function chooseFilter(next: FilterId) {
    setFilter(next);
    const matches = data.scenarios.filter((scenario) => matchesFilter(scenario, next, data.catalog));
    if (!matches.some((scenario) => scenario.id === selectedId) && matches[0]) {
      setSelectedId(matches[0].id);
    }
  }

  function chooseScenario(id: string) {
    setFilter("all");
    setSelectedId(id);
  }

  if (!selected) {
    return (
      <p role="alert" className="py-10 text-sm">
        The experiment file has no scenarios.
      </p>
    );
  }

  const products = relevantProducts(selected, data.catalog);
  const contrast = hybridContrast(selected);

  return (
    <section id="scenarios" className="scroll-mt-20 border-b border-line py-10">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Scenario explorer</h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
            All {data.scenarios.length} frozen requests. Select one to compare the expected decision
            with both architectures. Nothing here calls a model.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-md border border-line bg-card px-3 py-1.5 text-sm"
            onClick={() => chooseScenario(FEATURED_SCENARIO_ID)}
          >
            140 vs 100 stock
          </button>
          <button
            type="button"
            className="rounded-md border border-line bg-card px-3 py-1.5 text-sm"
            onClick={() => chooseScenario(MISSING_LENGTH_SCENARIO_ID)}
          >
            Missing length
          </button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Scenario filters">
        {FILTERS.map((item) => {
          const count = data.scenarios.filter((scenario) =>
            matchesFilter(scenario, item.id, data.catalog),
          ).length;
          const pressed = filter === item.id;
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={pressed}
              title={item.hint}
              className={`rounded-md border px-3 py-1.5 text-sm ${
                pressed ? "border-ink bg-ink text-paper" : "border-line bg-card text-ink"
              }`}
              onClick={() => chooseFilter(item.id)}
            >
              {item.label} <span className="tabular-nums">{count}</span>
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-sm text-muted">{FILTERS.find((item) => item.id === filter)?.hint}</p>

      <div className="mt-6 grid gap-6 md:grid-cols-[16rem_minmax(0,1fr)]">
        <div
          ref={listRef}
          data-testid="scenario-list"
          className="flex flex-col gap-2 md:sticky md:top-16 md:max-h-[calc(100vh-5rem)] md:overflow-y-auto md:pr-1"
        >
          {visible.map((scenario) => {
            const active = scenario.id === selected.id;
            return (
              <button
                key={scenario.id}
                type="button"
                aria-current={active ? "true" : undefined}
                className={`rounded-md border px-3 py-2 text-left ${
                  active ? "border-ink bg-card" : "border-line bg-transparent"
                }`}
                onClick={() => setSelectedId(scenario.id)}
              >
                <span className="block text-sm font-medium leading-snug line-clamp-3">{scenario.customerRequest}</span>
                <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <OutcomeDot outcome={scenario.direct.outcome} label="Direct" />
                  <OutcomeDot outcome={scenario.hybrid.outcome} label="Hybrid" />
                </span>
              </button>
            );
          })}
          {visible.length === 0 ? <p className="text-sm text-muted">No scenarios in this filter.</p> : null}
        </div>

        <div id={`scenario-${selected.id}`} className="min-w-0">
          <p className="font-mono text-xs text-muted">{selected.id}</p>
          <h3 className="mt-1 text-xl font-semibold leading-snug">{selected.description}</h3>
          <blockquote
            data-testid="selected-request"
            className="mt-4 border-l-2 border-ink pl-4 text-base leading-relaxed"
          >
            {selected.customerRequest}
          </blockquote>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Substitution in the sentence: {selected.substitutionStance}. Policy shown to the direct
            model: {selected.substitutionPolicy}
          </p>
          {contrast ? <p className="mt-3 text-sm leading-relaxed">{contrast}</p> : null}

          <div className="mt-4 grid gap-3 xl:grid-cols-3">
            <DecisionColumn
              title="Expected decision"
              testId="expected-decision"
              decision={selected.expected}
              reasons={[]}
              catalog={data.catalog}
            />
            <DecisionColumn
              title="Direct LLM"
              testId="direct-decision"
              outcome={selected.direct.outcome}
              decision={selected.direct.decision}
              reasons={selected.direct.reasons}
              catalog={data.catalog}
            />
            <DecisionColumn
              title="Hybrid"
              testId="hybrid-decision"
              outcome={selected.hybrid.outcome}
              decision={selected.hybrid.decision}
              reasons={selected.hybrid.reasons}
              catalog={data.catalog}
            />
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <Inventory products={products} catalogSize={data.catalog.length} />
            <Extraction scenario={selected} />
          </div>
        </div>
      </div>
    </section>
  );
}

function initialId(data: Experiment): string {
  if (data.scenarios.some((scenario) => scenario.id === FEATURED_SCENARIO_ID)) {
    return FEATURED_SCENARIO_ID;
  }
  return data.scenarios[0]?.id ?? "";
}

function OutcomeDot({ outcome, label }: { outcome: "PASS" | "FAIL"; label: string }) {
  const passed = outcome === "PASS";
  return (
    <span className={passed ? "text-pass" : "text-fail"}>
      {label} {passed ? "pass" : "fail"}
    </span>
  );
}

function Inventory({
  products,
  catalogSize,
}: {
  products: { sku: string; name: string; summary: string; stock: number; specs: Record<string, string | number>; substitutesFor: string[] }[];
  catalogSize: number;
}) {
  return (
    <section className="rounded-md border border-line bg-card p-4">
      <h3 className="text-sm font-medium">Catalog rows for this request</h3>
      {products.length === 0 ? (
        <p className="mt-2 text-sm text-muted">
          None of the {catalogSize} fictional products match this request.
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {products.map((product) => (
            <li key={product.sku} className="border-t border-line pt-3">
              <p className="font-mono text-sm">{product.sku}</p>
              <p className="text-sm">{product.name}</p>
              <p className="text-sm text-muted">{product.summary}</p>
              <p className="mt-1 text-sm tabular-nums">{product.stock} available</p>
              <p className="text-sm text-muted">{specLine(product.specs)}</p>
              <p className="text-sm text-muted">
                {product.substitutesFor.length > 0
                  ? `Substitutes for ${product.substitutesFor.join(", ")}`
                  : "Not a substitute"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Extraction({ scenario }: { scenario: Scenario }) {
  const extraction = scenario.hybrid.extraction;
  const rows = extraction
    ? EXTRACTION_FIELDS.flatMap((field) => {
        const value = extraction[field];
        const evidence = extraction.evidence[field];
        if (value === null && !evidence) return [];
        return [{ field, value, evidence }];
      })
    : [];

  return (
    <section className="rounded-md border border-line bg-card p-4">
      <h3 className="text-sm font-medium">Hybrid extraction</h3>
      <p className="mt-1 text-xs text-muted">
        {scenario.hybrid.modelName} · {scenario.hybrid.promptVersion} · temperature{" "}
        {scenario.hybrid.temperature}
      </p>
      {scenario.hybrid.derivedRules ? (
        <p className="mt-3 text-sm leading-relaxed">
          Python treated the requested product as {scenario.hybrid.derivedRules.primary_sku ?? "unresolved"},
          quantity {scenario.hybrid.derivedRules.quantity ?? "missing"}, substitution{" "}
          {scenario.hybrid.derivedRules.substitution_allowed ? "allowed" : "not allowed"}.
        </p>
      ) : null}
      <ul className="mt-3 space-y-2">
        {rows.map((row) => (
          <li key={row.field} className="border-t border-line pt-2 text-sm">
            <span className="font-medium">{fieldLabel(row.field)}: </span>
            <span>{row.value === null ? "not stated" : String(row.value)}</span>
            {row.evidence ? <span className="text-muted"> · evidence “{row.evidence}”</span> : null}
          </li>
        ))}
        {rows.length === 0 ? <li className="text-sm text-muted">No extracted fields.</li> : null}
      </ul>
      {(scenario.hybrid.recovered ?? []).length > 0 ? (
        <div className="mt-3">
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted">Read from the request</h4>
          <ul className="mt-1 space-y-1">
            {scenario.hybrid.recovered?.map((note) => (
              <li key={note} className="text-sm">
                {note}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {(scenario.hybrid.rejected ?? []).length > 0 ? (
        <div className="mt-3">
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted">Dropped values</h4>
          <ul className="mt-1 space-y-1">
            {scenario.hybrid.rejected?.map((note) => (
              <li key={note} className="text-sm">
                {note}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
