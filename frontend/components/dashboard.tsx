"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { Check, ChevronDown, Copy, Database, Play, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { requestDryPipeline } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type {
  Candidate,
  DashboardSnapshot,
  ExecutionStatus,
  PipelineStage,
  RiskStatus,
} from "@/lib/types";
import { compact, cn, currency, percent } from "@/lib/utils";
import { fadeUp, motionTransition, staggerContainer, usePrefersReducedMotion } from "@/lib/motion";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { EmptyState, Freshness, PanelAlert } from "@/components/data-state";
import { Reveal, Stagger, StaggerItem } from "@/components/reveal";
import { PerformanceCharts, ResearchBars } from "@/components/charts/synthetix-charts";

type Page = "command" | "pipeline" | "opportunities" | "portfolio" | "research" | "system";
type SortKey = "iv" | "hv" | "ivRv" | "ivRank" | "liquidity" | "confidence" | "updated";

const stageColors: Record<string, string> = {
  complete: "bg-cyan",
  active: "bg-cyan",
  blocked: "bg-negative",
  pending: "bg-muted",
};

const statusTone: Record<RiskStatus, string> = {
  APPROVED: "text-positive",
  HALTED: "text-negative",
  PENDING: "text-warning",
  UNAVAILABLE: "text-negative",
};

export function DashboardPage({ page }: { page: Page }) {
  const { snapshot, loading, error, refresh } = useDashboard();
  if (loading && !snapshot) return <LoadingPage />;
  if (!snapshot) {
    return (
      <div className="mx-auto max-w-[720px] pt-16">
        <EmptyState
          title="Dashboard snapshot unavailable"
          detail={
            error ??
            "The dashboard adapter did not return a snapshot. Check that the API is running, then retry."
          }
        />
        <div className="mt-4 flex justify-center">
          <Button onClick={refresh}>Retry snapshot</Button>
        </div>
      </div>
    );
  }
  return <DashboardContent page={page} snapshot={snapshot} />;
}

function LoadingPage() {
  return (
    <div className="mx-auto max-w-[1800px] space-y-8">
      <div>
        <Skeleton className="h-[30px] w-56" />
        <Skeleton className="mt-2 h-4 w-80" />
      </div>
      <Skeleton className="h-[88px] w-full" />
      <div className="grid gap-5 xl:grid-cols-12">
        <div className="panel p-5 xl:col-span-8">
          <p className="text-xs text-muted">Refreshing account posture</p>
          <Skeleton className="mt-4 h-[230px] w-full" />
        </div>
        <div className="panel p-5 xl:col-span-4">
          <p className="text-xs text-muted">Loading research artifact</p>
          <Skeleton className="mt-4 h-[230px] w-full" />
        </div>
      </div>
      <div className="panel p-5">
        <p className="text-xs text-muted">Refreshing candidate scan</p>
        <Skeleton className="mt-4 h-10 w-full" />
        <Skeleton className="mt-2 h-10 w-full" />
        <Skeleton className="mt-2 h-10 w-full" />
        <Skeleton className="mt-2 h-10 w-full" />
      </div>
    </div>
  );
}

function DashboardContent({ page, snapshot }: { page: Page; snapshot: DashboardSnapshot }) {
  const titles: Record<Page, [string, string]> = {
    command: ["Command Center", "Autonomous paper trading command center"],
    pipeline: ["Pipeline", "Decision audit for the latest paper run"],
    opportunities: ["Opportunities", "Volatility setups ranked by the current decision system"],
    portfolio: ["Portfolio", "Current paper account posture and execution record"],
    research: ["Research", "Historical strategy evidence and verification"],
    system: ["System", "Data freshness, adapter state, and runtime boundaries"],
  };
  const [title, subtitle] = titles[page];
  return (
    <div className="mx-auto max-w-[1800px] space-y-8">
      <PageHeader title={title} subtitle={subtitle} snapshot={snapshot} />
      {page === "command" ? <CommandCenter snapshot={snapshot} /> : null}
      {page === "pipeline" ? <PipelineView snapshot={snapshot} /> : null}
      {page === "opportunities" ? <OpportunitiesView snapshot={snapshot} /> : null}
      {page === "portfolio" ? <PortfolioView snapshot={snapshot} /> : null}
      {page === "research" ? <ResearchView snapshot={snapshot} /> : null}
      {page === "system" ? <SystemView snapshot={snapshot} /> : null}
    </div>
  );
}

