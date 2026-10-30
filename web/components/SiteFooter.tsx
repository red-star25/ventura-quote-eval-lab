import { githubUrl } from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="border-t border-line py-8 text-sm leading-relaxed text-muted">
      {githubUrl ? (
        <p>
          <a className="text-ink underline underline-offset-2" href={githubUrl}>
            GitHub repository
          </a>
        </p>
      ) : (
        <p>
          GitHub repository: not configured. Set <span className="font-mono">NEXT_PUBLIC_GITHUB_URL</span>{" "}
          when a public repository exists.
        </p>
      )}
      <p className="mt-3">
        Independent educational engineering experiment. Not affiliated with Ventura. No access to
        Ventura systems, customers, or production data.
      </p>
    </footer>
  );
}
