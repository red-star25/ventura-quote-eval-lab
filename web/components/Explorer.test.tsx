import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Explorer } from "@/components/Explorer";
import experiment from "@/data/experiment.json";
import type { Experiment } from "@/lib/types";

const data = experiment as unknown as Experiment;

describe("scenario explorer", () => {
  it("opens on the real 140-piece shortage and filters the list", async () => {
    const user = userEvent.setup();
    render(<Explorer data={data} />);

    expect(screen.getByTestId("scenario-list").querySelectorAll("button")).toHaveLength(20);
    expect(screen.getByTestId("selected-request").textContent).toContain("140 pieces");
    expect(screen.getByTestId("direct-decision").textContent).toContain("Ready to quote");
    expect(screen.getByTestId("direct-decision").textContent).toContain("LUM-ALT-2X4-8");
    expect(screen.getByTestId("direct-decision").textContent).toContain("100 available");
    expect(screen.getByTestId("direct-decision").textContent).toContain("Quoted 140, but LUM-ALT-2X4-8 has 100 available.");
    expect(screen.getByTestId("hybrid-decision").textContent).toContain("Needs review");
    expect(screen.getByTestId("hybrid-decision").textContent).toContain("Pass");
    expect(screen.getByTestId("expected-decision").textContent).toContain("Needs review");

    await user.click(screen.getByRole("button", { name: /Unsupported quote approvals/ }));
    expect(screen.getByTestId("scenario-list").querySelectorAll("button")).toHaveLength(5);
    expect(screen.getByTestId("selected-request").textContent?.length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Missing length" }));
    expect(screen.getByTestId("selected-request").textContent).toContain("22 pieces");
    expect(screen.getByTestId("direct-decision").textContent).toContain("Needs review");
    expect(screen.getByTestId("direct-decision").textContent).toContain("Fail");
    expect(screen.getByTestId("expected-decision").textContent).toContain("Needs clarification");
    expect(screen.getByTestId("expected-decision").textContent).toContain("Missing length");
    expect(screen.getByTestId("scenario-list").querySelectorAll("button")).toHaveLength(20);
  });
});
