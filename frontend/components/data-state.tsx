import { AlertTriangle, CheckCircle2, Clock3, LoaderCircle, WifiOff } from "lucide-react";
import type { DataFreshness, FreshnessStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const config: Record<FreshnessStatus, { label: string; color: string; icon: typeof CheckCircle2 }> = {
  fresh: { label: "Fresh", color: "text-cyan", icon: CheckCircle2 },
  refreshing: { label: "Refreshing", color: "text-cyan", icon: LoaderCircle },
  delayed: { label: "Delayed", color: "text-warning", icon: Clock3 },
  unavailable: { label: "Unavailable", color: "text-negative", icon: WifiOff },
};

export function Freshness({ value, compact = false }: { value: DataFreshness; compact?: boolean }) {
  const item = config[value.status];
  const Icon = item.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[11px] leading-4", item.color)} title={`${value.source} · ${value.asOf}`}>
      <Icon className={cn("h-3 w-3", value.status === "refreshing" && "animate-spin")} />
      <span>{compact ? item.label : `${value.source} · ${item.label}`}</span>
    </span>
  );
}

export function PanelAlert({
  title,
  detail,
  tone = "warning",
}: {
  title: string;
  detail: string;
  tone?: "warning" | "negative" | "info";
}) {
  const color =
    tone === "negative"
      ? "border-negative/30 bg-negative/5 text-negative"
      : tone === "warning"
        ? "border-warning/30 bg-warning/5 text-warning"
        : "border-cyan/30 bg-cyan/5 text-cyan";
  return (
    <div role="status" className={cn("flex gap-2 rounded-control border p-3 text-xs transition-colors duration-160 hover:bg-surface-hover/40", color)}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p className="font-medium">{title}</p>
        <p className="mt-1 text-[12px] leading-4 text-secondary">{detail}</p>
      </div>
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex h-40 flex-col items-center justify-center px-6 text-center">
      <span className="mb-3 h-px w-10 bg-border-subtle" aria-hidden="true" />
      <p className="text-sm text-foreground">{title}</p>
      <p className="mt-1 max-w-md text-xs leading-5 text-secondary">{detail}</p>
    </div>
  );
}
