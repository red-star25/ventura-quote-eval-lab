import type { Experiment } from "@/lib/types";

export function Methodology({ data }: { data: Experiment }) {
  const skuCount = data.catalog.length;
  return (
    <section id="method" className="scroll-mt-20 py-10">
      <details className="rounded-md border border-line bg-card p-4">
        <summary className="cursor-pointer text-lg font-semibold">
          Technical methodology and limitations
        </summary>
        <div className="mt-4 max-w-3xl space-y-4 text-sm leading-relaxed">
          <p>
            The hybrid runtime and the evaluator share one business-rule function,{" "}
            <code className="font-mono text-[0.85em]">correct_decision</code>. The score checker
            calls it with the hand-labeled business rules. The hybrid path calls it with rules built
            from the grounded extraction and the catalog. The inputs differ. The function does not.
            This dashboard does not claim that every evaluation step is independent.
          </p>
          <p>
            Separate safety-invariant tests inspect a finished ready quote against the catalog and
            the stated specs. Those checks do not call <code className="font-mono text-[0.85em]">correct_decision</code>.
          </p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              Synthetic catalog with {skuCount} fictional SKUs. Stock and names are invented. They
              are not a distributor catalog.
            </li>
            <li>
              {data.meta.scenarioCount} newly created fictional customer requests, frozen before this
              comparison. Expected decisions were written by hand and checked against the catalog
              policies.
            </li>
            <li>
              {data.meta.modelName} at temperature {data.meta.temperature} for both architectures.
              Direct prompt {data.meta.directPrompt}. Hybrid prompt {data.meta.hybridPrompt}.
            </li>
            <li>
              The direct model sees the customer request, the catalog, and the substitution policy.
              The extractor sees only the customer request. Private labels, the expected decision,
              and the hand-entered primary SKU stay out of both model inputs.
            </li>
            <li>
              Evidence validation keeps a model value when the sentence supports it, and can recover
              a documented phrase the model cited poorly. It does not invent a length from a bare
              number.
            </li>
            <li>Twenty requests is a small sample. It is not statistical proof of generalization.</li>
            <li>No production integration, no ERP, and no real customer data.</li>
            <li>
              The earlier development and held-out runs, and the offline reprocess of saved hybrid
              responses, are historical. They are not this comparison.
            </li>
          </ul>
          <p className="text-muted">Sources: {data.meta.sources.join(", ")}.</p>
        </div>
      </details>
    </section>
  );
}
