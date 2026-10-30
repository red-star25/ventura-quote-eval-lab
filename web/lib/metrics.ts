import type { Experiment, Product, Scenario } from "./types";

export type FilterId =
  | "all"
  | "improved"
  | "both-passed"
  | "unsupported-approval"
  | "missing-clarification"
  | "inventory-substitution";

export const FILTERS: { id: FilterId; label: string; hint: string }[] = [
  { id: "all", label: "All scenarios", hint: "Every frozen request" },
  { id: "improved", label: "Improved by hybrid", hint: "Direct failed and hybrid passed" },
  { id: "both-passed", label: "Both passed", hint: "Both architectures matched the expected decision" },
  {
    id: "unsupported-approval",
    label: "Unsupported quote approvals",
    hint: "Direct model approved a quote the rules reject",
  },
  {
    id: "missing-clarification",
    label: "Missing clarification",
    hint: "Direct model did not ask for a missing fact",
  },
  {
    id: "inventory-substitution",
    label: "Inventory / substitution",
    hint: "The customer stated a substitution policy, or stock cannot fill the quantity",
  },
];

export const FEATURED_SCENARIO_ID = "final-insufficient-alt";
export const MISSING_LENGTH_SCENARIO_ID = "final-missing-length-spaced";

export type Summary = {
  total: number;
  directPassed: number;
  hybridPassed: number;
  directFailed: number;
  hybridFailed: number;
  improved: number;
  unsupportedApprovals: number;
  unnecessaryReviews: number;
  categoryCounts: Record<string, number>;
  categoryLabelTotal: number;
  apiFailures: number;
  parseFailures: number;
};

export function summarize(scenarios: Scenario[]): Summary {
  const total = scenarios.length;
  const directPassed = scenarios.filter((scenario) => scenario.direct.outcome === "PASS").length;
  const hybridPassed = scenarios.filter((scenario) => scenario.hybrid.outcome === "PASS").length;
  const improved = scenarios.filter(
    (scenario) => scenario.direct.outcome === "FAIL" && scenario.hybrid.outcome === "PASS",
  ).length;
  const unsupportedApprovals = scenarios.filter((scenario) =>
    scenario.direct.failureCategories.includes("unsafe_quote_approval"),
  ).length;
  const unnecessaryReviews = scenarios.filter((scenario) =>
    scenario.direct.failureCategories.includes("unnecessary_human_escalation"),
  ).length;
  const categoryCounts: Record<string, number> = {};
  for (const scenario of scenarios) {
    for (const category of scenario.direct.failureCategories) {
      categoryCounts[category] = (categoryCounts[category] ?? 0) + 1;
    }
  }
  const categoryLabelTotal = Object.values(categoryCounts).reduce((sum, count) => sum + count, 0);
  const origins = scenarios.flatMap((scenario) => [scenario.direct.failureOrigin, scenario.hybrid.failureOrigin]);
  return {
    total,
    directPassed,
    hybridPassed,
    directFailed: total - directPassed,
    hybridFailed: total - hybridPassed,
    improved,
    unsupportedApprovals,
    unnecessaryReviews,
    categoryCounts,
    categoryLabelTotal,
    apiFailures: origins.filter((origin) => origin === "api").length,
    parseFailures: origins.filter((origin) => origin === "parse").length,
  };
}

export function matchesFilter(scenario: Scenario, filter: FilterId, catalog: Product[]): boolean {
  if (filter === "all") return true;
  if (filter === "improved") return scenario.direct.outcome === "FAIL" && scenario.hybrid.outcome === "PASS";
  if (filter === "both-passed") return scenario.direct.outcome === "PASS" && scenario.hybrid.outcome === "PASS";
  if (filter === "unsupported-approval") {
    return scenario.direct.failureCategories.includes("unsafe_quote_approval");
  }
  if (filter === "missing-clarification") {
    return scenario.direct.failureCategories.includes("missing_clarification");
  }
  return isInventoryOrSubstitution(scenario, catalog);
}

export function isInventoryOrSubstitution(scenario: Scenario, catalog: Product[]): boolean {
  if (scenario.substitutionStance !== "silent" || scenario.rules.substitutionAllowed) return true;
  if (scenario.expected.substitutionUsed) return true;
  const primary = catalog.find((product) => product.sku === scenario.rules.primarySku);
  if (primary && scenario.rules.quantity !== null && primary.stock < scenario.rules.quantity) return true;
  if (primary && primary.stock === 0 && scenario.expected.status === "NEEDS_REVIEW") return true;
  if (
    !scenario.rules.primarySku &&
    scenario.rules.quantity !== null &&
    scenario.expected.missingFields.length === 0 &&
    matchingProducts(catalog, scenario.rules.providedSpecs).length > 1
  ) {
    return true;
  }
  return false;
}

export function matchingProducts(catalog: Product[], specs: Record<string, string | number>): Product[] {
  const keys = Object.keys(specs);
  if (keys.length === 0) return [];
  return catalog.filter((product) => keys.every((key) => product.specs[key] === specs[key]));
}

export function relevantProducts(scenario: Scenario, catalog: Product[]): Product[] {
  const skus = new Set<string>();
  for (const sku of [
    scenario.expected.sku,
    scenario.direct.decision?.sku,
    scenario.hybrid.decision?.sku,
    scenario.rules.primarySku,
    scenario.hybrid.derivedRules?.primary_sku,
  ]) {
    if (sku) skus.add(sku);
  }
  for (const product of catalog) {
    if (product.substitutesFor.some((sku) => skus.has(sku))) skus.add(product.sku);
  }
  for (const product of matchingProducts(catalog, scenario.rules.providedSpecs)) {
    skus.add(product.sku);
  }
  return catalog.filter((product) => skus.has(product.sku));
}

export function stockShortfall(product: Product | undefined, quantity: number | null): string | null {
  if (!product || quantity === null || quantity <= product.stock) return null;
  return `Quoted ${quantity}, but ${product.sku} has ${product.stock} available.`;
}

export function findScenario(data: Experiment, id: string): Scenario | undefined {
  return data.scenarios.find((scenario) => scenario.id === id);
}