function PageHeader({ title, subtitle, snapshot }: { title: string; subtitle: string; snapshot: DashboardSnapshot }) {
  const [message, setMessage] = useState<string | null>(null);
  async function run() {
    const result = await requestDryPipeline();
    setMessage(result.detail);
  }
  return (
    <>
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">Synthetix Alpha</p>
          <h1 className="page-title mt-1">{title}</h1>
          <p className="mt-1 text-sm text-secondary">{subtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-1 font-mono text-[10px] font-medium tracking-[0.1em] text-warning">
            PAPER TRADING
          </span>
          {snapshot.mode === "mock" ? (
            <span className="rounded-full border border-violet/40 bg-violet/10 px-2 py-1 font-mono text-[10px] font-medium tracking-[0.1em] text-violet">
              DEMO DATA
            </span>
          ) : null}
          <Button variant="primary" onClick={run} disabled={snapshot.mode === "mock"}>
            <Play className="h-3.5 w-3.5" />
            Run dry pipeline
          </Button>
        </div>
      </div>
      {message ? <PanelAlert title="Pipeline action" detail={message} tone="info" /> : null}
    </>
  );
}

export function SignalTrace({ snapshot, full = false }: { snapshot: DashboardSnapshot; full?: boolean }) {
  const reduced = usePrefersReducedMotion();
  return (
    <section aria-label="Pipeline progress" className={cn("panel overflow-hidden", full ? "p-5" : "px-5 py-4")}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Signal Trace</p>
          <p className="mt-1 text-xs text-secondary">Screen → Gather → Critique → Form → Risk → Execute</p>
        </div>
        <span className="font-mono text-[11px] text-muted">RUN {snapshot.pipeline.id}</span>
      </div>
      <motion.ol
        className="grid gap-0 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
        initial={reduced ? false : "hidden"}
        variants={staggerContainer}
        viewport={{ once: true, amount: 0.35 }}
        whileInView={reduced ? undefined : "show"}
      >
        {snapshot.pipeline.stages.map((stage, index) => {
          const quiet = stage.status === "complete";
          const active = stage.status === "active";
          const blocked = stage.status === "blocked";
          return (
            <motion.li
              key={stage.stage}
              className="relative min-w-0 px-0 py-2 sm:pr-3"
              variants={reduced ? undefined : fadeUp}
            >
              <div className="mb-2 flex items-center">
                <motion.span
                  className={cn(
                    "h-2 w-2 rounded-full",
                    stageColors[stage.status],
                    active && "shadow-[0_0_10px_var(--data-cyan)]",
                    quiet && "opacity-70",
                  )}
                  transition={motionTransition}
                />
                {index < snapshot.pipeline.stages.length - 1 ? (
                  <span className="ml-2 h-px flex-1 overflow-hidden bg-border-subtle">
                    <span
                      className={cn(
                        "block h-px origin-left",
                        blocked ? "bg-negative" : stage.status === "pending" ? "bg-transparent" : "bg-cyan/70",
                        !reduced && stage.status !== "pending" && "sx-rail-fill",
                      )}
                    />
                  </span>
                ) : null}
              </div>
              <p className={cn("font-mono text-[10px] font-medium tracking-[0.12em]", quiet ? "text-muted" : "text-secondary")}>
                {stage.label.toUpperCase()}
              </p>
              <p className={cn("mt-1 text-xs leading-4", blocked ? "text-negative" : quiet ? "text-secondary" : "text-foreground")}>
                {stage.result}
              </p>
            </motion.li>
          );
        })}
      </motion.ol>
    </section>
  );
}

function AccountRiskSummary({ snapshot }: { snapshot: DashboardSnapshot }) {
  const p = snapshot.portfolio;
  return (
    <section className="panel px-5 py-4">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="section-title">Account posture</h2>
          <p className="mt-1 text-xs text-muted">
            Paper account snapshot ·{" "}
            {new Date(snapshot.asOf).toLocaleTimeString("en-US", {
              hour: "2-digit",
              minute: "2-digit",
              timeZone: "America/New_York",
              timeZoneName: "short",
            })}
          </p>
        </div>
        {p.hardHalt ? (
          <span className="text-xs text-negative">Hard halt active</span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-xs text-positive">
            <Check className="h-3.5 w-3.5" />
            No hard halt
          </span>
        )}
      </div>
      <div className="flex overflow-x-auto pb-1">
        <Metric label="NAV" value={currency(p.nav)} />
        <Metric label="Cash" value={currency(p.cash)} />
        <Metric label="Open positions" value={`${p.positions.length} / ${p.maxPositions}`} />
        <Metric label="Premium at risk" value={`${currency(p.premiumAtRisk)} / ${currency(p.premiumAtRiskCap)}`} />
        <Metric
          label="Unrealized P&L"
          value={`${p.aggregateUnrealizedPnl >= 0 ? "+" : ""}${currency(p.aggregateUnrealizedPnl)}`}
          positive={p.aggregateUnrealizedPnl >= 0}
        />
      </div>
    </section>
  );
}

function Metric({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  const reduced = usePrefersReducedMotion();
  return (
    <div className="metric-line shrink-0">
      <span className="metric-label">{label}</span>
      <motion.span
        className={cn("metric-value", positive === true && "text-positive")}
        initial={reduced ? false : { opacity: 0, y: 8 }}
        transition={motionTransition}
        viewport={{ once: true, amount: 0.6 }}
        whileInView={reduced ? undefined : { opacity: 1, y: 0 }}
      >
        {value}
      </motion.span>
    </div>
  );
}

function CriticMemo({ candidate }: { candidate: Candidate }) {
  const c = candidate.critic;
  return (
    <section className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="eyebrow">Critic Memo</p>
          <p className={cn("mt-1 font-mono text-xs font-medium", c.decision === "APPROVED" ? "text-positive" : c.decision === "REJECTED" ? "text-negative" : "text-warning")}>
            {c.decision} · {c.confidence} / 100
          </p>
        </div>
        <Confidence value={c.confidence} />
      </div>
      <MemoBlock label="Thesis">{c.thesis}</MemoBlock>
      <MemoBlock label="Risk factors">
        <ul className="space-y-1.5">
          {c.riskFactors.map((f) => (
            <li className="flex gap-2" key={f}>
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warning" />
              {f}
            </li>
          ))}
        </ul>
      </MemoBlock>
      <MemoBlock label="Macro regime">{c.regimeSummary}</MemoBlock>
    </section>
  );
}

function MemoBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <div className="mt-1.5 text-xs leading-5 text-secondary">{children}</div>
    </div>
  );
}

function Confidence({ value }: { value: number }) {
  return (
    <div className="flex gap-1" aria-label={`Critic confidence ${value} out of 100`}>
      {Array.from({ length: 5 }, (_, index) => (
        <span className={cn("h-1.5 w-5 rounded-full", value >= (index + 1) * 20 ? "bg-cyan" : "bg-border-strong")} key={index} />
      ))}
    </div>
  );
}

