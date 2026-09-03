export type DataMode = "mock" | "paper" | "live" | "stale";
export type DecisionStatus = "APPROVED" | "REJECTED" | "PENDING";
export type RiskStatus = "APPROVED" | "HALTED" | "PENDING" | "UNAVAILABLE";
export type ExecutionStatus = "dry_run" | "skipped_no_legs" | "duplicate" | "submitted" | "error" | "unavailable";
export type FreshnessStatus = "fresh" | "refreshing" | "delayed" | "unavailable";
export type ResearchSource = "historical" | "in_sample" | "out_of_sample" | "mock" | "paper";
export type PipelineStage = "SCREEN" | "GATHER" | "CRITIQUE" | "FORM" | "RISK" | "EXECUTE";

export interface DataFreshness {
  source: string;
  asOf: string;
  status: FreshnessStatus;
  detail?: string;
}

export interface CriticDecision {
  ticker: string;
  decision: DecisionStatus;
  confidence: number;
  regimeSummary: string;
  thesis: string;
  riskFactors: string[];
  suggestedSizeMultiplier: number;
}

export interface OptionLeg {
  symbol: string;
  side: "long" | "short";
  ratio: number;
  type: "put" | "call" | "stock";
  strike?: number;
  delta?: number;
  dteOffset?: number;
  resolved: boolean;
}

export interface Order {
  symbol: string;
  legs: OptionLeg[];
  contracts: number;
  limitPrice: number | null;
  clientOrderId: string;
  maxLoss: number;
  definedRisk: boolean;
  confidence: number;
  thesis: string;
  resolution: "resolved" | "placeholder" | "unavailable";
}

export interface RiskDecision {
  status: RiskStatus;
  approvedSymbols: string[];
  halts: string[];
  asOf: string;
  enforcedRules: string[];
  configuredNotEnforced: string[];
}

export interface Candidate {
  ticker: string;
  company: string;
  sector: string;
  iv: number;
  hv: number;
  ivRv: number;
  ivRank: number;
  price: number | null;
  avgDollarVolume: number | null;
  critic: CriticDecision;
  risk: RiskStatus;
  headlines: string[];
  analystConsensus: number | null;
  insiderMspr: number | null;
  updatedAt: string;
  order?: Order;
}

export interface Execution {
  symbol: string;
  clientOrderId: string;
  status: ExecutionStatus;
  detail: string;
  createdAt: string;
  orderId?: string;
}

export interface Position {
  symbol: string;
  quantity: number;
  averageEntryPrice: number;
  unrealizedPnl: number;
  protected: boolean;
  underlying?: string;
}

export interface PortfolioSnapshot {
  nav: number;
  cash: number;
  aggregateUnrealizedPnl: number;
  positions: Position[];
  maxPositions: number;
  premiumAtRisk: number;
  premiumAtRiskCap: number;
  remainingLeverage: number;
  dailyDrawdown: number | null;
  totalDrawdown: number | null;
  hardHalt: string | null;
}

export interface AgentEvent {
  id: string;
  timestamp: string;
  stage: PipelineStage;
  ticker?: string;
  status: "complete" | "active" | "blocked" | "info";
  detail: string;
}

export interface PipelineStageSummary {
  stage: PipelineStage;
  label: string;
  result: string;
  status: "complete" | "active" | "blocked" | "pending";
}

export interface PipelineRun {
  id: string;
  asOf: string;
  mode: "paper";
  finalState: "complete" | "halted" | "partial";
  stages: PipelineStageSummary[];
  events: AgentEvent[];
  errors: string[];
}

export interface EquityPoint {
  date: string;
  equity: number;
  drawdown: number;
}

export interface TradePnLBucket {
  bucket: string;
  count: number;
}

export interface GenerationRecord {
  evaluatedAt: string;
  generation: number;
  strategy: string;
  underlyings: string;
  meanReturn: number;
  meanSharpe: number;
  maxDrawdown: number;
  trades: number;
  score: number;
  note: string;
  deployed?: boolean;
  correction?: boolean;
}

export interface SampleComparison {
  sample: "in_sample" | "out_of_sample";
  label: string;
  sharpe: number;
  maxDrawdown: number;
  trades: number;
  detail: string;
}

export interface StrategyPerformance {
  name: string;
  source: ResearchSource;
  period: string;
  sharpe: number;
  maxDrawdown: number;
  winRate: number;
  trades: number;
  profitFactor: number;
  oosSharpe: number | null;
  fragilityMedian: number | null;
  equity: EquityPoint[];
  annualReturns: Array<{ year: string; value: number }>;
  gateSweep: Array<{ gate: string; score: number; deployed: boolean }>;
  fragility: Array<{ parameter: string; score: number }>;
  comparisons: Array<{ name: string; sharpe: number; maxDrawdown: number; trades: number }>;
  tradePnL: TradePnLBucket[];
  generationHistory: GenerationRecord[];
  sampleComparisons: SampleComparison[];
}

export interface GovernanceControl {
  name: string;
  value: string;
  state: "enforced" | "configured_not_enforced";
  detail: string;
}

export interface SystemHealth {
  sources: DataFreshness[];
  api: DataFreshness;
  warnings: string[];
  governance: GovernanceControl[];
}

export interface VolatilityForecast {
  ticker: string;
  value: number;
  source: "unavailable";
}

export interface DashboardSnapshot {
  mode: DataMode;
  asOf: string;
  pipeline: PipelineRun;
  candidates: Candidate[];
  portfolio: PortfolioSnapshot;
  executions: Execution[];
  performance: StrategyPerformance;
  system: SystemHealth;
  warnings: string[];
}
