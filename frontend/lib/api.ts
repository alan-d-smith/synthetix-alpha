import { mockSnapshot } from "@/lib/mock-data";
import type { DashboardSnapshot } from "@/lib/types";

const apiBase = process.env.NEXT_PUBLIC_DASHBOARD_API_URL?.replace(/\/$/, "");
const OVERVIEW_TIMEOUT_MS = 120_000;
const PIPELINE_TIMEOUT_MS = 180_000;

export type DryPipelineResponse = {
  available: boolean;
  detail: string;
  status?: "complete" | "error" | "unavailable";
  asOf?: string;
  summary?: {
    screened: number;
    criticApproved: number;
    criticRejected: number;
    formedOrders: number;
    riskApproved: number;
    riskHalts: number;
    executions: number;
  };
  critic?: Array<{ ticker?: string | null; decision?: string | null; confidence?: number | null }>;
  riskHalts?: string[];
  executions?: unknown[];
  errors?: string[];
  raw?: unknown;
};

function overviewRequestSignal(caller?: AbortSignal): AbortSignal {
  const timeoutSignal = AbortSignal.timeout(OVERVIEW_TIMEOUT_MS);
  if (!caller) return timeoutSignal;
  if (caller.aborted) return caller;

  const ctrl = new AbortController();
  const abort = () => ctrl.abort();
  caller.addEventListener("abort", abort, { once: true });
  timeoutSignal.addEventListener("abort", abort, { once: true });
  return ctrl.signal;
}

export async function getDashboardSnapshot(signal?: AbortSignal): Promise<DashboardSnapshot> {
  if (!apiBase) return mockSnapshot;

  try {
    const response = await fetch(`${apiBase}/v1/overview`, {
      signal: overviewRequestSignal(signal),
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`Dashboard adapter unavailable (${response.status})`);
    }
    return (await response.json()) as DashboardSnapshot;
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new Error(`Dashboard adapter request timed out after ${OVERVIEW_TIMEOUT_MS / 1000} seconds.`);
    }
    throw err;
  }
}

export async function requestDryPipeline(): Promise<DryPipelineResponse> {
  if (!apiBase) {
    return {
      available: false,
      status: "unavailable",
      detail: "Dry pipeline is unavailable in demo mode. Connect NEXT_PUBLIC_DASHBOARD_API_URL to run against the adapter.",
    };
  }

  try {
    const response = await fetch(`${apiBase}/v1/pipeline/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ dryRun: true }),
      signal: AbortSignal.timeout(PIPELINE_TIMEOUT_MS),
      cache: "no-store",
    });

    let body: Record<string, unknown> | null = null;
    try {
      body = (await response.json()) as Record<string, unknown>;
    } catch {
      body = null;
    }

    if (!response.ok) {
      const detail =
        (typeof body?.detail === "string" && body.detail) ||
        `Dry pipeline request failed (${response.status}).`;
      return { available: false, status: "error", detail, raw: body ?? undefined };
    }

    const summary = body?.summary as DryPipelineResponse["summary"] | undefined;
    const detail =
      (typeof body?.detail === "string" && body.detail) ||
      "Dry pipeline completed. No live orders were submitted.";

    return {
      available: true,
      status: body?.status === "error" ? "error" : "complete",
      detail,
      asOf: typeof body?.asOf === "string" ? body.asOf : undefined,
      summary,
      critic: Array.isArray(body?.critic) ? (body.critic as DryPipelineResponse["critic"]) : undefined,
      riskHalts: Array.isArray(body?.riskHalts) ? (body.riskHalts as string[]) : undefined,
      executions: Array.isArray(body?.executions) ? body.executions : undefined,
      errors: Array.isArray(body?.errors) ? (body.errors as string[]) : undefined,
      raw: body ?? undefined,
    };
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      return {
        available: false,
        status: "error",
        detail: `Dry pipeline timed out after ${PIPELINE_TIMEOUT_MS / 1000} seconds.`,
      };
    }
    return {
      available: false,
      status: "error",
      detail: err instanceof Error ? err.message : "Dry pipeline request failed.",
    };
  }
}
