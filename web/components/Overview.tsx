import type { Experiment } from "@/lib/types";
import { summarize } from "@/lib/metrics";

export function Overview({ data }: { data: Experiment }) {
  const summary = summarize(data.scenarios);
  const stats = [
    {
      label: "Direct LLM",
      value: summary.directPassed,
      total: summary.total,
      note: "passed",
      tone: "text-ink",
    },
    {
      label: "Hybrid",
      value: summary.hybridPassed,
      total: summary.total,
      note: "passed",
      tone: "text-pass",
    },
    {
      label: "Unsupported quote approvals",
      value: summary.unsupportedApprovals,
      total: null,
      note: "in the direct run",
      tone: "text-fail",
    },
    {
      label: "Improved by hybrid",
      value: summary.improved,
      total: null,
      note: "direct misses the hybrid run passed",
      tone: "text-ink",
    },
  ];

  return (
    <section id="overview" className="scroll-mt-20 border-b border-line pb-8 pt-8 sm:pb-10">
      <p className="text-sm text-muted">
        Synthetic evaluation · {data.meta.modelName} · temperature {data.meta.temperature} ·{" "}
        {summary.total} requests · not affiliated with Ventura
      </p>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">Quote Evaluation Lab</h1>
      <p className="mt-4 max-w-3xl text-lg leading-snug text-ink">
        This project evaluates AI quoting reliability by comparing direct LLM decisions against AI
        extraction plus deterministic business rules.
      </p>
      <dl className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((stat) => (
          <div key={stat.label} className="rounded-md border border-line bg-card px-4 py-3">
            <dt className="text-sm text-muted">{stat.label}</dt>
            <dd className={`mt-1 text-3xl font-semibold tabular-nums ${stat.tone}`}>
              {stat.value}
              {stat.total !== null ? (
                <span className="text-xl font-medium text-muted">/{stat.total}</span>
              ) : null}
            </dd>
            <p className="mt-1 text-sm text-muted">{stat.note}</p>
          </div>
        ))}
      </dl>
      <p className="mt-4 max-w-3xl text-sm leading-relaxed text-muted">
        Synthetic and exploratory. These {summary.total} fictional requests do not measure production
        accuracy or statistical generalization. The two architectures see different model inputs, so
        this is not a prompt-only comparison. The direct run also sent {summary.unnecessaryReviews}{" "}
        cases to human review when the expected result was clarification. Counts are calculated from
        the saved runs. API failures: {summary.apiFailures}. Parsing failures: {summary.parseFailures}.
      </p>
    </section>
  );
}
