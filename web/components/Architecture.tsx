import type { Experiment } from "@/lib/types";

export function Architecture({ data }: { data: Experiment }) {
  return (
    <section id="architectures" className="scroll-mt-20 border-b border-line py-10">
      <h2 className="text-2xl font-semibold tracking-tight">Architecture comparison</h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">
        Both sides received the same customer sentences and the same substitution policy.{" "}
        {data.meta.modelName} ran at temperature {data.meta.temperature}. The direct prompt is{" "}
        {data.meta.directPrompt}. The hybrid prompt is {data.meta.hybridPrompt}.
      </p>
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <ArchitectureCard
          title="Direct LLM decisions"
          prompt={data.meta.directPrompt}
          summary="The model reads the request, the catalog, and the policy, then chooses the quote."
          steps={[
            ["Customer request", "The original sentence."],
            ["Catalog and policy", "Fictional stock, specs, and whether a substitute is allowed."],
            ["Language model", "Selects status, SKU, quantity, and missing fields."],
            ["Quote decision", "Ready to quote, needs clarification, or needs review."],
          ]}
        />
        <ArchitectureCard
          title="Hybrid"
          prompt={data.meta.hybridPrompt}
          summary="The model only copies facts. Python checks the evidence and applies the catalog rules."
          steps={[
            ["Customer request", "The same sentence. The model does not see the catalog."],
            ["Extraction", "The model returns facts and a span of evidence for each one."],
            ["Evidence check", "A value is kept only when the sentence actually states it."],
            ["Python rules", "Catalog match, stock, and substitution decide the quote."],
            ["Quote decision", "The same three statuses, chosen by code rather than the model."],
          ]}
        />
      </div>
    </section>
  );
}

function ArchitectureCard({
  title,
  prompt,
  summary,
  steps,
}: {
  title: string;
  prompt: string;
  summary: string;
  steps: [string, string][];
}) {
  return (
    <article className="rounded-md border border-line bg-card p-4">
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-1 font-mono text-xs text-muted">{prompt}</p>
      <p className="mt-3 text-sm leading-relaxed">{summary}</p>
      <ol className="mt-4 flex flex-col gap-2">
        {steps.map(([label, detail], index) => (
          <li key={label} className="flex gap-3 border-t border-line pt-2">
            <span className="w-6 shrink-0 font-mono text-xs text-muted">{index + 1}</span>
            <div className="min-w-0">
              <p className="text-sm font-medium">{label}</p>
              <p className="text-sm text-muted">{detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </article>
  );
}
