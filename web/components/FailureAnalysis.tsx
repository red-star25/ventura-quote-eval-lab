import { CATEGORY_COPY } from "@/lib/format";
import { summarize } from "@/lib/metrics";
import type { Experiment } from "@/lib/types";

export function FailureAnalysis({ data }: { data: Experiment }) {
  const summary = summarize(data.scenarios);
  const misses = data.scenarios.filter((scenario) => scenario.direct.outcome === "FAIL");
  const hybridFixed = misses.filter((scenario) => scenario.hybrid.outcome === "PASS").length;
  const recovered = misses.filter((scenario) => (scenario.hybrid.recovered ?? []).length > 0).length;
  const shown = CATEGORY_COPY.filter((item) => (summary.categoryCounts[item.id] ?? 0) > 0);

  return (
    <section id="failures" className="scroll-mt-20 border-b border-line py-10">
      <h2 className="text-2xl font-semibold tracking-tight">Failure analysis</h2>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed">
        The direct architecture failed {summary.directFailed} of {summary.total} requests. Those{" "}
        {summary.directFailed} failures carry {summary.categoryLabelTotal} category labels. One
        scenario can contribute to more than one category, so the category counts are not a
        partition and they do not add up to {summary.directFailed}.
      </p>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted">
        The hybrid architecture passed {hybridFixed} of those {misses.length} cases in this
        experiment. On {recovered} of them, the saved hybrid record includes a value read from the
        customer sentence. Python then applied stock and substitution. This is not a claim about a
        live Ventura system. The catalog and the requests are fictional.
      </p>
      <ul className="mt-6 space-y-3">
        {shown.map((item) => {
          const count = summary.categoryCounts[item.id] ?? 0;
          return (
            <li key={item.id} className="rounded-md border border-line bg-card px-4 py-3">
              <div className="flex items-baseline justify-between gap-4">
                <h3 className="text-sm font-medium">{item.title}</h3>
                <p className="shrink-0 font-mono text-sm tabular-nums">
                  {count} {count === 1 ? "case" : "cases"}
                </p>
              </div>
              <p className="mt-1 text-sm text-muted">{item.detail}</p>
            </li>
          );
        })}
      </ul>
      <div className="mt-6">
        <h3 className="text-sm font-medium">Direct misses</h3>
        <ul className="mt-3 divide-y divide-line border-y border-line">
          {misses.map((scenario) => (
            <li key={scenario.id} className="grid gap-1 py-3 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] sm:gap-4">
              <div className="min-w-0">
                <a className="text-sm font-medium underline decoration-line underline-offset-2" href={`#scenario-${scenario.id}`}>
                  {scenario.description}
                </a>
                <p className="mt-1 text-sm text-muted">{scenario.customerRequest}</p>
              </div>
              <p className="text-sm leading-relaxed">
                Direct {scenario.direct.outcome.toLowerCase()}, hybrid {scenario.hybrid.outcome.toLowerCase()}.{" "}
                {scenario.direct.reasons[0]}
              </p>
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-4 text-sm text-muted">
        API failures: {summary.apiFailures}. Parsing failures: {summary.parseFailures}. Both runs
        finished with a parsed decision on every request.
      </p>
    </section>
  );
}
