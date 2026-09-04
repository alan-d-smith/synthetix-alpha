"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { Check, ChevronDown, Copy, Database, LoaderCircle, Play, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { requestDryPipeline, submitPaperTrade, type DryPipelineResponse, type PaperSubmitResponse } from "@/lib/api";
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
type DryRunState = "idle" | "running" | "success" | "error";
type SubmitState = "idle" | "confirm" | "submitting" | "success" | "error";

function isPaperExecutable(candidate: Candidate | null | undefined): boolean {
  if (!candidate) return false;
  const order = candidate.order;
  return (
    candidate.critic.decision === "APPROVED" &&
    candidate.risk === "APPROVED" &&
    Boolean(order) &&
    order!.resolution === "resolved" &&
    (order!.executable !== false) &&
    order!.legs.length > 0 &&
    order!.legs.every((leg) => leg.resolved)
  );
}

const stageColors: Record<string, string> = {
  complete: "bg-cyan",
  active: "bg-cyan",
  blocked: "bg-negative",
  pending: "bg-muted",
};

const stageStatusLabel: Record<string, string> = {
  complete: "Complete",
  active: "Active",
  blocked: "Blocked",
  pending: "Pending",
};

const statusTone: Record<RiskStatus, string> = {
  APPROVED: "text-positive",
  HALTED: "text-negative",
  PENDING: "text-warning",
  UNAVAILABLE: "text-negative",
};

const pageCopy: Record<Page, [string, string]> = {
  command: ["Command Center", "Paper options command center — AI-assisted, operator-controlled"],
  pipeline: ["Pipeline", "Decision audit for the latest paper run"],
  opportunities: ["Opportunities", "Volatility setups ranked by the current decision system"],
  portfolio: ["Portfolio", "Current paper account posture and execution record"],
  research: ["Research", "Historical strategy evidence and verification"],
  system: ["System", "Data freshness, adapter state, and runtime boundaries"],
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
  const [title, subtitle] = pageCopy[page];
  if (page === "command") {
    return (
      <div className="mx-auto max-w-[1800px] space-y-10">
        <StatusBrandBar title={title} subtitle={subtitle} snapshot={snapshot} />
        <section id="command" aria-labelledby="section-command-title" className="scroll-mt-16 space-y-8">
          <SectionHeading id="section-command-title" title="Overview" detail="Account posture, lead decision, and enforced risk envelope" />
          <CommandOverview snapshot={snapshot} />
        </section>
        <section id="pipeline" aria-labelledby="section-pipeline-title" className="scroll-mt-16 space-y-8">
          <SectionHeading id="section-pipeline-title" title="Pipeline" detail={pageCopy.pipeline[1]} />
          <PipelineView snapshot={snapshot} />
        </section>
        <section id="opportunities" aria-labelledby="section-opportunities-title" className="scroll-mt-16 space-y-8">
          <SectionHeading id="section-opportunities-title" title="Opportunities" detail={pageCopy.opportunities[1]} />
          <OpportunitiesView snapshot={snapshot} />
        </section>
        <section id="portfolio" aria-labelledby="section-portfolio-title" className="scroll-mt-16 space-y-8">
          <SectionHeading id="section-portfolio-title" title="Portfolio" detail={pageCopy.portfolio[1]} />
          <PortfolioView snapshot={snapshot} />
        </section>
        <section id="research" aria-labelledby="section-research-title" className="scroll-mt-16 space-y-8">
          <SectionHeading id="section-research-title" title="Research" detail={pageCopy.research[1]} />
          <ResearchView snapshot={snapshot} />
        </section>
        <section id="system" aria-labelledby="section-system-title" className="scroll-mt-16 space-y-8">
          <SectionHeading id="section-system-title" title="System" detail={pageCopy.system[1]} />
          <SystemView snapshot={snapshot} />
        </section>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1800px] space-y-8">
      <StatusBrandBar title={title} subtitle={subtitle} snapshot={snapshot} />
      {page === "pipeline" ? <PipelineView snapshot={snapshot} /> : null}
      {page === "opportunities" ? <OpportunitiesView snapshot={snapshot} /> : null}
      {page === "portfolio" ? <PortfolioView snapshot={snapshot} /> : null}
      {page === "research" ? <ResearchView snapshot={snapshot} /> : null}
      {page === "system" ? <SystemView snapshot={snapshot} /> : null}
    </div>
  );
}

