"use client";

import { Area } from "@/components/charts/area";
import { AreaChart } from "@/components/charts/area-chart";
import { Bar } from "@/components/charts/bar";
import { BarChart } from "@/components/charts/bar-chart";
import { BarXAxis } from "@/components/charts/bar-x-axis";
import { ChartConfigProvider } from "@/components/charts/chart-config-context";
import { Grid } from "@/components/charts/grid";
import { ChartTooltip } from "@/components/charts/tooltip/chart-tooltip";
import { XAxis } from "@/components/charts/x-axis";
import { YAxis } from "@/components/charts/y-axis";
import { chartEnterTransition, usePrefersReducedMotion } from "@/lib/motion";
import type { DashboardSnapshot } from "@/lib/types";
import { currency, percent } from "@/lib/utils";

const restrainedChartMotion = {
  tooltipSpring: { stiffness: 420, damping: 42 },
  tooltipBoxSpring: { stiffness: 280, damping: 36 },
  highlightSpring: { stiffness: 320, damping: 38 },
};

const chartMargin = { top: 10, right: 12, bottom: 28, left: 52 };

function InspectionTooltip({
  title,
  value,
  detail,
}: {
  title: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="chart-tooltip min-w-[148px]">
      <p className="text-[10px] uppercase tracking-[0.1em] text-muted">{title}</p>
      {detail ? <p className="mt-1 text-[11px] text-secondary">{detail}</p> : null}
      <p className="mt-1 font-mono text-xs text-foreground">{value}</p>
    </div>
  );
}

export function PerformanceCharts({ snapshot }: { snapshot: DashboardSnapshot }) {
  const data = snapshot.performance.equity as unknown as Record<string, unknown>[];
  const reduced = usePrefersReducedMotion();
  const source =
    snapshot.performance.source === "historical" || snapshot.performance.source === "in_sample"
      ? "Historical backtest · not live or paper performance"
      : "Demo performance data · not live trading";

  return (
    <section className="panel p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Cumulative performance</h2>
          <p className="mt-1 text-xs text-muted">{source}</p>
        </div>
        <span className="rounded-full border border-violet/40 bg-violet/10 px-2 py-0.5 font-mono text-[10px] text-violet">
          HISTORICAL
        </span>
      </div>
      <ChartConfigProvider value={restrainedChartMotion}>
        <div className="h-[230px]" aria-label="Historical equity curve chart">
          <AreaChart
            animationDuration={reduced ? 0 : 720}
            aspectRatio="auto"
            className="h-full w-full"
            data={data}
            enterTransition={chartEnterTransition}
            margin={chartMargin}
            xDataKey="date"
          >
            <Grid
              fadeHorizontal
              hideHorizontalEdgeLines
              numTicksRows={4}
              stroke="var(--chart-grid)"
              strokeDasharray="0"
              strokeOpacity={0.9}
              strokeWidth={1}
              vertical={false}
            />
            <XAxis numTicks={6} />
            <YAxis formatValue={(v) => `$${Math.round(v / 1000)}k`} numTicks={4} />
            <Area
              animate={!reduced}
              dataKey="equity"
              fill="var(--chart-line-primary)"
              fillOpacity={0.16}
              gradientToOpacity={0}
              showHighlight
              stroke="var(--chart-line-primary)"
              strokeWidth={1.8}
            />
            <ChartTooltip
              damping={0}
              content={({ point }) => (
                <InspectionTooltip
                  detail={String(point.date ?? "")}
                  title="Equity"
                  value={currency(Number(point.equity ?? 0))}
                />
              )}
              showDatePill={false}
            />
          </AreaChart>
        </div>
        <div className="mt-4 border-t border-subtle pt-3">
          <p className="eyebrow">Drawdown</p>
          <div className="mt-2 h-[68px]" aria-label="Historical drawdown chart">
            <AreaChart
              animationDuration={reduced ? 0 : 720}
              aspectRatio="auto"
              className="h-full w-full"
              data={data}
              enterTransition={chartEnterTransition}
              margin={{ top: 4, right: 8, bottom: 4, left: 8 }}
              xDataKey="date"
            >
              <Grid horizontal={false} vertical={false} />
              <Area
                animate={!reduced}
                dataKey="drawdown"
                fill="var(--negative)"
                fillOpacity={0.14}
                gradientToOpacity={0}
                showHighlight={false}
                stroke="var(--negative)"
                strokeWidth={1.4}
              />
              <ChartTooltip
                damping={0}
                content={({ point }) => (
                  <InspectionTooltip
                    detail={String(point.date ?? "")}
                    title="Drawdown"
                    value={percent(Number(point.drawdown ?? 0))}
                  />
                )}
                showCrosshair
                showDatePill={false}
                showDots={false}
              />
            </AreaChart>
          </div>
        </div>
      </ChartConfigProvider>
      <p className="sr-only">
        Equity path from {currency(snapshot.performance.equity[0]?.equity ?? 0)} to{" "}
        {currency(snapshot.performance.equity[snapshot.performance.equity.length - 1]?.equity ?? 0)} over{" "}
        {snapshot.performance.period}.
      </p>
    </section>
  );
}

