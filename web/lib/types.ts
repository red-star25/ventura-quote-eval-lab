export type DecisionStatus = "READY_TO_QUOTE" | "NEEDS_CLARIFICATION" | "NEEDS_REVIEW";

export type Decision = {
  status: DecisionStatus;
  sku: string | null;
  quantity: number | null;
  missingFields: string[];
  substitutionUsed: boolean;
  rationale: string;
};

export type Product = {
  sku: string;
  name: string;
  summary: string;
  stock: number;
  specs: Record<string, string | number>;
  substitutesFor: string[];
};

export type Extraction = {
  product_type: string | null;
  grade: string | null;
  species: string | null;
  thickness_in: string | number | null;
  width_in: number | null;
  width_ft: number | null;
  length_ft: number | null;
  quantity: number | null;
  model: string | null;
  substitution_allowed: boolean | null;
  evidence: Record<string, string | null>;
};

export type DerivedRules = {
  substitution_allowed: boolean;
  required_fields: string[];
  provided_specs: Record<string, string | number>;
  quantity: number | null;
  primary_sku: string | null;
};

export type ArchitectureRun = {
  outcome: "PASS" | "FAIL";
  failureOrigin: string;
  failureCategories: string[];
  reasons: string[];
  decision: Decision | null;
  modelName: string;
  promptVersion: string;
  temperature: number;
  extraction?: Extraction;
  rejected?: string[];
  recovered?: string[];
  derivedRules?: DerivedRules | null;
};

export type Scenario = {
  id: string;
  description: string;
  customerRequest: string;
  substitutionStance: "allowed" | "forbidden" | "silent";
  substitutionPolicy: string;
  rules: {
    substitutionAllowed: boolean;
    requiredFields: string[];
    providedSpecs: Record<string, string | number>;
    quantity: number | null;
    primarySku: string | null;
  };
  expected: Decision;
  direct: ArchitectureRun;
  hybrid: ArchitectureRun;
};

export type Experiment = {
  meta: {
    title: string;
    synthetic: boolean;
    exploratory: boolean;
    modelName: string;
    temperature: number;
    directPrompt: string;
    hybridPrompt: string;
    scenarioCount: number;
    sources: string[];
  };
  catalog: Product[];
  scenarios: Scenario[];
};
