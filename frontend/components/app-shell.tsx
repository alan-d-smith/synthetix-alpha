"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  Activity,
  ChartNoAxesCombined,
  Command,
  Layers3,
  Library,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  Workflow,
  X,
} from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { motionTransition, usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

const nav = [
  ["/", "Command Center", ChartNoAxesCombined],
  ["/pipeline", "Pipeline", Workflow],
  ["/opportunities", "Opportunities", Activity],
  ["/portfolio", "Portfolio", Layers3],
  ["/research", "Research", Library],
  ["/system", "System", ShieldCheck],
] as const;

const mobileNav = [
  ["/", "Command", ChartNoAxesCombined],
  ["/opportunities", "Scan", Activity],
  ["/portfolio", "Book", Layers3],
  ["/research", "Research", Library],
] as const;

function pipelineLabel(finalState: string | undefined) {
  if (finalState === "partial") return "Pipeline: execution limited";
  if (finalState === "halted") return "Pipeline: halted";
  if (finalState === "complete") return "Pipeline: complete";
  return "Pipeline: awaiting snapshot";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { snapshot } = useDashboard();
  const [collapsed, setCollapsed] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const reduced = usePrefersReducedMotion();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1279px)");
    const apply = () => setCollapsed(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [...nav];
    return nav.filter(([, label]) => label.toLowerCase().includes(q));
  }, [query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, commandOpen]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k" && !event.isComposing) {
        event.preventDefault();
        setCommandOpen(true);
      }
      if (event.key === "Escape") {
        setCommandOpen(false);
        setQuery("");
      }
      if (
        event.key === "/" &&
        !event.isComposing &&
        target?.tagName !== "INPUT" &&
        target?.tagName !== "TEXTAREA" &&
        !target?.isContentEditable
      ) {
        event.preventDefault();
        document.getElementById("opportunity-search")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (commandOpen) window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [commandOpen]);

  function go(href: string) {
    setCommandOpen(false);
    setQuery("");
    router.push(href);
  }

  const asOf = snapshot
    ? new Date(snapshot.asOf).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "America/New_York",
        timeZoneName: "short",
      })
    : "—";

  return (
    <div className="market-canvas text-foreground">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-[var(--z-sticky)] hidden border-r border-subtle bg-[#0b0e14] transition-[width] duration-180 min-[900px]:flex min-[900px]:flex-col",
          collapsed ? "w-16" : "w-56",
        )}
      >
        <div className="flex h-12 items-center justify-between border-b border-subtle px-4">
          <span className={cn("font-mono text-[11px] font-medium tracking-[0.16em] text-foreground", collapsed && "sr-only")}>
            SYNTHETIX / ALPHA
          </span>
          <button
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            onClick={() => setCollapsed((v) => !v)}
            className="rounded-control p-1.5 text-muted transition-colors duration-160 hover:bg-surface-hover hover:text-foreground"
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>
        <nav aria-label="Primary" className="flex-1 px-2 py-4">
          {nav.map(([href, label, Icon]) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                title={collapsed ? label : undefined}
                className={cn(
                  "group mb-1 flex h-9 items-center gap-3 rounded-control border-l-2 px-3 text-xs transition-[background-color,color,border-color] duration-160",
                  active
                    ? "border-cyan bg-surface-hover text-foreground"
                    : "border-transparent text-muted hover:bg-surface-hover hover:text-secondary",
                )}
              >
                <Icon className={cn("h-4 w-4 shrink-0", active ? "text-cyan" : "text-muted group-hover:text-secondary")} />
                <span className={cn(collapsed && "sr-only")}>{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-subtle p-3">
          <button
            onClick={() => setCommandOpen(true)}
            className={cn(
              "flex w-full items-center gap-2 rounded-control border border-subtle bg-surface px-2 py-2 text-left text-xs text-muted transition-colors duration-160 hover:border-strong hover:text-secondary",
              collapsed && "justify-center",
            )}
            aria-label="Open command palette"
          >
            <Command className="h-3.5 w-3.5" />
            <span className={cn("flex-1", collapsed && "sr-only")}>Command</span>
            <kbd className={cn("font-mono text-[10px] text-muted", collapsed && "sr-only")}>⌘K</kbd>
          </button>
        </div>
      </aside>

      <div className={cn("transition-[margin] duration-180 min-[900px]:ml-56", collapsed && "min-[900px]:ml-16")}>
        <header className="sticky top-0 z-[var(--z-sticky)] flex h-12 items-center justify-between border-b border-subtle bg-canvas/90 px-3 backdrop-blur-sm sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <span className="font-mono text-[10px] tracking-[0.16em] text-muted min-[900px]:hidden">SYNTHETIX / ALPHA</span>
            <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 font-mono text-[10px] font-medium tracking-[0.08em] text-warning">
              PAPER
            </span>
            {snapshot?.mode === "mock" ? (
              <span className="rounded-full border border-violet/40 bg-violet/10 px-2 py-0.5 font-mono text-[10px] font-medium tracking-[0.08em] text-violet">
                DEMO
              </span>
            ) : null}
            <Link
              href="/pipeline"
              className="hidden min-w-0 items-center gap-2 text-xs text-secondary hover:text-foreground sm:inline-flex"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-cyan shadow-[0_0_8px_var(--data-cyan)]" />
              <span aria-live="polite" className="truncate">
                {pipelineLabel(snapshot?.pipeline.finalState)}
              </span>
            </Link>
          </div>
          <button
            onClick={() => setCommandOpen(true)}
            className="flex items-center gap-2 rounded-control px-2 py-1 text-xs text-muted transition-colors duration-160 hover:bg-surface-hover hover:text-secondary"
            aria-label="Open command palette"
          >
            <span className="hidden font-mono text-[11px] sm:inline">Data as of {asOf}</span>
            <Command className="h-3.5 w-3.5" />
          </button>
        </header>
        <main className="p-3 pb-24 sm:p-4 min-[900px]:p-6 min-[900px]:pb-8">{children}</main>
      </div>

      <nav
        aria-label="Mobile"
        className="fixed inset-x-0 bottom-0 z-[var(--z-sticky)] border-t border-subtle bg-[#0b0e14]/95 backdrop-blur-sm min-[900px]:hidden"
      >
        <div className="grid grid-cols-4 gap-0.5 px-1 py-1.5">
          {mobileNav.map(([href, label, Icon]) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex flex-col items-center gap-1 rounded-control px-1 py-1.5 text-[10px] tracking-[0.02em] transition-colors duration-160",
                  active ? "bg-surface-hover text-cyan" : "text-muted",
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
        </div>
      </nav>

      <AnimatePresence>
      {commandOpen ? (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
            className="fixed inset-0 flex items-start justify-center bg-black/60 px-4 pt-[15vh]"
          style={{ zIndex: "var(--z-command)" }}
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={reduced ? undefined : { opacity: 0 }}
          transition={reduced ? { duration: 0 } : { ...motionTransition, duration: 0.16 }}
          onMouseDown={() => {
            setCommandOpen(false);
            setQuery("");
          }}
        >
          <motion.div
            className="w-full max-w-lg overflow-hidden rounded-panel border border-strong bg-raised shadow-overlay"
            initial={reduced ? false : { opacity: 0.78, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced ? undefined : { opacity: 0, y: 8 }}
            transition={reduced ? { duration: 0 } : motionTransition}
            onMouseDown={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActiveIndex((i) => Math.min(filtered.length - 1, i + 1));
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveIndex((i) => Math.max(0, i - 1));
              }
              if (e.key === "Enter" && filtered[activeIndex]) {
                e.preventDefault();
                go(filtered[activeIndex][0]);
              }
            }}
          >
            <div className="flex items-center gap-2 border-b border-subtle px-4">
              <Command className="h-4 w-4 text-muted" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search commands"
                className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted"
                placeholder="Go to a view…"
              />
              <button
                onClick={() => {
                  setCommandOpen(false);
                  setQuery("");
                }}
                aria-label="Close command palette"
                className="p-1 text-muted hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-2 text-xs">
              <p className="px-2 py-2 uppercase tracking-[0.1em] text-muted">Navigate</p>
              {filtered.length === 0 ? <p className="px-3 py-4 text-secondary">No matching views.</p> : null}
              {filtered.map(([href, label, Icon], index) => (
                <button
                  key={href}
                  onClick={() => go(href)}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-control px-3 py-2 text-left text-secondary transition-colors duration-160 hover:bg-surface-hover hover:text-foreground",
                    index === activeIndex && "bg-surface-hover text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              ))}
            </div>
          </motion.div>
        </motion.div>
      ) : null}
      </AnimatePresence>
    </div>
  );
}
