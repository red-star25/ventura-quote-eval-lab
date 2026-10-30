const LINKS = [
  ["#overview", "Overview"],
  ["#architectures", "Architectures"],
  ["#scenarios", "Scenarios"],
  ["#failures", "Failures"],
  ["#method", "Method"],
];

export function Header() {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-paper/95 backdrop-blur-sm">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
        <a href="#overview" className="text-sm font-semibold">
          Quote Evaluation Lab
        </a>
        <nav aria-label="Page" className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
          {LINKS.map(([href, label]) => (
            <a key={href} href={href} className="hover:text-ink">
              {label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  );
}
