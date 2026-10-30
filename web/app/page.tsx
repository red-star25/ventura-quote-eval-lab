import { Architecture } from "@/components/Architecture";
import { Explorer } from "@/components/Explorer";
import { FailureAnalysis } from "@/components/FailureAnalysis";
import { Header } from "@/components/Header";
import { Methodology } from "@/components/Methodology";
import { Overview } from "@/components/Overview";
import { SiteFooter } from "@/components/SiteFooter";
import experiment from "@/data/experiment.json";
import type { Experiment } from "@/lib/types";

const data = experiment as unknown as Experiment;

export default function HomePage() {
  if (data.scenarios.length === 0) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-16">
        <p role="alert">The experiment file has no scenarios.</p>
      </main>
    );
  }

  return (
    <>
      <a
        href="#scenarios"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-20 focus:bg-card focus:px-3 focus:py-2"
      >
        Skip to scenarios
      </a>
      <Header />
      <main className="mx-auto max-w-6xl px-4">
        <Overview data={data} />
        <Architecture data={data} />
        <Explorer data={data} />
        <FailureAnalysis data={data} />
        <Methodology data={data} />
        <SiteFooter />
      </main>
    </>
  );
}
