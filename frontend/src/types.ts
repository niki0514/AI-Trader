import type { ReactNode } from "react";

export type NumberLike = number | string | null | undefined;

export interface ServiceState {
  label: string;
  statusClass: string;
  hint: string;
}

export interface RunFormState {
  trade_date: string;
  run_id: string;
  input_file: string;
  config_file: string;
  output_root: string;
}

export interface PositionRow {
  symbol?: string;
  name?: string;
  sector?: string;
  board?: string;
  quantity?: NumberLike;
  available_quantity?: NumberLike;
  weight?: NumberLike;
  market_value?: NumberLike;
  avg_cost?: NumberLike;
  prev_close?: NumberLike;
  last_price?: NumberLike;
  upper_limit?: NumberLike;
  lower_limit?: NumberLike;
  unrealized_pnl_pct?: NumberLike;
  is_st?: boolean | string;
  suspended?: boolean | string;
  [key: string]: unknown;
}

export interface PlanRow {
  symbol?: string;
  name?: string;
  board?: string;
  action?: string;
  status?: string;
  target_weight?: NumberLike;
  w_final?: NumberLike;
  risk_mode?: string;
  entry_price_final?: NumberLike;
  stop_loss_price_final?: NumberLike;
  take_profit_price_final?: NumberLike;
  reduce_price_final?: NumberLike;
  exit_price_final?: NumberLike;
  reason?: string;
  [key: string]: unknown;
}

export interface FillRow {
  symbol?: string;
  name?: string;
  board?: string;
  action?: string;
  status?: string;
  planned_price?: NumberLike;
  quantity?: NumberLike;
  fill_price?: NumberLike;
  price_deviation_bps?: NumberLike;
  filled_amount?: NumberLike;
  total_fee?: NumberLike;
  note?: string;
  order_id?: string;
  [key: string]: unknown;
}

export interface NavRow {
  trade_date?: string;
  total_equity?: NumberLike;
  daily_return?: NumberLike;
  cum_return?: NumberLike;
  max_drawdown?: NumberLike;
  cash?: NumberLike;
  market_value?: NumberLike;
  [key: string]: unknown;
}

export interface Metrics {
  run_id?: string;
  trade_date?: string;
  risk_mode?: string;
  daily_return?: NumberLike;
  cum_return?: NumberLike;
  max_drawdown?: NumberLike;
  filled_order_count?: number | string;
  accepted_order_count?: number | string;
  risk_intercept_count?: number | string;
  [key: string]: unknown;
}

export interface PositionsPayload {
  trade_date?: string;
  run_id?: string;
  source?: string;
  output_dir?: string;
  count?: number;
  positions?: PositionRow[];
}

export interface PlansPayload {
  trade_date?: string;
  run_id?: string;
  source?: string;
  output_dir?: string;
  count?: number;
  plans?: PlanRow[];
}

export interface FillsPayload {
  trade_date?: string;
  run_id?: string;
  source?: string;
  output_dir?: string;
  count?: number;
  fills?: FillRow[];
}

export interface NavPayload {
  start?: string;
  end?: string;
  count?: number;
  nav?: NavRow[];
}

export interface ReportPayload {
  trade_date?: string;
  run_id?: string;
  source?: string;
  output_dir?: string;
  metrics?: Metrics | null;
  risk_report_markdown?: string;
}

export interface DashboardState {
  selectedDate: string;
  latestDate: string;
  latestPositions: PositionsPayload | null;
  navRows: NavRow[];
  plans: PlanRow[];
  fills: FillRow[];
  report: ReportPayload | null;
  lastSync: string;
}

export interface TableColumn<RowType> {
  label: string;
  className?: string;
  render: (row: RowType, index: number) => ReactNode;
}
