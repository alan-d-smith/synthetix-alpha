import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Page not found",
  description: "The requested Synthetix Alpha page does not exist.",
};

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col justify-center px-2 py-16">
      <p className="eyebrow">404</p>
      <h1 className="page-title mt-2">Page not found</h1>
      <p className="mt-2 text-sm text-secondary">
        That route is not part of the paper-trading command center. Use the navigation to return to a live section.
      </p>
      <div className="mt-6 flex flex-wrap gap-2">
        <Link
          href="/#command"
          className="rounded-control border border-cyan/40 bg-cyan/10 px-3 py-2 text-xs text-cyan hover:bg-cyan/15"
        >
          Command Center
        </Link>
        <Link
          href="/#system"
          className="rounded-control border border-subtle px-3 py-2 text-xs text-secondary hover:bg-surface-hover hover:text-foreground"
        >
          System
        </Link>
      </div>
    </div>
  );
}