function SectionHeading({ id, title, detail }: { id: string; title: string; detail: string }) {
  return (
    <div className="border-b border-subtle pb-3">
      <h2 id={id} className="font-display text-lg font-semibold tracking-[-0.03em]">
        {title}
      </h2>
      <p className="mt-1 text-xs text-secondary">{detail}</p>
    </div>
  );
}

function adapterConnection(snapshot: DashboardSnapshot) {
  if (snapshot.mode === "mock") return { label: "Demo fallback", tone: "text-violet" as const, detail: "Adapter not reached — showing typed demo snapshot." };
  const status = snapshot.system.api.status;
  if (status === "fresh") return { label: "Connected", tone: "text-positive" as const, detail: snapshot.system.api.detail ?? "Dashboard adapter responding." };
  if (status === "refreshing") return { label: "Refreshing", tone: "text-cyan" as const, detail: "Snapshot refresh in progress." };
  if (status === "delayed") return { label: "Stale", tone: "text-warning" as const, detail: "Adapter response is delayed." };
  return { label: "Unavailable", tone: "text-negative" as const, detail: "Adapter health reports unavailable." };
}

function StatusBrandBar({ title, subtitle, snapshot }: { title: string; subtitle: string; snapshot: DashboardSnapshot }) {
  const { refresh } = useDashboard();
  const [dryState, setDryState] = useState<DryRunState>("idle");
  const [result, setResult] = useState<DryPipelineResponse | null>(null);
  const connection = adapterConnection(snapshot);
  const demo = snapshot.mode === "mock";

  async function run() {
    if (dryState === "running" || demo) return;
    setDryState("running");
    setResult(null);
    const response = await requestDryPipeline();
    setResult(response);
    setDryState(response.available && response.status !== "error" ? "success" : "error");
    if (response.available) refresh();
  }

  const buttonLabel =
    dryState === "running" ? "Running dry pipeline…" : dryState === "success" ? "Dry run complete" : dryState === "error" ? "Dry run failed — retry" : "Run dry pipeline";

  return (
    <>
      <div className="panel overflow-hidden p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <p className="eyebrow">Synthetix Alpha</p>
            <h1 className="page-title mt-1 break-words">{title}</h1>
            <p className="mt-1 max-w-2xl text-sm text-secondary">{subtitle}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-1 font-mono text-[10px] font-medium tracking-[0.1em] text-warning">
              PAPER TRADING
            </span>
            <span className="rounded-full border border-cyan/35 bg-cyan/10 px-2 py-1 font-mono text-[10px] font-medium tracking-[0.1em] text-cyan">
              COPILOT
            </span>
            <span className="rounded-full border border-subtle px-2 py-1 font-mono text-[10px] font-medium tracking-[0.1em] text-secondary">
              MANUAL TRIGGER
            </span>
            {demo ? (
              <span className="rounded-full border border-violet/40 bg-violet/10 px-2 py-1 font-mono text-[10px] font-medium tracking-[0.1em] text-violet">
                DEMO DATA
              </span>
            ) : null}
            <Button
              variant="primary"
              onClick={run}
              disabled={demo || dryState === "running"}
              aria-busy={dryState === "running"}
              aria-live="polite"
              className={cn(
                dryState === "success" && "border-positive/40 bg-positive/10 text-positive",
                dryState === "error" && "border-negative/40 bg-negative/10 text-negative",
              )}
            >
              {dryState === "running" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              {buttonLabel}
            </Button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 border-t border-subtle pt-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatusChip label="Connection" value={connection.label} tone={connection.tone} detail={connection.detail} />
          <StatusChip
            label="Operating mode"
            value="Copilot"
            tone="text-cyan"
            detail="AI proposes; operator reviews and may submit PAPER trades. No autonomous trading loop."
          />
          <StatusChip
            label="Pipeline"
            value={
              snapshot.pipeline.stages.find((s) => s.stage === "EXECUTE")?.status === "active"
                ? "Awaiting approval"
                : snapshot.pipeline.finalState === "partial"
                  ? "Partial"
                  : snapshot.pipeline.finalState
            }
            tone={snapshot.pipeline.finalState === "halted" ? "text-negative" : "text-secondary"}
            detail={`Run ${snapshot.pipeline.id}`}
          />
          <StatusChip
            label="As of"
            value={new Date(snapshot.asOf).toLocaleTimeString("en-US", {
              hour: "2-digit",
              minute: "2-digit",
              timeZone: "America/New_York",
              timeZoneName: "short",
            })}
            tone="text-secondary"
            detail={snapshot.system.api.source}
          />
        </div>
      </div>
      {result ? (
        <DryPipelineResultPanel result={result} state={dryState} />
      ) : null}
    </>
  );
}

function StatusChip({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: string;
}) {
  return (
    <div className="min-w-0 rounded-control border border-subtle bg-canvas/60 px-3 py-2.5">
      <p className="eyebrow">{label}</p>
      <p className={cn("mt-1 font-mono text-xs font-medium", tone)}>{value}</p>
      <p className="mt-1 text-[11px] leading-4 text-muted">{detail}</p>
    </div>
  );
}

function DryPipelineResultPanel({ result, state }: { result: DryPipelineResponse; state: DryRunState }) {
  const tone = state === "success" ? "info" : "negative";
  return (
    <div className="space-y-3" aria-live="polite">
      <PanelAlert
        title={state === "success" ? "Dry pipeline succeeded" : "Dry pipeline did not complete"}
        detail={result.detail}
        tone={tone}
      />
      {result.summary ? (
        <div className="panel grid gap-2 p-4 sm:grid-cols-2 xl:grid-cols-4">
          {(
            [
              ["Screened", result.summary.screened],
              ["Critic approved", result.summary.criticApproved],
              ["Risk approved", result.summary.riskApproved],
              ["Risk halts", result.summary.riskHalts],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-control border border-subtle px-3 py-2">
              <p className="eyebrow">{label}</p>
              <p className="mono mt-1 text-sm">{value}</p>
            </div>
          ))}
        </div>
      ) : null}
      {result.errors?.length ? (
        <div className="space-y-2">
          {result.errors.map((error) => (
            <PanelAlert key={error} title="Pipeline error" detail={error} tone="negative" />
          ))}
        </div>
      ) : null}
      {result.raw ? (
        <details className="panel p-4 text-xs">
          <summary className="cursor-pointer font-mono text-[11px] text-secondary">View adapter response</summary>
          <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-muted">
            {JSON.stringify(result.raw, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

export function SignalTrace({ snapshot, full = false }: { snapshot: DashboardSnapshot; full?: boolean }) {
  const reduced = usePrefersReducedMotion();
  return (
    <section aria-label="Pipeline progress" className={cn("panel overflow-hidden", full ? "p-5" : "px-5 py-4")}>
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="eyebrow">Signal Trace</p>
          <p className="mt-1 text-xs text-secondary">SCREEN → GATHER → CRITIQUE → FORM → RISK → EXECUTE</p>
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
          const pending = stage.status === "pending";
          return (
            <motion.li
              key={stage.stage}
              className="relative min-w-0 px-0 py-2 sm:pr-3"
              variants={reduced ? undefined : fadeUp}
            >
              <div className="mb-2 flex items-center">
                <motion.span
                  className={cn(
                    "h-2.5 w-2.5 rounded-full",
                    stageColors[stage.status],
                    active && "shadow-[0_0_10px_var(--data-cyan)]",
                    quiet && "opacity-70",
                    pending && "opacity-45",
                  )}
                  aria-hidden="true"
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
              <div className="flex flex-wrap items-center gap-2">
                <p className={cn("font-mono text-[10px] font-medium tracking-[0.12em]", quiet ? "text-muted" : "text-secondary")}>
                  {stage.stage}
                </p>
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.5 font-mono text-[9px] tracking-[0.08em]",
                    blocked && "bg-negative/10 text-negative",
                    active && "bg-cyan/10 text-cyan",
                    quiet && "bg-surface-hover text-muted",
                    pending && "text-muted",
                  )}
                >
                  {stageStatusLabel[stage.status] ?? stage.status}
                </span>
              </div>
              <p className={cn("mt-1 text-xs leading-4", blocked ? "text-negative" : quiet ? "text-secondary" : "text-foreground")}>
                {stage.result}
              </p>
            </motion.li>
          );
        })}
      </motion.ol>
      {snapshot.pipeline.stages.length === 0 ? (
        <EmptyState title="No pipeline candidates in the latest run." detail="The adapter returned an empty stage list for this snapshot." />
      ) : null}
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
      <div className="flex overflow-x-auto pb-1 [-webkit-overflow-scrolling:touch]">
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

function RiskGuardsPanel({ snapshot, compact = false }: { snapshot: DashboardSnapshot; compact?: boolean }) {
  const governance = snapshot.system.governance;
  const enforced = governance.filter((row) => row.state === "enforced");
  const configured = governance.filter((row) => row.state === "configured_not_enforced");

  return (
    <section className="panel p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Risk Guards & Parameters</h2>
          <p className="mt-1 text-xs text-muted">Read-only governance — parameters cannot be edited from the dashboard</p>
        </div>
        <ShieldCheck className="h-4 w-4 shrink-0 text-cyan" aria-hidden="true" />
      </div>
      {governance.length ? (
        <div className="space-y-4">
          <ul className="space-y-2">
            {enforced.map((row) => (
              <li key={row.name} className="flex flex-col gap-1 border-b border-subtle/70 pb-2 text-xs last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-foreground">{row.name}</span>
                <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                  <span className="mono text-secondary">{row.value}</span>
                  <span className="font-mono text-[9px] tracking-[0.08em] text-positive">ENFORCED</span>
                </div>
              </li>
            ))}
          </ul>
          {configured.length ? (
            <div className="border-t border-subtle pt-4">
              <p className="eyebrow">Configured · not enforced</p>
              <ul className="mt-2 space-y-2">
                {configured.map((row) => (
                  <li key={row.name} className="flex flex-col gap-1 border-b border-subtle/70 pb-2 text-xs last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
                    <span className="text-foreground">{row.name}</span>
                    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                      <span className="mono text-secondary">{row.value}</span>
                      <span className="font-mono text-[9px] tracking-[0.08em] text-warning">CONFIGURED · NOT ENFORCED</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-warning">Governance rows were not returned by the adapter.</p>
      )}
      {!compact ? (
        <p className="mt-4 text-[11px] leading-4 text-muted">
          Full governance detail and runtime limitations live under System.
        </p>
      ) : null}
    </section>
  );
}

function PipelineRunSummary({ snapshot }: { snapshot: DashboardSnapshot }) {
  const execute = snapshot.pipeline.stages.find((s) => s.stage === "EXECUTE");
  const risk = snapshot.pipeline.stages.find((s) => s.stage === "RISK");
  const form = snapshot.pipeline.stages.find((s) => s.stage === "FORM");
  const ready = execute?.status === "active";
  return (
    <section className="panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">Latest run</p>
          <h2 className="section-title mt-1">Run {snapshot.pipeline.id}</h2>
          <p className="mt-1 text-xs text-secondary">
            {new Date(snapshot.pipeline.asOf).toLocaleString("en-US", { timeZone: "America/New_York", timeZoneName: "short" })}
          </p>
        </div>
        <span
          className={cn(
            "rounded-full border px-2 py-1 font-mono text-[10px]",
            ready ? "border-cyan/35 bg-cyan/10 text-cyan" : "border-subtle text-secondary",
          )}
        >
          {ready ? "AWAITING OPERATOR" : "PAPER COPILOT"}
        </span>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {snapshot.pipeline.stages.slice(0, 3).map((stage) => (
          <div key={stage.stage} className="rounded-control border border-subtle px-3 py-2">
            <p className="font-mono text-[10px] text-muted">{stage.stage}</p>
            <p className="mt-1 text-xs text-secondary">{stage.result}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 rounded-control border border-subtle bg-canvas/50 px-3 py-3 text-xs text-secondary">
        <p>
          <span className="font-mono text-foreground">FORM</span> · {form?.result ?? "—"}
        </p>
        <p className="mt-1">
          <span className="font-mono text-foreground">RISK</span> · {risk?.result ?? "—"}
        </p>
        <p className="mt-1">
          <span className="font-mono text-foreground">EXECUTE</span> · {execute?.result ?? "No order reached execution"}
        </p>
      </div>
    </section>
  );
}

function ResearchSummaryCompact({ snapshot }: { snapshot: DashboardSnapshot }) {
  const p = snapshot.performance;
  const unavailable = !p.name || p.name === "unavailable" || p.equity.length === 0;
  if (unavailable) {
    return (
      <section className="panel p-5">
        <p className="eyebrow">Historical research</p>
        <EmptyState title="Research artifacts unavailable" detail="Historical strategy evidence was not returned by the adapter." />
      </section>
    );
  }
  return (
    <section className="panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">Historical research</p>
          <h2 className="section-title mt-1">{p.name}</h2>
          <p className="mt-2 text-xs text-secondary">
            Sharpe <span className="mono text-foreground">{p.sharpe.toFixed(2)}</span>
            {" · "}
            Max DD <span className="mono text-negative">{percent(p.maxDrawdown)}</span>
            {" · "}
            Win rate <span className="mono text-foreground">{percent(p.winRate, 0)}</span>
            {" · "}
            <span className="mono text-foreground">{p.trades}</span> trades
          </p>
        </div>
        <span className="rounded-full border border-violet/40 bg-violet/10 px-2 py-1 font-mono text-[10px] text-violet">
          NOT LIVE PERFORMANCE
        </span>
      </div>
      <p className="mt-3 text-xs text-muted">
        Full charts and verification tables are in the Research section below.
      </p>
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
  const { refresh } = useDashboard();
  const o = candidate?.order;
  const executable = isPaperExecutable(candidate);
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [submitResult, setSubmitResult] = useState<PaperSubmitResponse | null>(null);

  useEffect(() => {
    setSubmitState("idle");
    setSubmitResult(null);
  }, [candidate?.ticker]);

  async function onSubmitPaper() {
    if (!candidate || !o || submitState === "submitting") return;
    setSubmitState("submitting");
    const response = await submitPaperTrade({
      symbol: candidate.ticker,
      clientOrderId: o.clientOrderId || undefined,
    });
    setSubmitResult(response);
    setSubmitState(response.available && response.ok ? "success" : "error");
    if (response.available) refresh();
  }

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
                {o.structure ? (
                  <p className="mt-2 text-xs text-muted">
                    Structure · <span className="mono text-secondary">{o.structure}</span>
                  </p>
                ) : null}
                {o.limitPrice != null ? (
                  <p className="mt-1 text-xs text-muted">
                    Limit ·{" "}
                    <span className="mono text-secondary">
                      {o.limitPrice < 0 ? `credit ${currency(Math.abs(o.limitPrice))}` : `debit ${currency(o.limitPrice)}`}
                    </span>
                  </p>
                ) : null}
                <div className="mt-3 space-y-2">
                  {o.legs.map((leg, index) => (
                    <div className="flex justify-between gap-3 font-mono text-[11px]" key={`${leg.symbol}-${index}`}>
                      <span className={leg.side === "short" ? "text-negative" : "text-positive"}>
                        {leg.side.toUpperCase()} {leg.ratio} {leg.type.toUpperCase()}
                        {leg.delta ? ` · ${leg.delta}Δ` : ""}
                        {leg.strike != null ? ` · ${leg.strike}` : ""}
                      </span>
                      <span className={cn("truncate text-right", leg.resolved ? "text-foreground" : "text-muted")}>
                        {leg.resolved ? leg.symbol : "Option leg unresolved"}
                      </span>
                    </div>
                  ))}
                </div>
                {!executable ? (
                  <p className="mt-3 border-t border-subtle pt-3 text-xs text-negative">
                    Execution blocked — critic/risk approval or OCC leg resolution is incomplete.
                  </p>
                ) : (
                  <p className="mt-3 border-t border-subtle pt-3 text-xs text-cyan">
                    Critic + risk approved · executable OCC legs · paper trading only.
                  </p>
                )}
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
          {executable ? (
            <TradeReviewPanel
              candidate={candidate}
              submitState={submitState}
              submitResult={submitResult}
              onReview={() => setSubmitState("confirm")}
              onCancel={() => setSubmitState("idle")}
              onSubmit={onSubmitPaper}
            />
          ) : null}
          {submitResult ? (
            <PanelAlert
              title={
                submitState === "success"
                  ? submitResult.filled
                    ? "PAPER ORDER FILLED"
                    : "PAPER ORDER SUBMITTED"
                  : "Paper submission did not succeed"
              }
              detail={
                [
                  submitResult.symbol,
                  submitResult.structure,
                  submitResult.orderId ? `Alpaca Order ID: ${submitResult.orderId}` : null,
                  submitResult.status ? `Status: ${String(submitResult.status).toUpperCase()}` : null,
                  submitResult.detail,
                ]
                  .filter(Boolean)
                  .join(" · ")
              }
              tone={submitState === "success" ? "info" : "negative"}
            />
          ) : null}
          <footer className="border-t border-subtle pt-4">
            <Freshness value={{ source: "Candidate context", asOf: candidate.updatedAt, status: "fresh" }} />
          </footer>
        </div>
      </SheetContent>
      ) : null}
    </Sheet>
  );
}

function TradeReviewPanel({
  candidate,
  submitState,
  submitResult,
  onReview,
  onCancel,
  onSubmit,
}: {
  candidate: Candidate;
  submitState: SubmitState;
  submitResult: PaperSubmitResponse | null;
  onReview: () => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const o = candidate.order!;
  const submitting = submitState === "submitting";
  const confirmed = submitState === "confirm" || submitting || submitState === "success";
  return (
    <section className="rounded-control border border-cyan/30 bg-cyan/5 p-4" aria-label="Trade review">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="eyebrow">Trade review</p>
          <h3 className="mt-1 font-display text-base font-semibold tracking-[-0.02em]">
            {candidate.ticker} · paper submission
          </h3>
        </div>
        <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-1 font-mono text-[10px] text-warning">
          PAPER ONLY
        </span>
      </div>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-muted">Underlying</dt>
          <dd className="mono text-foreground">{candidate.price != null ? currency(candidate.price) : "Unavailable"}</dd>
        </div>
        <div>
          <dt className="text-muted">Structure</dt>
          <dd className="mono text-foreground">{o.structure ?? "put_credit_spread"}</dd>
        </div>
        <div>
          <dt className="text-muted">Quantity</dt>
          <dd className="mono text-foreground">{o.contracts}</dd>
        </div>
        <div>
          <dt className="text-muted">Est. max loss</dt>
          <dd className="mono text-foreground">{currency(o.maxLoss)}</dd>
        </div>
        <div>
          <dt className="text-muted">Critic</dt>
          <dd className="mono text-foreground">{candidate.critic.confidence} · {candidate.critic.decision}</dd>
        </div>
        <div>
          <dt className="text-muted">Risk</dt>
          <dd className="mono text-positive">{candidate.risk}</dd>
        </div>
      </dl>
      <p className="mt-3 text-xs leading-5 text-secondary">{candidate.critic.thesis}</p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        {submitState === "idle" || submitState === "error" ? (
          <Button variant="primary" onClick={onReview} className="w-full sm:w-auto">
            Review & Submit Paper Trade
          </Button>
        ) : null}
        {confirmed && submitState !== "success" ? (
          <>
            <Button
              variant="primary"
              onClick={onSubmit}
              disabled={submitting}
              aria-busy={submitting}
              className="w-full sm:w-auto"
            >
              {submitting ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
              {submitting ? "Submitting to Alpaca Paper…" : "Submit to Alpaca Paper"}
            </Button>
            <Button variant="ghost" onClick={onCancel} disabled={submitting} className="w-full sm:w-auto">
              Cancel
            </Button>
          </>
        ) : null}
        {submitState === "success" && submitResult?.status === "duplicate" ? (
          <p className="text-xs text-warning">Duplicate blocked — matching client order id already exists.</p>
        ) : null}
      </div>
    </section>
  );
}

function CommandOverview({ snapshot }: { snapshot: DashboardSnapshot }) {
  const lead =
    snapshot.candidates.find((c) => c.critic.decision === "APPROVED" && c.risk === "APPROVED") ??
    snapshot.candidates.find((c) => c.critic.decision === "APPROVED") ??
    snapshot.candidates[0];
  return (
    <>
      <Reveal>
        <AccountRiskSummary snapshot={snapshot} />
      </Reveal>
      <div className="grid gap-5 xl:grid-cols-12">
        <Reveal className="min-w-0 space-y-5 xl:col-span-8">
          <section className="panel p-5">
            {lead ? (
              <>
                <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="eyebrow">Current decision</p>
                    <h2 className="section-title mt-1">
                      {lead.ticker} · {lead.critic.decision}
                    </h2>
                    <p className="mt-1 text-xs text-muted">Critic summary — not a hidden chain-of-thought dump</p>
                  </div>
                  <DecisionLabel value={lead.critic.decision} />
                </div>
                <CriticMemo candidate={lead} />
                <div className="mt-5 border-t border-subtle pt-4">
                  <p className="eyebrow">Proposed structure</p>
                  {lead.order ? (
                    <div className="mt-2 space-y-1 text-xs text-secondary">
                      <p>
                        {lead.order.contracts} contract · max loss{" "}
                        <span className="mono text-foreground">{currency(lead.order.maxLoss)}</span>
                      </p>
                      <p>
                        Resolution · <span className="mono text-foreground">{lead.order.resolution}</span>
                        {lead.order.structure ? (
                          <>
                            {" · "}
                            Structure · <span className="mono text-foreground">{lead.order.structure}</span>
                          </>
                        ) : null}
                      </p>
                      {lead.order.legs.map((leg, index) => (
                        <p key={`${leg.symbol}-${index}`} className="mono text-[11px]">
                          <span className={leg.side === "short" ? "text-negative" : "text-positive"}>
                            {leg.side.toUpperCase()} {leg.type.toUpperCase()}
                          </span>
                          {" · "}
                          {leg.resolved ? leg.symbol : "unresolved"}
                        </p>
                      ))}
                      {isPaperExecutable(lead) ? (
                        <p className="pt-2 text-cyan">Ready for operator review — open Opportunities to submit PAPER.</p>
                      ) : null}
                    </div>
                  ) : (
                    <p className="mt-2 text-xs text-muted">No formed order is available for this candidate in the latest run.</p>
                  )}
                </div>
                <div className="mt-4 border-t border-subtle pt-4">
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
          <PipelineRunSummary snapshot={snapshot} />
        </Reveal>
        <Reveal className="min-w-0 space-y-5 xl:col-span-4">
          <RiskGuardsPanel snapshot={snapshot} compact />
          <ResearchSummaryCompact snapshot={snapshot} />
        </Reveal>
      </div>
      <Reveal>
        <CompactPositions snapshot={snapshot} />
      </Reveal>
    </>
  );
}

function CompactPositions({ snapshot }: { snapshot: DashboardSnapshot }) {
  const p = snapshot.portfolio;
  if (p.positions.length === 0) {
    return (
      <section className="panel p-5">
        <p className="eyebrow">Positions</p>
        <EmptyState
          title="No open positions"
          detail={`Your paper account currently holds no option contracts. ${p.positions.length} / ${p.maxPositions} position slots used.`}
        />
      </section>
    );
  }
  return <PositionTable snapshot={snapshot} compact />;
}

function PositionTable({ snapshot, compact = false }: { snapshot: DashboardSnapshot; compact?: boolean }) {
  const empty = snapshot.portfolio.positions.length === 0;
  if (empty) {
    return (
      <section className="panel p-5">
        <p className="eyebrow">Positions</p>
        <EmptyState
          title="No open positions"
          detail={`Your paper account currently holds no option contracts. ${snapshot.portfolio.positions.length} / ${snapshot.portfolio.maxPositions} position slots used.`}
        />
      </section>
    );
  }
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
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RiskEvents({ snapshot }: { snapshot: DashboardSnapshot }) {
  const blocked = snapshot.pipeline.events.filter((event) => event.status === "blocked");
  const unprotected = snapshot.portfolio.positions.filter((p) => !p.protected);
  const hasEvents = blocked.length > 0 || unprotected.length > 0;
  return (
    <section className="panel p-5">
      <div>
        <h2 className="section-title">Risk events</h2>
        <p className="mt-1 text-xs text-muted">Halts, breaches, and execution errors in the latest run</p>
      </div>
      <div className="mt-5 space-y-3">
        {blocked.map((event) => (
          <PanelAlert key={event.id} title={`${event.stage} · ${event.ticker ?? "System"}`} detail={event.detail} tone="negative" />
        ))}
        {unprotected.map((p) => (
          <PanelAlert key={p.symbol} title="Protection review" detail={`${p.symbol} has no verified resting closing order.`} tone="warning" />
        ))}
        {!hasEvents ? (
          <EmptyState title="No risk events" detail="No halts, breaches, or execution errors in the latest run." />
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

  return (
    <>
      <Reveal>
      <section className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow">Latest run</p>
            <h2 className="mt-1 font-display text-xl font-semibold">
              {snapshot.pipeline.stages.find((s) => s.stage === "EXECUTE")?.result ?? "Dry-run pipeline audit"}
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
          <AuditStat
            label="Execution"
            value={
              snapshot.pipeline.stages.find((s) => s.stage === "EXECUTE")?.status === "active"
                ? "AWAITING APPROVAL"
                : snapshot.executions[0]?.status
                  ? String(snapshot.executions[0].status).toUpperCase()
                  : "OPERATOR"
            }
          />
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
    <Reveal>
      <OpportunityTable snapshot={snapshot} />
    </Reveal>
  );
}

function PortfolioView({ snapshot }: { snapshot: DashboardSnapshot }) {
  const { refresh, loading } = useDashboard();
  return (
    <>
      <Reveal>
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted">Paper account state from Alpaca — refresh after submission.</p>
          <Button variant="ghost" onClick={refresh} disabled={loading} aria-busy={loading}>
            {loading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
            Refresh account
          </Button>
        </div>
        <AccountRiskSummary snapshot={snapshot} />
      </Reveal>
      <div className="grid gap-5 xl:grid-cols-12">
        <Reveal className="xl:col-span-12">
          <PositionTable snapshot={snapshot} />
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
      <div className="flex flex-col gap-2 border-b border-subtle px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="section-title">Execution ledger</h2>
          <p className="mt-1 text-xs text-muted">
            submitted · pending · filled · rejected · duplicate · error — never implied fills
          </p>
        </div>
        <span className="font-mono text-[11px] text-warning">PAPER ONLY</span>
      </div>
      <div className="table-shell">
        <table className="w-full min-w-[920px]">
          <thead className="table-head">
            <tr>
              <th className="h-10 px-5">Time</th>
              <th className="h-10 px-3">Symbol</th>
              <th className="h-10 px-3">Status</th>
              <th className="h-10 px-3">Client order ID</th>
              <th className="h-10 px-3">Alpaca order ID</th>
              <th className="h-10 px-5">Detail</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.executions.map((execution) => (
              <tr className="table-row" key={`${execution.clientOrderId}-${execution.orderId ?? ""}`}>
                <td className="mono px-5 py-3 text-[11px] text-muted">
                  {execution.createdAt
                    ? new Date(execution.createdAt).toLocaleTimeString("en-US", {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                        timeZone: "America/New_York",
                      })
                    : "—"}
                </td>
                <td className="mono px-3 py-3 text-xs">
                  {execution.symbol}
                  {execution.structure ? (
                    <span className="ml-2 text-[10px] text-muted">{execution.structure}</span>
                  ) : null}
                </td>
                <td className="px-3 py-3">
                  <ExecutionLabel value={execution.status} />
                </td>
                <td className="px-3 py-3">
                  <button
                    onClick={() => navigator.clipboard?.writeText(execution.clientOrderId)}
                    className="mono inline-flex max-w-full items-center gap-1 truncate text-[11px] text-secondary hover:text-cyan"
                    aria-label={`Copy ${execution.clientOrderId}`}
                  >
                    <span className="truncate">{execution.clientOrderId}</span>
                    <Copy className="h-3 w-3 shrink-0" />
                  </button>
                </td>
                <td className="mono px-3 py-3 text-[11px] text-secondary">{execution.orderId ?? "—"}</td>
                <td className="px-5 py-3 text-xs text-secondary">{execution.detail}</td>
              </tr>
            ))}
            {snapshot.executions.length === 0 ? (
              <tr>
                <td colSpan={6}>
                  <EmptyState
                    title="No paper executions yet."
                    detail="Operator-approved Alpaca paper submissions appear here with truthful broker status."
                  />
                </td>
              </tr>
            ) : null}
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
    pending: ["Pending", "text-cyan"],
    filled: ["Filled", "text-positive"],
    rejected: ["Rejected", "text-negative"],
    cancelled: ["Cancelled", "text-muted"],
    error: ["Error", "text-negative"],
    unavailable: ["Unavailable", "text-negative"],
  };
  const [label, tone] = map[value] ?? [value, "text-secondary"];
  return <span className={cn("font-mono text-[11px]", tone)}>{label}</span>;
}

function ResearchView({ snapshot }: { snapshot: DashboardSnapshot }) {
  const p = snapshot.performance;
  const unavailable = !p.name || p.name === "unavailable" || p.equity.length === 0;
  if (unavailable) {
    return (
      <EmptyState
        title="Research artifacts unavailable"
        detail="Historical strategy evidence was not returned by the adapter. Check research datasets and regenerate the performance snapshot."
      />
    );
  }
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
        <div className="mt-5 flex overflow-x-auto border-t border-subtle pt-4 [-webkit-overflow-scrolling:touch]">
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
        <RiskGuardsPanel snapshot={snapshot} />
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
