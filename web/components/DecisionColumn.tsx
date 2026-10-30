import { decisionSummary, fieldLabel, formatMissing, formatQuantity, formatSku, formatSubstitution, statusLabel } from "@/lib/format";
import { stockShortfall } from "@/lib/metrics";
import type { Decision, Product } from "@/lib/types";

export function DecisionColumn({
  title,
  testId,
  outcome,
  decision,
  reasons,
  catalog,
}: {
  title: string;
  testId: string;
  outcome?: "PASS" | "FAIL";
  decision: Decision | null;
  reasons: string[];
  catalog: Product[];
}) {
  const product = catalog.find((item) => item.sku === decision?.sku);
  const shortfall = stockShortfall(product, decision?.quantity ?? null);

  return (
    <article data-testid={testId} className="min-w-0 rounded-md border border-line bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-medium text-muted">{title}</h3>
        {outcome ? <Outcome outcome={outcome} /> : null}
      </div>
      {decision ? (
        <div className="mt-3">
          <p className={`text-lg font-semibold ${tone(decision.status)}`}>{statusLabel(decision.status)}</p>
          <p className="mt-2 font-mono text-sm">{formatSku(decision.sku)}</p>
          <p className="text-sm">{formatQuantity(decision.quantity)}</p>
          <p className="text-sm">{formatMissing(decision.missingFields)}</p>
          <p className="text-sm">{formatSubstitution(decision.substitutionUsed)}</p>
          {product ? (
            <p className="mt-2 text-sm text-muted">
              {product.name}: {product.stock} available
              {product.substitutesFor.length > 0
                ? ` · substitutes for ${product.substitutesFor.join(", ")}`
                : ""}
            </p>
          ) : null}
          {shortfall ? <p className="mt-2 text-sm font-medium text-fail">{shortfall}</p> : null}
          {decision.rationale ? (
            <p className="mt-3 text-sm leading-relaxed">
              <span className="font-medium">Rationale. </span>
              {decision.rationale}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 text-sm">No parsed decision.</p>
      )}
      {reasons.length > 0 ? (
        <div className="mt-3 border-t border-line pt-3">
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted">Checker</h4>
          <ul className="mt-2 space-y-2">
            {reasons.map((reason) => (
              <li key={reason} className="text-sm leading-relaxed">
                {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="sr-only">{decision ? decisionSummary(decision) : "No parsed decision"}</p>
    </article>
  );
}

function Outcome({ outcome }: { outcome: "PASS" | "FAIL" }) {
  const passed = outcome === "PASS";
  return (
    <span
      className={`shrink-0 rounded-sm border px-2 py-0.5 text-xs font-medium ${
        passed ? "border-pass text-pass" : "border-fail text-fail"
      }`}
    >
      {passed ? "Pass" : "Fail"}
    </span>
  );
}

function tone(status: string): string {
  if (status === "READY_TO_QUOTE") return "text-pass";
  if (status === "NEEDS_CLARIFICATION") return "text-ink";
  return "text-review";
}

export function specLine(specs: Record<string, string | number>): string {
  return Object.entries(specs)
    .map(([key, value]) => `${fieldLabel(key)} ${value}`)
    .join(" · ");
}