export function ResearchBars({
  title,
  subtitle,
  data,
  keyName,
  valueName,
  type,
}: {
  title: string;
  subtitle: string;
  data: ReadonlyArray<Record<string, unknown>>;
  keyName: string;
  valueName: string;
  type: "returns" | "gate" | "fragility" | "pnl";
}) {
  const reduced = usePrefersReducedMotion();
  const rows = data.map((entry) => {
    const value = Number(entry[valueName] ?? 0);
    let fill = "var(--data-violet)";
    if (type === "returns") fill = value >= 0 ? "var(--positive)" : "var(--negative)";
    else if (type === "gate") fill = entry.deployed ? "var(--data-cyan)" : "#3a4658";
    else if (type === "fragility" || type === "pnl") fill = "var(--data-violet)";
    return { ...entry, fill };
  });

  const formatValue = (value: number) => {
    if (type === "returns") return percent(value);
    if (type === "pnl") return `${value} trades`;
    return value.toFixed(2);
  };

  return (
    <section className="panel p-5">
      <div>
        <h2 className="section-title">{title}</h2>
        <p className="mt-1 text-xs text-muted">{subtitle}</p>
      </div>
      <ChartConfigProvider value={restrainedChartMotion}>
        <div className="mt-5 h-[220px]">
          <BarChart
            animationDuration={reduced ? 0 : 720}
            aspectRatio="auto"
            barGap={0.28}
            className="h-full w-full"
            data={rows}
            enterTransition={chartEnterTransition}
            margin={{ top: 8, right: 8, bottom: type === "pnl" ? 44 : 28, left: 44 }}
            xDataKey={keyName}
          >
            <Grid
              fadeHorizontal
              hideHorizontalEdgeLines
              highlightRowValues={[0]}
              numTicksRows={4}
              stroke="var(--chart-grid)"
              strokeDasharray="0"
              vertical={false}
            />
            <BarXAxis maxLabels={12} showAllLabels={type !== "pnl"} />
            <YAxis
              formatValue={(v) => (type === "returns" ? percent(v, 0) : type === "pnl" ? String(Math.round(v)) : v.toFixed(1))}
              numTicks={4}
            />
            <Bar
              animate={!reduced}
              dataKey={valueName}
              fill="var(--chart-line-primary)"
              lineCap={2}
              stroke="var(--chart-line-primary)"
            />
            <ChartTooltip
              damping={0}
              content={({ point }) => (
                <InspectionTooltip
                  detail={String(point[keyName] ?? "")}
                  title={title}
                  value={formatValue(Number(point[valueName] ?? 0))}
                />
              )}
              showDatePill={false}
              showDots={false}
            />
          </BarChart>
        </div>
      </ChartConfigProvider>
    </section>
  );
}
