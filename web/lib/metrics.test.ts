import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import experiment from "@/data/experiment.json";
import {
  FEATURED_SCENARIO_ID,
  FILTERS,
  MISSING_LENGTH_SCENARIO_ID,
  isInventoryOrSubstitution,
  matchesFilter,
  summarize,
} from "@/lib/metrics";
import type { Experiment } from "@/lib/types";

const data = experiment as unknown as Experiment;

describe("saved experiment", () => {
  it("keeps every frozen scenario and calculates the recorded scores", () => {
    const summary = summarize(data.scenarios);
    expect(data.scenarios).toHaveLength(20);
    expect(new Set(data.scenarios.map((scenario) => scenario.id)).size).toBe(20);
    expect(summary.total).toBe(20);
    expect(summary.directPassed).toBe(data.scenarios.filter((scenario) => scenario.direct.outcome === "PASS").length);
    expect(summary.hybridPassed).toBe(data.scenarios.filter((scenario) => scenario.hybrid.outcome === "PASS").length);
    expect(summary.directPassed).toBe(12);
    expect(summary.hybridPassed).toBe(20);
    expect(summary.improved).toBe(8);
    expect(summary.unsupportedApprovals).toBe(5);
    expect(summary.unnecessaryReviews).toBe(3);
    expect(summary.apiFailures).toBe(0);
    expect(summary.parseFailures).toBe(0);
    expect(summary.categoryLabelTotal).toBeGreaterThan(summary.directFailed);
    expect(data.meta.modelName).toBe("gpt-4o-mini");
    expect(data.meta.temperature).toBe(0);
    expect(data.meta.directPrompt).toBe("quote-decision-v1");
    expect(data.meta.hybridPrompt).toBe("quote-extract-v2");
  });

  it("uses the real stock-shortage case as the featured scenario", () => {
    const featured = data.scenarios.find((scenario) => scenario.id === FEATURED_SCENARIO_ID);
    expect(featured).toBeDefined();
    expect(featured?.customerRequest).toContain("140 pieces");
    expect(featured?.direct.outcome).toBe("FAIL");
    expect(featured?.direct.decision?.sku).toBe("LUM-ALT-2X4-8");
    expect(featured?.direct.decision?.quantity).toBe(140);
    expect(featured?.direct.failureCategories).toContain("unsafe_quote_approval");
    expect(featured?.direct.failureCategories).toContain("incorrect_inventory_decision");
    expect(featured?.direct.reasons.join(" ")).toContain("100 available");
    expect(featured?.hybrid.outcome).toBe("PASS");
    expect(featured?.hybrid.decision?.status).toBe("NEEDS_REVIEW");
    expect(data.catalog.find((product) => product.sku === "LUM-ALT-2X4-8")?.stock).toBe(100);
    expect(data.catalog.find((product) => product.sku === "LUM-SPF-2X4-8")?.stock).toBe(0);
  });

  it("filters from outcomes and categories rather than a separate score list", () => {
    expect(FILTERS.map((filter) => data.scenarios.filter((scenario) => matchesFilter(scenario, filter.id, data.catalog)).length)).toEqual([
      20,
      8,
      12,
      5,
      data.scenarios.filter((scenario) => scenario.direct.failureCategories.includes("missing_clarification")).length,
      data.scenarios.filter((scenario) => isInventoryOrSubstitution(scenario, data.catalog)).length,
    ]);
    const approvals = data.scenarios.filter((scenario) => matchesFilter(scenario, "unsupported-approval", data.catalog));
    expect(approvals).toHaveLength(5);
    expect(approvals.every((scenario) => scenario.direct.failureCategories.includes("unsafe_quote_approval"))).toBe(true);
    const missing = data.scenarios.filter((scenario) => matchesFilter(scenario, "missing-clarification", data.catalog));
    expect(missing.every((scenario) => scenario.direct.reasons.length > 0)).toBe(true);
    const lengthCase = data.scenarios.find((scenario) => scenario.id === MISSING_LENGTH_SCENARIO_ID);
    expect(lengthCase?.direct.failureCategories).toContain("unnecessary_human_escalation");
    expect(isInventoryOrSubstitution(lengthCase!, data.catalog)).toBe(false);
    expect(matchesFilter(data.scenarios.find((scenario) => scenario.id === "final-insufficient-alt")!, "inventory-substitution", data.catalog)).toBe(true);
    expect(matchesFilter(data.scenarios.find((scenario) => scenario.id === "final-plywood-ready")!, "inventory-substitution", data.catalog)).toBe(false);
    expect(matchesFilter(data.scenarios.find((scenario) => scenario.id === "final-unknown-siding")!, "inventory-substitution", data.catalog)).toBe(false);
  });

  it("does not carry secrets or a fabricated repository URL", () => {
    const blob = readFileSync(path.join(process.cwd(), "data/experiment.json"), "utf8").toLowerCase();
    expect(blob).not.toContain("openai_api_key");
    expect(blob).not.toContain("sk-");
    expect(blob).not.toContain("api_key");
    const site = readFileSync(path.join(process.cwd(), "lib/site.ts"), "utf8");
    expect(site).not.toMatch(/github\.com\//);
  });
});
