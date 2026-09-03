"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  Activity,
  ChartNoAxesCombined,
  Command,
  Layers3,
  Library,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  Workflow,
  X,
} from "lucide-react";
import { useDashboard } from "@/lib/dashboard-context";
import { motionTransition, usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

export const DASHBOARD_SECTIONS = [
  { id: "command", href: "/", label: "Command Center", short: "Command", Icon: ChartNoAxesCombined },
  { id: "pipeline", href: "/pipeline", label: "Pipeline", short: "Pipeline", Icon: Workflow },
  { id: "opportunities", href: "/opportunities", label: "Opportunities", short: "Scan", Icon: Activity },
  { id: "portfolio", href: "/portfolio", label: "Portfolio", short: "Book", Icon: Layers3 },
  { id: "research", href: "/research", label: "Research", short: "Research", Icon: Library },
  { id: "system", href: "/system", label: "System", short: "System", Icon: ShieldCheck },
] as const;

export type SectionId = (typeof DASHBOARD_SECTIONS)[number]["id"];

function pipelineLabel(finalState: string | undefined) {
  if (finalState === "partial") return "Pipeline: execution limited";
  if (finalState === "halted") return "Pipeline: halted";
  if (finalState === "complete") return "Pipeline: complete";
  return "Pipeline: awaiting snapshot";
}

function connectionLabel(snapshot: ReturnType<typeof useDashboard>["snapshot"]) {
  if (!snapshot) return { label: "Connecting", tone: "text-muted" as const };
  if (snapshot.mode === "mock") return { label: "Demo fallback", tone: "text-violet" as const };
  const status = snapshot.system.api.status;
  if (status === "fresh") return { label: "Adapter connected", tone: "text-positive" as const };
  if (status === "refreshing") return { label: "Refreshing", tone: "text-cyan" as const };
  if (status === "delayed") return { label: "Stale adapter", tone: "text-warning" as const };
  return { label: "Adapter unavailable", tone: "text-negative" as const };
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { snapshot } = useDashboard();
  const [collapsed, setCollapsed] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<SectionId>("command");
  const reduced = usePrefersReducedMotion();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const onHome = pathname === "/";

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1279px)");
    const apply = () => setCollapsed(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [...DASHBOARD_SECTIONS];
    return DASHBOARD_SECTIONS.filter((item) => item.label.toLowerCase().includes(q));
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
        setMobileOpen(false);
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

  useEffect(() => {
    if (!onHome) {
      const match = DASHBOARD_SECTIONS.find((s) => (s.href === "/" ? false : pathname.startsWith(s.href)));
      if (match) setActiveSection(match.id);
      return;
    }

    const nodes = DASHBOARD_SECTIONS.map((s) => document.getElementById(s.id)).filter(Boolean) as HTMLElement[];
    if (!nodes.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        const top = visible[0]?.target.id as SectionId | undefined;
        if (top) setActiveSection(top);
      },
      { rootMargin: "-20% 0px -55% 0px", threshold: [0.1, 0.25, 0.5] },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [onHome, pathname, snapshot]);

  useEffect(() => {
    if (!onHome) return;
    const hash = window.location.hash.replace("#", "") as SectionId;
    if (!hash || !DASHBOARD_SECTIONS.some((s) => s.id === hash)) return;
    const t = window.setTimeout(() => {
      document.getElementById(hash)?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      setActiveSection(hash);
    }, 80);
    return () => window.clearTimeout(t);
  }, [onHome, reduced, snapshot]);

  const goSection = useCallback(
    (id: SectionId) => {
      setCommandOpen(false);
      setMobileOpen(false);
      setQuery("");
      if (pathname === "/") {
        const el = document.getElementById(id);
        if (el) {
          el.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
          window.history.replaceState(null, "", `#${id}`);
          setActiveSection(id);
          return;
        }
      }
      router.push(`/#${id}`);
    },
    [pathname, reduced, router],
  );

  const asOf = snapshot
    ? new Date(snapshot.asOf).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "America/New_York",
        timeZoneName: "short",
      })
    : "—";

  const connection = connectionLabel(snapshot);
  const isNavActive = (id: SectionId, href: string) => {
    if (onHome) return activeSection === id;
    return href === "/" ? pathname === "/" : pathname.startsWith(href);
  };

  return (
    <div className="market-canvas text-foreground">
      <a
        href="#command"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[calc(var(--z-command)+1)] focus:rounded-control focus:bg-raised focus:px-3 focus:py-2 focus:text-xs"
      >
        Skip to command center
      </a>
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-[var(--z-sticky)] hidden border-r border-subtle bg-[#07080c] transition-[width] duration-180 min-[900px]:flex min-[900px]:flex-col",
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
          {DASHBOARD_SECTIONS.map(({ id, href, label, Icon }) => {
            const active = isNavActive(id, href);
            return (
              <button
                key={id}
                type="button"
                title={collapsed ? label : undefined}
                aria-current={active ? "page" : undefined}
                onClick={() => goSection(id)}
                className={cn(
                  "group mb-1 flex h-9 w-full items-center gap-3 rounded-control border-l-2 px-3 text-left text-xs transition-[background-color,color,border-color] duration-160",
                  active
                    ? "border-cyan bg-surface-hover text-foreground"
                    : "border-transparent text-muted hover:bg-surface-hover hover:text-secondary",
                )}
              >
                <Icon className={cn("h-4 w-4 shrink-0", active ? "text-cyan" : "text-muted group-hover:text-secondary")} />
                <span className={cn(collapsed && "sr-only")}>{label}</span>
              </button>
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
        <header className="sticky top-0 z-[var(--z-sticky)] flex h-12 items-center justify-between gap-2 border-b border-subtle bg-canvas/90 px-3 backdrop-blur-sm sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className="rounded-control p-1.5 text-muted hover:bg-surface-hover hover:text-foreground min-[900px]:hidden"
              aria-expanded={mobileOpen}
              aria-controls="mobile-nav-drawer"
              aria-label={mobileOpen ? "Close navigation menu" : "Open navigation menu"}
              onClick={() => setMobileOpen((v) => !v)}
            >
              {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>
            <span className="truncate font-mono text-[10px] tracking-[0.16em] text-muted min-[900px]:hidden">
              SYNTHETIX / ALPHA
            </span>
            <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 font-mono text-[10px] font-medium tracking-[0.08em] text-warning">
              PAPER
            </span>
            {snapshot?.mode === "mock" ? (
              <span className="rounded-full border border-violet/40 bg-violet/10 px-2 py-0.5 font-mono text-[10px] font-medium tracking-[0.08em] text-violet">
                DEMO
              </span>
            ) : null}
            <span className={cn("hidden items-center gap-1.5 text-[11px] sm:inline-flex", connection.tone)}>
              <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
              {connection.label}
            </span>
            <button
              type="button"
              onClick={() => goSection("pipeline")}
              className="hidden min-w-0 items-center gap-2 text-xs text-secondary hover:text-foreground md:inline-flex"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-cyan shadow-[0_0_8px_var(--data-cyan)]" />
              <span aria-live="polite" className="truncate">
                {pipelineLabel(snapshot?.pipeline.finalState)}
              </span>
            </button>
          </div>
          <button
            onClick={() => setCommandOpen(true)}
            className="flex shrink-0 items-center gap-2 rounded-control px-2 py-1 text-xs text-muted transition-colors duration-160 hover:bg-surface-hover hover:text-secondary"
            aria-label="Open command palette"
          >
            <span className="hidden font-mono text-[11px] sm:inline">Data as of {asOf}</span>
            <Command className="h-3.5 w-3.5" />
          </button>
        </header>
        <main className="min-w-0 overflow-x-hidden p-3 pb-24 sm:p-4 min-[900px]:p-6 min-[900px]:pb-8">{children}</main>
      </div>

      <AnimatePresence>
        {mobileOpen ? (
          <motion.div
            id="mobile-nav-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Dashboard navigation"
            className="fixed inset-0 z-[var(--z-dialog)] min-[900px]:hidden"
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={reduced ? undefined : { opacity: 0 }}
            transition={reduced ? { duration: 0 } : { duration: 0.16 }}
          >
            <button
              type="button"
              className="absolute inset-0 bg-black/65"
              aria-label="Close navigation menu"
              onClick={() => setMobileOpen(false)}
            />
            <motion.nav
              className="absolute inset-y-0 left-0 flex w-[min(100%,20rem)] flex-col border-r border-subtle bg-[#07080c] shadow-overlay"
              initial={reduced ? false : { x: -24 }}
              animate={{ x: 0 }}
              exit={reduced ? undefined : { x: -24 }}
              transition={reduced ? { duration: 0 } : motionTransition}
            >
              <div className="flex h-12 items-center justify-between border-b border-subtle px-4">
                <span className="font-mono text-[11px] tracking-[0.16em]">SYNTHETIX / ALPHA</span>
                <button
                  type="button"
                  aria-label="Close navigation menu"
                  className="rounded-control p-1.5 text-muted hover:bg-surface-hover hover:text-foreground"
                  onClick={() => setMobileOpen(false)}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto px-2 py-3">
                {DASHBOARD_SECTIONS.map(({ id, href, label, Icon }) => {
                  const active = isNavActive(id, href);
                  return (
                    <button
                      key={id}
                      type="button"
                      aria-current={active ? "page" : undefined}
                      onClick={() => goSection(id)}
                      className={cn(
                        "mb-1 flex h-11 w-full items-center gap-3 rounded-control border-l-2 px-3 text-left text-sm",
                        active ? "border-cyan bg-surface-hover text-foreground" : "border-transparent text-secondary",
                      )}
                    >
                      <Icon className={cn("h-4 w-4", active ? "text-cyan" : "text-muted")} />
                      {label}
                    </button>
                  );
                })}
              </div>
              <div className="border-t border-subtle p-3 text-[11px] text-muted">
                <p className={connection.tone}>{connection.label}</p>
                <p className="mt-1">Operating mode · COPILOT</p>
              </div>
            </motion.nav>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <nav
        aria-label="Mobile sections"
        className="fixed inset-x-0 bottom-0 z-[var(--z-sticky)] border-t border-subtle bg-[#07080c]/95 backdrop-blur-sm min-[900px]:hidden"
      >
        <div className="grid grid-cols-6 gap-0.5 px-1 py-1.5">
          {DASHBOARD_SECTIONS.map(({ id, href, short, Icon }) => {
            const active = isNavActive(id, href);
            return (
              <button
                key={id}
                type="button"
                onClick={() => goSection(id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-w-0 flex-col items-center gap-1 rounded-control px-0.5 py-1.5 text-[9px] tracking-[0.02em] transition-colors duration-160",
                  active ? "bg-surface-hover text-cyan" : "text-muted",
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="w-full truncate text-center">{short}</span>
              </button>
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
                  goSection(filtered[activeIndex].id);
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
                  placeholder="Go to a section…"
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
                {filtered.length === 0 ? <p className="px-3 py-4 text-secondary">No matching sections.</p> : null}
                {filtered.map((item, index) => (
                  <button
                    key={item.id}
                    onClick={() => goSection(item.id)}
                    onMouseEnter={() => setActiveIndex(index)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-control px-3 py-2 text-left text-secondary transition-colors duration-160 hover:bg-surface-hover hover:text-foreground",
                      index === activeIndex && "bg-surface-hover text-foreground",
                    )}
                  >
                    <item.Icon className="h-4 w-4" />
                    {item.label}
                  </button>
                ))}
                <p className="mt-2 border-t border-subtle px-2 pt-3 text-[11px] text-muted">Standalone routes</p>
                <div className="mt-1 flex flex-wrap gap-1 px-2 pb-2">
                  {DASHBOARD_SECTIONS.filter((s) => s.href !== "/").map((s) => (
                    <Link
                      key={s.href}
                      href={s.href}
                      onClick={() => {
                        setCommandOpen(false);
                        setQuery("");
                      }}
                      className="rounded-control px-2 py-1 text-[11px] text-secondary hover:bg-surface-hover hover:text-foreground"
                    >
                      {s.href}
                    </Link>
                  ))}
                </div>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
