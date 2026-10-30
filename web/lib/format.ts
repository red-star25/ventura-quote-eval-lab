import type { Decision, DecisionStatus, Scenario } from "./types";

const STATUS_LABEL: Record<DecisionStatus, string> = {
  READY_TO_QUOTE: "Ready to quote",
  NEEDS_CLARIFICATION: "Needs clarification",
  NEEDS_REVIEW: "Needs review",
};

const FIELD_LABEL: Record<string, string> = {
  grade: "grade",
  species: "species",
  thickness_in: "thickness",
  width_in: "width (in)",
  width_ft: "width (ft)",
  length_ft: "length",
  quantity: "quantity",
  model: "model",
  product_type: "product type",
  substitution_allowed: "substitution allowed",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "No decision";
  return STATUS_LABEL[status as DecisionStatus] ?? status;
}

export function fieldLabel(field: string): string {
  return FIELD_LABEL[field] ?? field.replaceAll("_", " ");
}

export function formatQuantity(quantity: number | null): string {
  return quantity === null ? "No quantity" : `Quantity ${quantity}`;
}

export function formatMissing(fields: string[]): string {
  if (fields.length === 0) return "Nothing missing";
  return `Missing ${fields.map(fieldLabel).join(", ")}`;
}

export function formatSubstitution(used: boolean): string {
  return used ? "Substitution used" : "Substitution not used";
}

export function formatSku(sku: string | null): string {
  return sku ?? "No SKU";
}

export function decisionSummary(decision: Decision | null): string {
  if (!decision) return "No parsed decision";
  return [
    statusLabel(decision.status),
    formatSku(decision.sku),
    formatQuantity(decision.quantity),
    formatMissing(decision.missingFields),
    formatSubstitution(decision.substitutionUsed),
  ].join(" · ");
}

export function hybridContrast(scenario: Scenario): string | null {
  if (scenario.direct.outcome !== "FAIL" || scenario.hybrid.outcome !== "PASS") return null;
  const direct = scenario.direct.decision;
  const hybrid = scenario.hybrid.decision;
  if (!direct || !hybrid) return null;
  return `Direct said ${statusLabel(direct.status).toLowerCase()}. Hybrid said ${statusLabel(hybrid.status).toLowerCase()}, matching the expected ${statusLabel(scenario.expected.status).toLowerCase()}.`;
}

export const CATEGORY_COPY: { id: string; title: string; detail: string }[] = [
  {
    id: "unsafe_quote_approval",
    title: "Unsafe or unsupported quote approval",
    detail: "The direct model marked the quote ready when the labeled rules do not allow a quote.",
  },
  {
    id: "unnecessary_human_escalation",
    title: "Unnecessary human review",
    detail: "The direct model asked a person to review a request that only needed a missing fact.",
  },
  {
    id: "missing_clarification",
    title: "Missing clarification",
    detail: "The expected result asks the customer for something the request never stated, and the direct model did not.",
  },
  {
    id: "incorrect_inventory_decision",
    title: "Inventory shortage",
    detail: "Ready versus review, with the same quantity and no missing field. The disagreement is about stock.",
  },
  {
    id: "incorrect_substitution",
    title: "Substitution policy violation",
    detail: "The direct model recorded a substitute the labeled outcome does not use.",
  },
  {
    id: "wrong_product_or_quantity",
    title: "Wrong product or quantity",
    detail: "The SKU or the quantity differs from the expected decision.",
  },
  {
    id: "extraction_or_evidence",
    title: "Extraction or evidence-validation problem",
    detail: "A failed hybrid case dropped a model value the sentence did not support.",
  },
  {
    id: "invalid_model_output",
    title: "API or parsing failure",
    detail: "The call failed, or the response was not a usable decision.",
  },
];