function RiskEnvelope({ snapshot }: { snapshot: DashboardSnapshot }) {
  const p = snapshot.portfolio;
  const reduced = usePrefersReducedMotion();
  const rows = [
    { label: "Premium at risk", current: p.premiumAtRisk, max: p.premiumAtRiskCap, display: `${currency(p.premiumAtRisk)} / ${currency(p.premiumAtRiskCap)}` },
    { label: "Position slots", current: p.positions.length, max: p.maxPositions, display: `${p.positions.length} / ${p.maxPositions}` },
    { label: "Daily drawdown", current: p.dailyDrawdown ?? 0, max: 0.05, display: p.dailyDrawdown === null ? "Unavailable" : `${percent(p.dailyDrawdown)} / 5.0%` },
    { label: "Total drawdown", current: p.totalDrawdown ?? 0, max: 0.2, display: p.totalDrawdown === null ? "Unavailable" : `${percent(p.totalDrawdown)} / 20.0%` },
  ];
  return (
    <section className="panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="section-title">Risk envelope</h2>
          <p className="mt-1 text-xs text-muted">Enforced runtime controls</p>
        </div>
        <ShieldCheck className="h-4 w-4 text-cyan" />
      </div>
      <div className="space-y-4">
        {rows.map((row) => {
          const ratio = Math.min(row.current / row.max, 1);
          const color = ratio >= 1 ? "bg-negative" : ratio >= 0.8 ? "bg-warning" : "bg-cyan";
          const width = `${Math.max(ratio * 100, 2)}%`;
          return (
            <div key={row.label}>
              <div className="mb-1.5 flex justify-between gap-3 text-xs">
                <span className="text-secondary">{row.label}</span>
                <span className="mono text-foreground">{row.display}</span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-border-subtle">
                <motion.div
                  className={cn("h-1 rounded-full", color)}
                  initial={reduced ? false : { width: 0 }}
                  transition={{ ...motionTransition, duration: 0.55 }}
                  viewport={{ once: true, amount: 0.8 }}
                  whileInView={reduced ? undefined : { width }}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-5 border-t border-subtle pt-4">
        <p className="eyebrow">Configured — not enforced by current runtime</p>
        <p className="mt-1 text-xs leading-5 text-warning">
          Sector concentration and weekly drawdown limits remain configuration-only in the current backend.
        </p>
      </div>
    </section>
  );
}

function OpportunityTable({ snapshot, limit }: { snapshot: DashboardSnapshot; limit?: number }) {
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("ivRv");
  const [sortAsc, setSortAsc] = useState(false);
  const [criticFilter, setCriticFilter] = useState<"ALL" | "APPROVED" | "REJECTED" | "PENDING">("ALL");
  const [riskFilter, setRiskFilter] = useState<"ALL" | RiskStatus>("ALL");
  const [focusIndex, setFocusIndex] = useState(0);
  const tableRef = useRef<HTMLTableElement>(null);

  const values = useMemo(() => {
    const filtered = snapshot.candidates.filter((c) => {
      const matchesQuery = `${c.ticker} ${c.company}`.toLowerCase().includes(query.toLowerCase());
      const matchesCritic = criticFilter === "ALL" || c.critic.decision === criticFilter;
      const matchesRisk = riskFilter === "ALL" || c.risk === riskFilter;
      return matchesQuery && matchesCritic && matchesRisk;
    });
    const sorted = [...filtered].sort((a, b) => {
      const dir = sortAsc ? 1 : -1;
      const pick = (c: Candidate) => {
        if (sortKey === "iv") return c.iv;
        if (sortKey === "hv") return c.hv;
        if (sortKey === "ivRv") return c.ivRv;
        if (sortKey === "ivRank") return c.ivRank;
        if (sortKey === "liquidity") return c.avgDollarVolume ?? -1;
        if (sortKey === "confidence") return c.critic.confidence;
        return new Date(c.updatedAt).getTime();
      };
      return (pick(a) - pick(b)) * dir;
    });
    return sorted.slice(0, limit);
  }, [snapshot.candidates, query, sortAsc, sortKey, criticFilter, riskFilter, limit]);

  useEffect(() => {
    setFocusIndex(0);
  }, [query, criticFilter, riskFilter, sortKey, sortAsc]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc((v) => !v);
    else {
      setSortKey(key);
      setSortAsc(false);
    }
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (!values.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setFocusIndex((i) => Math.min(values.length - 1, i + 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setFocusIndex((i) => Math.max(0, i - 1));
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setSelected(values[focusIndex] ?? null);
    }
  }

  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-subtle px-5 py-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="section-title">Opportunity scan</h2>
            <p className="mt-1 text-xs text-muted">IV/RV after liquidity and critic review · ↑↓ Enter to inspect</p>
          </div>
          <div className="relative">
            <input
              id="opportunity-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search symbol or company"
              className="h-8 w-full rounded-control border border-subtle bg-canvas px-3 pr-8 text-xs text-foreground placeholder:text-muted sm:w-56"
            />
            {query ? (
              <button onClick={() => setQuery("")} aria-label="Clear opportunity search" className="absolute right-2 top-2 text-muted hover:text-foreground">
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {(["ALL", "APPROVED", "REJECTED", "PENDING"] as const).map((value) => (
            <button
              key={value}
              onClick={() => setCriticFilter(value)}
              className={cn("rounded-full px-2.5 py-1 font-mono text-[10px]", criticFilter === value ? "bg-surface-hover text-cyan" : "text-muted hover:text-secondary")}
            >
              Critic · {value}
            </button>
          ))}
          {(["ALL", "APPROVED", "HALTED", "PENDING", "UNAVAILABLE"] as const).map((value) => (
            <button
              key={value}
              onClick={() => setRiskFilter(value)}
              className={cn("rounded-full px-2.5 py-1 font-mono text-[10px]", riskFilter === value ? "bg-surface-hover text-cyan" : "text-muted hover:text-secondary")}
            >
              Risk · {value}
            </button>
          ))}
        </div>
      </div>
      <div className="table-shell">
        <table
          ref={tableRef}
          className="w-full min-w-[1060px] border-collapse"
          tabIndex={0}
          onKeyDown={onKeyDown}
          aria-label="Opportunity table"
        >
          <thead className="table-head">
            <tr>
              <th className="h-10 px-5">Symbol / company</th>
              <SortHead label="IV" active={sortKey === "iv"} asc={sortAsc} onClick={() => toggleSort("iv")} />
              <SortHead label="HV" active={sortKey === "hv"} asc={sortAsc} onClick={() => toggleSort("hv")} />
              <SortHead label="IV/RV" active={sortKey === "ivRv"} asc={sortAsc} onClick={() => toggleSort("ivRv")} />
              <SortHead label="IV rank" active={sortKey === "ivRank"} asc={sortAsc} onClick={() => toggleSort("ivRank")} />
              <SortHead label="Liquidity" active={sortKey === "liquidity"} asc={sortAsc} onClick={() => toggleSort("liquidity")} />
              <th className="h-10 px-3">Critic</th>
              <SortHead label="Confidence" active={sortKey === "confidence"} asc={sortAsc} onClick={() => toggleSort("confidence")} />
              <th className="h-10 px-3">Risk</th>
              <SortHead label="Updated" active={sortKey === "updated"} asc={sortAsc} onClick={() => toggleSort("updated")} className="px-5" />
            </tr>
          </thead>
          <tbody>
            {values.map((candidate, index) => {
              const active = selected?.ticker === candidate.ticker || focusIndex === index;
              return (
                <tr
                  key={candidate.ticker}
                  className={cn("table-row cursor-pointer", active && "bg-surface-hover")}
                  aria-selected={active}
                  onClick={() => {
                    setFocusIndex(index);
                    setSelected(candidate);
                  }}
                >
                  <td className={cn("h-10 px-5 py-0", active ? "border-l-2 border-cyan" : "border-l-2 border-transparent")}>
                    <span className="font-mono text-xs font-medium">{candidate.ticker}</span>
                    <span className="ml-2 text-xs text-secondary">{candidate.company}</span>
                  </td>
                  <NumberCell>{percent(candidate.iv)}</NumberCell>
                  <NumberCell>{percent(candidate.hv)}</NumberCell>
                  <NumberCell strong>{candidate.ivRv.toFixed(2)}×</NumberCell>
                  <NumberCell>{percent(candidate.ivRank, 0)}</NumberCell>
                  <NumberCell>{candidate.avgDollarVolume ? compact(candidate.avgDollarVolume) : "Unavailable"}</NumberCell>
                  <td className="px-3">
                    <DecisionLabel value={candidate.critic.decision} />
                  </td>
                  <NumberCell>
                    <span className={candidate.critic.confidence >= 70 ? "text-positive" : "text-warning"}>{candidate.critic.confidence}</span>
                  </NumberCell>
                  <td className="px-3">
                    <RiskLabel value={candidate.risk} />
                  </td>
                  <NumberCell className="px-5">
                    {new Date(candidate.updatedAt).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "America/New_York" })}
                  </NumberCell>
                </tr>
              );
            })}
            {values.length === 0 ? (
              <tr>
                <td colSpan={10}>
                  <EmptyState
                    title="No liquid names meet the current IV/RV regime."
                    detail="An empty opportunity set is a valid market outcome when IV/RV or liquidity gates do not clear."
                  />
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <OpportunityInspector candidate={selected} onClose={() => setSelected(null)} />
    </section>
  );
}

function SortHead({
  label,
  active,
  asc,
  onClick,
  className,
}: {
  label: string;
  active: boolean;
  asc: boolean;
  onClick: () => void;
  className?: string;
}) {
  return (
    <th className={cn("h-10 px-3 text-right", className)}>
      <button onClick={onClick} aria-sort={active ? (asc ? "ascending" : "descending") : "none"} className="inline-flex items-center gap-1 hover:text-foreground">
        {label}
        <ChevronDown className={cn("h-3 w-3 transition-transform", active && asc && "rotate-180", !active && "opacity-35")} />
      </button>
    </th>
  );
}

function NumberCell({ children, strong, className }: { children: React.ReactNode; strong?: boolean; className?: string }) {
  return <td className={cn("mono h-10 px-3 py-0 text-right text-xs leading-4 text-secondary", strong && "text-foreground", className)}>{children}</td>;
}

function DecisionLabel({ value }: { value: Candidate["critic"]["decision"] }) {
  const color = value === "APPROVED" ? "bg-positive" : value === "REJECTED" ? "bg-negative" : "bg-warning";
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-secondary">
      <span className={cn("status-dot", color)} />
      {value}
    </span>
  );
}

function RiskLabel({ value }: { value: RiskStatus }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-mono text-[11px]", statusTone[value])}>
      <span className={cn("status-dot", value === "APPROVED" ? "bg-positive" : value === "PENDING" ? "bg-warning" : "bg-negative")} />
      {value}
    </span>
  );
}

function OpportunityInspector({ candidate, onClose }: { candidate: Candidate | null; onClose: () => void }) {
  const o = candidate?.order;
  return (
    <Sheet open={Boolean(candidate)} onOpenChange={(open) => !open && onClose()}>
      {candidate ? (
      <SheetContent title={`${candidate.ticker} · Decision detail`} description={`${candidate.company} · ${candidate.sector}`}>
        <div className="space-y-6">
          <div className="flex items-start justify-between">
            <div>
              <DecisionLabel value={candidate.critic.decision} />
              <p className="mt-2 font-mono text-[22px] font-medium leading-[26px]">{candidate.critic.confidence} / 100</p>
            </div>
            <Confidence value={candidate.critic.confidence} />
          </div>
          <section>
            <p className="eyebrow">Volatility setup</p>
            <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-control border border-subtle bg-subtle">
              {(
                [
                  ["IV", percent(candidate.iv)],
                  ["HV", percent(candidate.hv)],
                  ["IV/RV", `${candidate.ivRv.toFixed(2)}×`],
                  ["IV rank", percent(candidate.ivRank, 0)],
                  ["Price", candidate.price ? currency(candidate.price) : "Unavailable"],
                  ["Liquidity", candidate.avgDollarVolume ? compact(candidate.avgDollarVolume) : "Unavailable"],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="bg-surface p-3">
                  <p className="eyebrow">{label}</p>
                  <p className="mono mt-1 text-sm text-foreground">{value}</p>
                </div>
              ))}
            </div>
          </section>
          <CriticMemo candidate={candidate} />
          <section>
            <p className="eyebrow">Underlying context</p>
            <div className="mt-2 space-y-2 text-xs text-secondary">
              {candidate.analystConsensus !== null ? (
                <p>
                  Analyst consensus <span className="mono text-foreground">{candidate.analystConsensus.toFixed(2)}</span>
                </p>
              ) : (
                <p>Analyst context unavailable for this underlying.</p>
              )}
              {candidate.insiderMspr !== null ? (
                <p>
                  Insider MSPR <span className="mono text-foreground">{candidate.insiderMspr.toFixed(1)}</span>
                </p>
              ) : null}
              {candidate.headlines.map((headline) => (
                <p className="border-l border-subtle pl-3 leading-5" key={headline}>
                  {headline}
                </p>
              ))}
            </div>
          </section>
          <section>
            <p className="eyebrow">Trade proposal</p>
            {o ? (
              <div className="mt-2 rounded-control border border-subtle p-3">
                <div className="flex justify-between text-xs">
                  <span className="text-secondary">{o.contracts} contract · max loss</span>
                  <span className="mono text-foreground">{currency(o.maxLoss)}</span>
                </div>
                {o.legs[0]?.dteOffset !== undefined ? (
                  <p className="mt-2 text-xs text-muted">
                    DTE offset <span className="mono text-secondary">{o.legs[0].dteOffset}</span>
                  </p>
                ) : null}
                <div className="mt-3 space-y-2">
                  {o.legs.map((leg, index) => (
                    <div className="flex justify-between font-mono text-[11px]" key={`${leg.symbol}-${index}`}>
                      <span className={leg.side === "short" ? "text-negative" : "text-positive"}>
                        {leg.side.toUpperCase()} {leg.ratio} {leg.type.toUpperCase()}
                        {leg.delta ? ` · ${leg.delta}Δ` : ""}
                      </span>
                      <span className="text-muted">{leg.resolved ? leg.symbol : "Option leg unresolved"}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 border-t border-subtle pt-3 text-xs text-negative">
                  Execution unavailable — option-leg resolution is incomplete.
                </p>
              </div>
            ) : (
              <p className="mt-2 text-xs text-muted">No formed order is available for this candidate.</p>
            )}
          </section>
          <section>
            <p className="eyebrow">Risk outcome</p>
            <div className="mt-2">
              <RiskLabel value={candidate.risk} />
            </div>
          </section>
          <footer className="border-t border-subtle pt-4">
            <Freshness value={{ source: "Candidate context", asOf: candidate.updatedAt, status: "fresh" }} />
          </footer>
        </div>
      </SheetContent>
      ) : null}
    </Sheet>
  );
}

function CommandCenter({ snapshot }: { snapshot: DashboardSnapshot }) {
  const lead = snapshot.candidates.find((c) => c.critic.decision === "APPROVED") ?? snapshot.candidates[0];
  return (
    <>
      <Reveal>
        <AccountRiskSummary snapshot={snapshot} />
      </Reveal>
      <div className="grid gap-5 xl:grid-cols-12">
        <Reveal className="xl:col-span-8">
          <PerformanceCharts snapshot={snapshot} />
        </Reveal>
        <Reveal className="space-y-5 xl:col-span-4">
          <section className="panel p-5">
            {lead ? (
              <>
                <div className="mb-5 flex items-center justify-between">
                  <div>
                    <p className="eyebrow">Current decision</p>
                    <h2 className="section-title mt-1">
                      {lead.ticker} · {lead.critic.decision}
                    </h2>
                  </div>
                  <DecisionLabel value={lead.critic.decision} />
                </div>
                <CriticMemo candidate={lead} />
                <div className="mt-5 border-t border-subtle pt-4">
                  <p className="eyebrow">Risk result</p>
                  <div className="mt-2">
                    <RiskLabel value={lead.risk} />
                  </div>
                </div>
              </>
            ) : (
              <EmptyState title="Critic found no setup that clears the configured confidence threshold." detail="The latest scan produced no candidates. That is a calm, valid pipeline outcome." />
            )}
          </section>
          <RiskEnvelope snapshot={snapshot} />
        </Reveal>
      </div>
      <Reveal>
        <SignalTrace snapshot={snapshot} />
      </Reveal>
      <Reveal>
        <OpportunityTable snapshot={snapshot} />
      </Reveal>
      <div className="grid gap-5 xl:grid-cols-12">
        <Reveal className="xl:col-span-7">
          <PositionTable snapshot={snapshot} compact />
        </Reveal>
        <Reveal className="xl:col-span-5">
          <RiskEvents snapshot={snapshot} />
        </Reveal>
      </div>
    </>
  );
}

function PositionTable({ snapshot, compact = false }: { snapshot: DashboardSnapshot; compact?: boolean }) {
  return (
    <section className="panel overflow-hidden">
      <div className="flex items-center justify-between border-b border-subtle px-5 py-4">
        <div>
          <h2 className="section-title">{compact ? "Positions" : "Position slots"}</h2>
          <p className="mt-1 text-xs text-muted">
            Current paper positions · underlying shown only when verified on the contract record
          </p>
        </div>
        <span className="mono text-xs text-secondary">
          {snapshot.portfolio.positions.length} / {snapshot.portfolio.maxPositions}
        </span>
      </div>
      <div className="table-shell">
        <table className="w-full min-w-[720px]">
          <thead className="table-head">
            <tr>
              <th className="h-10 px-5">Contract</th>
              {!compact ? <th className="h-10 px-3">Underlying</th> : null}
              <th className="h-10 px-3 text-right">Qty</th>
              <th className="h-10 px-3 text-right">Avg entry</th>
              <th className="h-10 px-3 text-right">Unrealized P&L</th>
              <th className="h-10 px-5">Protection</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.portfolio.positions.map((p) => (
              <tr className="table-row" key={p.symbol}>
                <td className="mono h-10 px-5 py-0 text-xs">{p.symbol}</td>
                {!compact ? <td className="mono h-10 px-3 py-0 text-xs text-secondary">{p.underlying ?? "—"}</td> : null}
                <NumberCell>{p.quantity}</NumberCell>
                <NumberCell>{p.averageEntryPrice.toFixed(2)}</NumberCell>
                <NumberCell>
                  <span className={p.unrealizedPnl >= 0 ? "text-positive" : "text-negative"}>
                    {p.unrealizedPnl >= 0 ? "+" : ""}
                    {currency(p.unrealizedPnl)}
                  </span>
                </NumberCell>
                <td className="px-5 text-xs">
                  {p.protected ? (
                    <span className="inline-flex items-center gap-1 text-positive">
                      <Check className="h-3.5 w-3.5" />
                      Protected
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-warning">
                      <TriangleAlert className="h-3.5 w-3.5" />
                      Review
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {snapshot.portfolio.positions.length === 0 ? (
              <tr>
                <td colSpan={compact ? 5 : 6}>
                  <EmptyState title="No open paper positions." detail="Paper account currently holds no option contracts." />
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RiskEvents({ snapshot }: { snapshot: DashboardSnapshot }) {
  const blocked = snapshot.pipeline.events.filter((event) => event.status === "blocked");
  const warnings = snapshot.warnings;
  return (
    <section className="panel p-5">
      <div>
        <h2 className="section-title">Risk events</h2>
        <p className="mt-1 text-xs text-muted">Latest pipeline exceptions and account warnings</p>
      </div>
      <div className="mt-5 space-y-3">
        {blocked.map((event) => (
          <PanelAlert key={event.id} title={`${event.stage} · ${event.ticker ?? "System"}`} detail={event.detail} tone="negative" />
        ))}
        {snapshot.portfolio.positions
          .filter((p) => !p.protected)
          .map((p) => (
            <PanelAlert key={p.symbol} title="Protection review" detail={`${p.symbol} has no verified resting closing order.`} tone="warning" />
          ))}
        {warnings.map((warning) => (
          <PanelAlert key={warning} title="Data notice" detail={warning} tone="info" />
        ))}
        {blocked.length === 0 && snapshot.portfolio.positions.every((p) => p.protected) && warnings.length === 0 ? (
          <EmptyState title="No active risk events" detail="No blocked pipeline transitions or unprotected legs in the current snapshot." />
        ) : null}
      </div>
    </section>
  );
}

function PipelineView({ snapshot }: { snapshot: DashboardSnapshot }) {
  const [stage, setStage] = useState<PipelineStage | "ALL">("ALL");
  const reduced = usePrefersReducedMotion();
  const events = stage === "ALL" ? snapshot.pipeline.events : snapshot.pipeline.events.filter((event) => event.stage === stage);
  const approvals = snapshot.candidates.filter((c) => c.critic.decision === "APPROVED").length;
  const rejections = snapshot.candidates.filter((c) => c.critic.decision === "REJECTED").length;
  const halts = snapshot.candidates.filter((c) => c.risk === "HALTED").length;
  const unavailableExec = snapshot.executions.filter((e) => e.status === "unavailable" || e.status === "skipped_no_legs").length;

  return (
    <>
      <Reveal>
      <section className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow">Latest run</p>
            <h2 className="mt-1 font-display text-xl font-semibold">
              {snapshot.pipeline.finalState === "partial" ? "Completed with execution limitation" : snapshot.pipeline.finalState}
            </h2>
            <p className="mt-1 text-xs text-secondary">
              {new Date(snapshot.pipeline.asOf).toLocaleString("en-US", { timeZone: "America/New_York", timeZoneName: "short" })} · Paper mode
            </p>
          </div>
          <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-1 font-mono text-[10px] text-warning">
            {snapshot.mode === "mock" ? "DEMO RUN" : "PAPER RUN"}
          </span>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <AuditStat label="Critic approvals" value={String(approvals)} />
          <AuditStat label="Critic rejections" value={String(rejections)} />
          <AuditStat label="Risk halts" value={String(halts)} />
          <AuditStat label="Unavailable execution" value={String(unavailableExec)} tone="negative" />
        </div>
      </section>
      </Reveal>
      <Reveal>
      <SignalTrace snapshot={snapshot} full />
      </Reveal>
      <section className="grid gap-5 xl:grid-cols-12">
        <div className="panel p-5 xl:col-span-5">
          <div className="mb-4">
            <h2 className="section-title">Decision timeline</h2>
            <p className="mt-1 text-xs text-muted">Every available transition in the current run</p>
          </div>
          <motion.ol
            className="space-y-0"
            initial={reduced ? false : "hidden"}
            variants={staggerContainer}
            viewport={{ once: true, amount: 0.2 }}
            whileInView={reduced ? undefined : "show"}
          >
            {snapshot.pipeline.events.map((event, index) => (
              <motion.li className="relative flex gap-3 pb-5 last:pb-0" key={event.id} variants={reduced ? undefined : fadeUp}>
                {index < snapshot.pipeline.events.length - 1 ? <span className="absolute left-[5px] top-3 h-[calc(100%-4px)] w-px bg-border-subtle" /> : null}
                <span
                  className={cn(
                    "mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-surface",
                    event.status === "blocked" ? "bg-negative" : "bg-cyan",
                  )}
                />
                <div>
                  <div className="flex items-center gap-2">
                    <span className="mono text-[11px] text-muted">{event.timestamp}</span>
                    <span className="mono text-[10px] tracking-[0.08em] text-secondary">{event.stage}</span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-secondary">
                    {event.ticker ? <span className="font-mono text-foreground">{event.ticker} </span> : null}
                    {event.detail}
                  </p>
                </div>
              </motion.li>
            ))}
          </motion.ol>
        </div>
        <section className="panel overflow-hidden xl:col-span-7">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle px-5 py-4">
            <div>
              <h2 className="section-title">Stage detail</h2>
              <p className="mt-1 text-xs text-muted">Filter the run by its operational phase</p>
            </div>
            <div className="flex gap-1 overflow-x-auto">
              {(["ALL", "SCREEN", "GATHER", "CRITIQUE", "FORM", "RISK", "EXECUTE"] as const).map((value) => (
                <button
                  onClick={() => setStage(value)}
                  className={cn(
                    "rounded-control px-2 py-1 font-mono text-[10px] transition-colors duration-160",
                    stage === value ? "bg-surface-hover text-cyan" : "text-muted hover:text-secondary",
                  )}
                  key={value}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
          <div className="table-shell">
            <table className="w-full min-w-[640px]">
              <thead className="table-head">
                <tr>
                  <th className="h-10 px-5">Time</th>
                  <th className="h-10 px-3">Stage</th>
                  <th className="h-10 px-3">Ticker</th>
                  <th className="h-10 px-5">Result</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr className="table-row" key={event.id}>
                    <td className="mono px-5 py-3 text-xs text-muted">{event.timestamp}</td>
                    <td className="mono px-3 py-3 text-[11px] text-secondary">{event.stage}</td>
                    <td className="mono px-3 py-3 text-xs">{event.ticker ?? "—"}</td>
                    <td className="px-5 py-3 text-xs text-secondary">{event.detail}</td>
                  </tr>
                ))}
                {events.length === 0 ? (
                  <tr>
                    <td colSpan={4}>
                      <EmptyState title="No names met the IV/RV and liquidity criteria." detail="The selected stage has no recorded transitions in the latest run." />
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </section>
      <section className="grid gap-5 xl:grid-cols-2">
        <div className="panel p-5">
          <h2 className="section-title">Approvals & rejections</h2>
          <p className="mt-1 text-xs text-muted">Critic and risk outcomes from the current candidate set</p>
          <div className="mt-4 space-y-2">
            {snapshot.candidates.map((c) => (
              <div key={c.ticker} className="flex items-center justify-between gap-3 border-t border-subtle py-2.5 text-xs">
                <span className="mono text-foreground">{c.ticker}</span>
                <div className="flex items-center gap-3">
                  <DecisionLabel value={c.critic.decision} />
                  <RiskLabel value={c.risk} />
                </div>
              </div>
            ))}
            {snapshot.candidates.length === 0 ? (
              <EmptyState title="Critic found no setup that clears the configured confidence threshold." detail="An empty candidate set is a calm and valid pipeline outcome." />
            ) : null}
          </div>
        </div>
        <div className="panel p-5">
          <h2 className="section-title">Execution limitations</h2>
          <p className="mt-1 text-xs text-muted">Honest status — never upgraded to a fill</p>
          <div className="mt-4 space-y-3">
            {snapshot.pipeline.errors.map((error) => (
              <PanelAlert key={error} title="Pipeline limitation" detail={error.replace("EXECUTE: ", "")} tone="negative" />
            ))}
            {snapshot.executions
              .filter((e) => e.status === "unavailable" || e.status === "skipped_no_legs" || e.status === "error")
              .map((execution) => (
                <PanelAlert key={execution.clientOrderId} title={`${execution.symbol} · ${execution.status}`} detail={execution.detail} tone="warning" />
              ))}
          </div>
        </div>
      </section>
    </>
  );
}

function AuditStat({ label, value, tone }: { label: string; value: string; tone?: "negative" }) {
  return (
    <div className="rounded-control border border-subtle bg-canvas px-3 py-3">
      <p className="eyebrow">{label}</p>
      <p className={cn("mono mt-1 text-xl font-medium", tone === "negative" ? "text-negative" : "text-foreground")}>{value}</p>
    </div>
  );
}

function OpportunitiesView({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <>
      <Reveal>
        <SignalTrace snapshot={snapshot} />
      </Reveal>
      <Reveal>
        <OpportunityTable snapshot={snapshot} />
      </Reveal>
    </>
  );
}

function PortfolioView({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <>
      <Reveal>
        <AccountRiskSummary snapshot={snapshot} />
      </Reveal>
      <div className="grid gap-5 xl:grid-cols-12">
        <Reveal className="xl:col-span-7">
          <PositionTable snapshot={snapshot} />
        </Reveal>
        <Reveal className="xl:col-span-5">
          <RiskEnvelope snapshot={snapshot} />
        </Reveal>
      </div>
      <Reveal>
        <ExecutionLedger snapshot={snapshot} />
      </Reveal>
    </>
  );
}

function ExecutionLedger({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <section className="panel overflow-hidden">
      <div className="flex items-center justify-between border-b border-subtle px-5 py-4">
        <div>
          <h2 className="section-title">Execution ledger</h2>
          <p className="mt-1 text-xs text-muted">dry-run · skipped · duplicate · submitted · error — never implied fills</p>
        </div>
        <span className="font-mono text-[11px] text-warning">PAPER ONLY</span>
      </div>
      <div className="table-shell">
        <table className="w-full min-w-[760px]">
          <thead className="table-head">
            <tr>
              <th className="h-10 px-5">Symbol</th>
              <th className="h-10 px-3">Status</th>
              <th className="h-10 px-3">Client order ID</th>
              <th className="h-10 px-5">Detail</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.executions.map((execution) => (
              <tr className="table-row" key={execution.clientOrderId}>
                <td className="mono px-5 py-3 text-xs">{execution.symbol}</td>
                <td className="px-3 py-3">
                  <ExecutionLabel value={execution.status} />
                </td>
                <td className="px-3 py-3">
                  <button
                    onClick={() => navigator.clipboard?.writeText(execution.clientOrderId)}
                    className="mono inline-flex items-center gap-1 text-[11px] text-secondary hover:text-cyan"
                    aria-label={`Copy ${execution.clientOrderId}`}
                  >
                    {execution.clientOrderId}
                    <Copy className="h-3 w-3" />
                  </button>
                </td>
                <td className="px-5 py-3 text-xs text-secondary">{execution.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ExecutionLabel({ value }: { value: ExecutionStatus }) {
  const map: Record<ExecutionStatus, [string, string]> = {
    dry_run: ["Dry-run", "text-cyan"],
    skipped_no_legs: ["Skipped", "text-warning"],
    duplicate: ["Duplicate", "text-warning"],
    submitted: ["Submitted", "text-positive"],
    error: ["Error", "text-negative"],
    unavailable: ["Unavailable", "text-negative"],
  };
  const [label, tone] = map[value];
  return <span className={cn("font-mono text-[11px]", tone)}>{label}</span>;
}

function ResearchView({ snapshot }: { snapshot: DashboardSnapshot }) {
  const p = snapshot.performance;
  return (
    <>
      <Reveal>
      <section className="panel p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="eyebrow">Deployed strategy</p>
            <h2 className="mt-1 font-display text-xl font-semibold">{p.name}</h2>
            <p className="mt-1 text-xs text-secondary">{p.period}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="rounded-full border border-violet/40 bg-violet/10 px-2 py-1 font-mono text-[10px] tracking-[0.1em] text-violet">
              HISTORICAL RESEARCH
            </span>
            <span className="rounded-full border border-subtle px-2 py-1 font-mono text-[10px] tracking-[0.1em] text-secondary">
              NOT LIVE PERFORMANCE
            </span>
          </div>
        </div>
        <div className="mt-5 flex overflow-x-auto border-t border-subtle pt-4">
          <Metric label="IS Sharpe" value={p.sharpe.toFixed(2)} />
          <Metric label="Max drawdown" value={percent(p.maxDrawdown)} />
          <Metric label="Win rate" value={percent(p.winRate, 0)} />
          <Metric label="Trades" value={p.trades.toString()} />
          <Metric label="Profit factor" value={p.profitFactor.toFixed(2)} />
          <Metric label="OOS Sharpe" value={p.oosSharpe?.toFixed(2) ?? "Unavailable"} />
          <Metric label="Fragility median" value={p.fragilityMedian?.toFixed(2) ?? "Unavailable"} />
        </div>
      </section>
      </Reveal>
      <Reveal>
        <PerformanceCharts snapshot={snapshot} />
      </Reveal>
      <Stagger className="grid gap-5 xl:grid-cols-2">
        <StaggerItem>
          <ResearchBars title="Annual returns" subtitle="Historical, in-sample" data={p.annualReturns as unknown as ReadonlyArray<Record<string, unknown>>} keyName="year" valueName="value" type="returns" />
        </StaggerItem>
        <StaggerItem>
          <ResearchBars title="Trade P&L distribution" subtitle="Historical trade count by P&L bucket · not live" data={p.tradePnL as unknown as ReadonlyArray<Record<string, unknown>>} keyName="bucket" valueName="count" type="pnl" />
        </StaggerItem>
      </Stagger>
      <Stagger className="grid gap-5 xl:grid-cols-2">
        <StaggerItem>
          <ResearchBars title="IV/RV gate sweep" subtitle="Selection score; deployed threshold highlighted" data={p.gateSweep as unknown as ReadonlyArray<Record<string, unknown>>} keyName="gate" valueName="score" type="gate" />
        </StaggerItem>
        <StaggerItem>
          <ResearchBars title="Parameter fragility" subtitle="One-at-a-time perturbation selection score" data={p.fragility as unknown as ReadonlyArray<Record<string, unknown>>} keyName="parameter" valueName="score" type="fragility" />
        </StaggerItem>
      </Stagger>
      <Stagger className="grid gap-5 xl:grid-cols-2">
        <StaggerItem>
          <SampleComparisonTable snapshot={snapshot} />
        </StaggerItem>
        <StaggerItem>
          <StrategyComparison snapshot={snapshot} />
        </StaggerItem>
      </Stagger>
      <Reveal>
        <GenerationHistory snapshot={snapshot} />
      </Reveal>
    </>
  );
}

function SampleComparisonTable({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <section className="panel overflow-hidden">
      <div className="border-b border-subtle px-5 py-4">
        <h2 className="section-title">In sample vs out of sample</h2>
        <p className="mt-1 text-xs text-muted">Never present backtest results as live performance</p>
      </div>
      <div className="table-shell">
        <table className="w-full min-w-[560px]">
          <thead className="table-head">
            <tr>
              <th className="h-10 px-5">Sample</th>
              <th className="h-10 px-3 text-right">Sharpe</th>
              <th className="h-10 px-3 text-right">Max DD</th>
              <th className="h-10 px-5 text-right">Trades</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.performance.sampleComparisons.map((row) => (
              <tr className="table-row" key={row.label}>
                <td className="px-5 py-3">
                  <p className="text-xs text-foreground">{row.label}</p>
                  <p className="mt-0.5 text-[11px] text-muted">{row.detail}</p>
                  <span className="mt-1 inline-block rounded-full border border-violet/30 px-1.5 py-0.5 font-mono text-[9px] text-violet">
                    {row.sample === "in_sample" ? "IN SAMPLE" : "OUT OF SAMPLE"}
                  </span>
                </td>
                <NumberCell>{row.sharpe.toFixed(2)}</NumberCell>
                <NumberCell>
                  <span className="text-negative">{percent(row.maxDrawdown)}</span>
                </NumberCell>
                <NumberCell className="px-5">{row.trades}</NumberCell>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StrategyComparison({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <section className="panel overflow-hidden">
      <div className="border-b border-subtle px-5 py-4">
        <h2 className="section-title">Strategy comparison</h2>
        <p className="mt-1 text-xs text-muted">Historical metrics; not live performance</p>
      </div>
      <div className="table-shell">
        <table className="w-full min-w-[520px]">
          <thead className="table-head">
            <tr>
              <th className="h-10 px-5">Strategy</th>
              <th className="h-10 px-3 text-right">Sharpe</th>
              <th className="h-10 px-3 text-right">Max DD</th>
              <th className="h-10 px-5 text-right">Trades</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.performance.comparisons.map((s) => (
              <tr className="table-row" key={s.name}>
                <td className="mono px-5 py-3 text-xs">{s.name}</td>
                <NumberCell>{s.sharpe.toFixed(2)}</NumberCell>
                <NumberCell>
                  <span className="text-negative">{percent(s.maxDrawdown)}</span>
                </NumberCell>
                <NumberCell className="px-5">{s.trades}</NumberCell>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function GenerationHistory({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <section className="panel overflow-hidden">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="section-title">Strategy generation history</h2>
            <p className="mt-1 text-xs text-muted">Improvement path from repository research progress · historical only</p>
          </div>
          <span className="rounded-full border border-violet/40 bg-violet/10 px-2 py-1 font-mono text-[10px] text-violet">HISTORICAL</span>
        </div>
      </div>
      <div className="table-shell">
        <table className="w-full min-w-[980px]">
          <thead className="table-head">
            <tr>
              <th className="h-10 px-5">Evaluated</th>
              <th className="h-10 px-3">Gen</th>
              <th className="h-10 px-3">Strategy</th>
              <th className="h-10 px-3 text-right">Sharpe</th>
              <th className="h-10 px-3 text-right">Max DD</th>
              <th className="h-10 px-3 text-right">Trades</th>
              <th className="h-10 px-3 text-right">Score</th>
              <th className="h-10 px-5">Note</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.performance.generationHistory.map((row) => (
              <tr className="table-row" key={`${row.strategy}-${row.evaluatedAt}-${row.score}`}>
                <td className="mono px-5 py-3 text-[11px] text-muted">
                  {new Date(row.evaluatedAt).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC
                </td>
                <NumberCell>{row.generation}</NumberCell>
                <td className="px-3 py-3">
                  <span className="mono text-xs">{row.strategy}</span>
                  {row.deployed ? <span className="ml-2 font-mono text-[9px] text-cyan">DEPLOYED</span> : null}
                  {row.correction ? <span className="ml-2 font-mono text-[9px] text-warning">CORRECTION</span> : null}
                </td>
                <NumberCell>{row.meanSharpe.toFixed(2)}</NumberCell>
                <NumberCell>
                  <span className="text-negative">{percent(row.maxDrawdown)}</span>
                </NumberCell>
                <NumberCell>{row.trades}</NumberCell>
                <NumberCell strong>{row.score.toFixed(3)}</NumberCell>
                <td className="max-w-xs px-5 py-3 text-xs text-secondary">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SystemView({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <>
      <Reveal>
      <section className="grid gap-5 xl:grid-cols-12">
        <section className="panel p-5 xl:col-span-8">
          <div className="mb-5">
            <h2 className="section-title">Data source health</h2>
            <p className="mt-1 text-xs text-muted">Availability and freshness for every current adapter dependency</p>
          </div>
          <div className="space-y-0">
            {snapshot.system.sources.map((source) => (
              <div className="flex items-center justify-between gap-4 border-t border-subtle py-3" key={source.source}>
                <div>
                  <p className="text-sm text-foreground">{source.source}</p>
                  <p className="mt-0.5 text-xs text-muted">{source.detail}</p>
                </div>
                <div className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    {source.status === "delayed" ? (
                      <span className="font-mono text-[10px] tracking-[0.08em] text-warning">STALE</span>
                    ) : null}
                    <Freshness value={source} compact />
                  </div>
                  <p className="mt-1 font-mono text-[10px] text-muted">
                    {new Date(source.asOf).toLocaleString("en-US", {
                      timeZone: "America/New_York",
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                      timeZoneName: "short",
                    })}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
        <section className="panel p-5 xl:col-span-4">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-cyan" />
            <h2 className="section-title">Adapter state</h2>
          </div>
          <div className="mt-4">
            <Freshness value={snapshot.system.api} />
          </div>
          <p className="mt-4 text-xs leading-5 text-secondary">
            The dashboard falls back to typed demo data whenever the adapter is unavailable. Credentials remain server-side and are never requested by the browser.
          </p>
          <div className="mt-5 border-t border-subtle pt-4">
            <p className="eyebrow">Pipeline errors</p>
            <div className="mt-3 space-y-2">
              {snapshot.pipeline.errors.length ? (
                snapshot.pipeline.errors.map((error) => <PanelAlert key={error} title="Pipeline" detail={error} tone="negative" />)
              ) : (
                <p className="text-xs text-secondary">No pipeline errors in the latest snapshot.</p>
              )}
            </div>
          </div>
        </section>
      </section>
      </Reveal>
      <Reveal>
      <section className="panel overflow-hidden">
        <div className="border-b border-subtle px-5 py-4">
          <h2 className="section-title">Configuration & governance</h2>
          <p className="mt-1 text-xs text-muted">Read-only. Enforced controls are visually separated from configuration-only rules.</p>
        </div>
        <div className="table-shell">
          <table className="w-full min-w-[720px]">
            <thead className="table-head">
              <tr>
                <th className="h-10 px-5">Control</th>
                <th className="h-10 px-3">Value</th>
                <th className="h-10 px-3">State</th>
                <th className="h-10 px-5">Detail</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.system.governance.map((row) => (
                <tr className="table-row" key={row.name}>
                  <td className="px-5 py-3 text-xs text-foreground">{row.name}</td>
                  <td className="mono px-3 py-3 text-xs text-secondary">{row.value}</td>
                  <td className="px-3 py-3">
                    {row.state === "enforced" ? (
                      <span className="font-mono text-[11px] text-positive">Enforced</span>
                    ) : (
                      <span className="font-mono text-[11px] text-warning">Configured · not enforced</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-xs text-secondary">{row.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      </Reveal>
      <Reveal>
      <section className="panel p-5">
        <h2 className="section-title">Runtime boundaries</h2>
        <p className="mt-1 text-xs text-muted">Visible limitations are surfaced rather than concealed</p>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {snapshot.system.warnings.concat(snapshot.warnings).map((warning) => (
            <PanelAlert key={warning} title="Integration limitation" detail={warning} tone="warning" />
          ))}
        </div>
      </section>
      </Reveal>
    </>
  );
}
