import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import type {
  DashboardState,
  FillRow,
  FillsPayload,
  Metrics,
  NavPayload,
  NavRow,
  NumberLike,
  PlanRow,
  PlansPayload,
  PositionRow,
  PositionsPayload,
  ReportPayload,
  RunFormState,
  ServiceState,
  TableColumn,
} from "./types";

type TabId = "overview" | "calendar" | "positions" | "plans" | "fills" | "report";

interface StageDefinition {
  key: string;
  order: string;
  label: string;
  description: string;
}

interface TabDefinition {
  id: TabId;
  label: string;
}

interface RefreshOptions {
  preferredDate?: string;
  baseOverride?: string;
  forceLatest?: boolean;
}

interface ToastState {
  message: string;
  isError: boolean;
}

interface CardSectionProps {
  eyebrow?: string;
  title: string;
  chip?: ReactNode;
  className?: string;
  children: ReactNode;
}

interface MetricCardProps {
  label: string;
  value: ReactNode;
  footnote?: string;
  className?: string;
}

interface SummaryGridItem {
  label: string;
  value: ReactNode;
  note?: string;
  toneClassName?: string;
}

interface SummaryBarProps {
  items: SummaryGridItem[];
  className?: string;
}

interface DecisionPoint {
  label: string;
  detail: string;
  toneClassName?: string;
}

interface StatusPillProps {
  label: string;
  statusClass: string;
}

interface SymbolCellProps {
  symbol?: string;
  name?: string;
}

interface BadgeProps {
  value?: string;
  tone: string;
}

interface DeltaTextProps {
  value: NumberLike;
  kind?: "percent" | "number";
}

interface NavChartProps {
  rows: NavRow[];
  fallbackDelta?: NumberLike;
}

interface PipelineTimelineProps {
  markdown: string;
}

interface AllocationListProps {
  rows: PositionRow[];
}

interface MarkdownRendererProps {
  markdown: string;
  emptyText: string;
}

interface CalendarPanelProps {
  month: string;
  selectedDate: string;
  rows: NavRow[];
  onSelectDate: (date: string) => void;
  onPrevMonth: () => void;
  onNextMonth: () => void;
  onCurrentMonth: () => void;
  disabled?: boolean;
}

interface QuickDateNavigatorProps {
  rows: NavRow[];
  selectedDate: string;
  prevDate: string;
  nextDate: string;
  disabled?: boolean;
  onSelectDate: (date: string) => void;
  onShiftDate: (offset: -1 | 1) => void;
}

interface CollapsibleSectionProps {
  eyebrow?: string;
  title: string;
  chip?: ReactNode;
  summaryText?: string;
  className?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

interface CalendarCell {
  date: string;
  day: number;
  inCurrentMonth: boolean;
  row: NavRow | null;
}

type MarkdownBlock =
  | { type: "h1" | "h2" | "h3" | "p"; text: string }
  | { type: "ul"; items: string[] };

const PIPELINE_STAGES: StageDefinition[] = [
  {
    key: "update_holding_actions",
    order: "01",
    label: "持仓复核",
    description: "对已有持仓生成 HOLD / REDUCE / EXIT 等动作建议。",
  },
  {
    key: "selector",
    order: "02",
    label: "候选筛选",
    description: "根据技术分与规则过滤观察池。",
  },
  {
    key: "analyst",
    order: "03",
    label: "AI 研判",
    description: "综合事件、基本面与技术信号产出 AI insight。",
  },
  {
    key: "decider",
    order: "04",
    label: "订单决策",
    description: "把候选和持仓动作合并为订单草案。",
  },
  {
    key: "risk_guard",
    order: "05",
    label: "风控拦截",
    description: "应用仓位上限、风险模式和拦截规则。",
  },
  {
    key: "executor",
    order: "06",
    label: "模拟执行",
    description: "生成成交、现金与仓位变化。",
  },
  {
    key: "reporter",
    order: "07",
    label: "报表输出",
    description: "沉淀 NAV、风险日报与摘要文件。",
  },
];

const TAB_ITEMS: TabDefinition[] = [
  { id: "overview", label: "决策总览" },
  { id: "calendar", label: "交易日复盘" },
  { id: "positions", label: "持仓" },
  { id: "plans", label: "计划" },
  { id: "fills", label: "成交" },
  { id: "report", label: "决策报告" },
];

const DEFAULT_SERVICE_STATE: ServiceState = {
  label: "检测中",
  statusClass: "status-pending",
  hint: "正在检查后端服务与最新产物。",
};

const DEFAULT_API_BASE = deriveDefaultApiBase();
const INITIAL_TRADE_DATE = todayIso();
const DEFAULT_RUN_FORM: RunFormState = {
  trade_date: INITIAL_TRADE_DATE,
  run_id: "",
  input_file: "backend/examples/input/daily_snapshot.json",
  config_file: "backend/app/config/pipeline.yaml",
  output_root: "backend/outputs",
};

const INITIAL_DASHBOARD_STATE: DashboardState = {
  selectedDate: "",
  latestDate: "",
  latestPositions: null,
  navRows: [],
  plans: [],
  fills: [],
  report: null,
  lastSync: "--",
};

const POSITION_COLUMNS: TableColumn<PositionRow>[] = [
  {
    label: "标的",
    render: (row) => <SymbolCell symbol={row.symbol} name={row.name} />,
  },
  {
    label: "板块",
    render: (row) => <Badge value={formatBoardLabel(row.board)} tone={boardTone(row.board)} />,
  },
  { label: "行业", render: (row) => row.sector || "--" },
  {
    label: "可用 / 持仓",
    className: "align-right mono",
    render: (row) => formatAvailablePosition(row.available_quantity, row.quantity),
  },
  {
    label: "成本价",
    className: "align-right mono",
    render: (row) => formatNumber(row.avg_cost, 2),
  },
  {
    label: "昨收",
    className: "align-right mono",
    render: (row) => formatNumber(row.prev_close, 2),
  },
  {
    label: "现价",
    className: "align-right mono",
    render: (row) => formatNumber(row.last_price, 2),
  },
  {
    label: "日涨跌",
    className: "align-right",
    render: (row) => <DeltaText value={intradayReturn(row.prev_close, row.last_price)} kind="percent" />,
  },
  {
    label: "市值",
    className: "align-right mono",
    render: (row) => formatCurrency(row.market_value),
  },
  {
    label: "仓位",
    className: "align-right",
    render: (row) => formatPercent(row.weight),
  },
  {
    label: "浮盈亏",
    className: "align-right",
    render: (row) => <DeltaText value={row.unrealized_pnl_pct} kind="percent" />,
  },
];

const PLAN_COLUMNS: TableColumn<PlanRow>[] = [
  { label: "标的", render: (row) => <SymbolCell symbol={row.symbol} name={row.name} /> },
  { label: "板块", render: (row) => <Badge value={formatBoardLabel(row.board)} tone={boardTone(row.board)} /> },
  { label: "动作", render: (row) => <Badge value={row.action} tone={actionTone(row.action)} /> },
  { label: "状态", render: (row) => <Badge value={row.status} tone={statusTone(row.status)} /> },
  {
    label: "目标仓位",
    className: "align-right",
    render: (row) => formatPercent(row.w_final ?? row.target_weight),
  },
  {
    label: "参考价",
    className: "align-right mono",
    render: (row) => formatNumber(planReferencePrice(row), 2),
  },
  {
    label: "止损价",
    className: "align-right mono",
    render: (row) => formatNumber(row.stop_loss_price_final, 2),
  },
  {
    label: "止盈价",
    className: "align-right mono",
    render: (row) => formatNumber(row.take_profit_price_final, 2),
  },
  { label: "理由", render: (row) => row.reason || "--" },
];

const FILL_COLUMNS: TableColumn<FillRow>[] = [
  { label: "标的", render: (row) => <SymbolCell symbol={row.symbol} name={row.name} /> },
  { label: "板块", render: (row) => <Badge value={formatBoardLabel(row.board)} tone={boardTone(row.board)} /> },
  { label: "动作", render: (row) => <Badge value={row.action} tone={actionTone(row.action)} /> },
  { label: "状态", render: (row) => <Badge value={row.status} tone={statusTone(row.status)} /> },
  {
    label: "计划价",
    className: "align-right mono",
    render: (row) => formatNumber(row.planned_price, 2),
  },
  {
    label: "数量",
    className: "align-right mono",
    render: (row) => formatNumber(row.quantity, 2),
  },
  {
    label: "成交价",
    className: "align-right mono",
    render: (row) => formatNumber(row.fill_price, 2),
  },
  {
    label: "偏离(bp)",
    className: "align-right mono",
    render: (row) => formatBasisPoints(row.price_deviation_bps),
  },
  {
    label: "成交额",
    className: "align-right mono",
    render: (row) => formatCurrency(row.filled_amount),
  },
  {
    label: "总费用",
    className: "align-right mono",
    render: (row) => formatCurrency(row.total_fee),
  },
  { label: "备注", render: (row) => row.note || "--" },
];

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [apiBaseInput, setApiBaseInput] = useState(DEFAULT_API_BASE);
  const [tradeDateInput, setTradeDateInput] = useState(INITIAL_TRADE_DATE);
  const [runForm, setRunForm] = useState<RunFormState>(DEFAULT_RUN_FORM);
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [calendarMonth, setCalendarMonth] = useState(() => toMonthValue(INITIAL_TRADE_DATE));
  const [serviceState, setServiceState] = useState<ServiceState>(DEFAULT_SERVICE_STATE);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [dataState, setDataState] = useState<DashboardState>(INITIAL_DASHBOARD_STATE);

  const positions = dataState.latestPositions?.positions || [];
  const reportMetrics = dataState.report?.metrics || null;
  const reportMarkdown = dataState.report?.risk_report_markdown || "";
  const sortedNavRows = useMemo(() => {
    return [...dataState.navRows].sort((left, right) => String(left.trade_date || "").localeCompare(String(right.trade_date || "")));
  }, [dataState.navRows]);
  const navByDate = useMemo(() => {
    return new Map(sortedNavRows.filter((row) => row.trade_date).map((row) => [String(row.trade_date), row]));
  }, [sortedNavRows]);

  const selectedNavRow = useMemo(() => {
    return navByDate.get(dataState.selectedDate) || null;
  }, [navByDate, dataState.selectedDate]);

  const selectedNavIndex = useMemo(() => {
    const index = sortedNavRows.findIndex((row) => row.trade_date === dataState.selectedDate);
    return index >= 0 ? index : sortedNavRows.length - 1;
  }, [sortedNavRows, dataState.selectedDate]);

  const previousNavRow = useMemo(() => {
    if (selectedNavIndex > 0) {
      return sortedNavRows[selectedNavIndex - 1];
    }
    return null;
  }, [sortedNavRows, selectedNavIndex]);

  const tradeDateSeries = useMemo(() => {
    return sortedNavRows.map((row) => row.trade_date).filter((value): value is string => Boolean(value));
  }, [sortedNavRows]);

  const selectedTradeDateIndex = useMemo(() => {
    return tradeDateSeries.findIndex((value) => value === dataState.selectedDate);
  }, [tradeDateSeries, dataState.selectedDate]);

  const prevTradeDate = selectedTradeDateIndex > 0 ? tradeDateSeries[selectedTradeDateIndex - 1] : "";
  const nextTradeDate =
    selectedTradeDateIndex >= 0 && selectedTradeDateIndex < tradeDateSeries.length - 1 ? tradeDateSeries[selectedTradeDateIndex + 1] : "";

  const acceptedPlans = useMemo(() => {
    return dataState.plans.filter((row) => row.status === "ACCEPTED").length;
  }, [dataState.plans]);

  const completedFills = useMemo(() => {
    return dataState.fills.filter((row) => ["FILLED", "COMPLETED"].includes(row.status || "")).length;
  }, [dataState.fills]);

  const metricView = {
    tradeDate: dataState.selectedDate || "--",
    equity: selectedNavRow ? formatCurrency(selectedNavRow.total_equity) : "--",
    dailyReturn: reportMetrics?.daily_return ?? selectedNavRow?.daily_return,
    cumReturn: reportMetrics?.cum_return ?? selectedNavRow?.cum_return,
    maxDrawdown: reportMetrics?.max_drawdown ?? selectedNavRow?.max_drawdown,
    riskMode: reportMetrics?.risk_mode || "--",
    filledOrderCount: reportMetrics?.filled_order_count ?? completedFills,
    acceptedOrderCount: reportMetrics?.accepted_order_count ?? acceptedPlans,
  };

  const marketSnapshot = useMemo(() => {
    const activeRow = selectedNavRow;
    const equityDelta = previousNavRow ? toNumber(activeRow?.total_equity) - toNumber(previousNavRow.total_equity) : Number.NaN;
    const basis = Number.isFinite(equityDelta) ? equityDelta : toNumber(metricView.dailyReturn);
    const trend = marketTrendMeta(basis);

    return {
      ...trend,
    };
  }, [dataState.selectedDate, metricView.dailyReturn, previousNavRow, selectedNavRow]);

  const totalPositionWeight = useMemo(() => {
    return positions.reduce((sum, row) => {
      const weight = toNumber(row.weight);
      return Number.isFinite(weight) ? sum + weight : sum;
    }, 0);
  }, [positions]);

  const topPosition = useMemo(() => {
    return [...positions].sort((left, right) => toNumber(right.weight) - toNumber(left.weight))[0] || null;
  }, [positions]);

  const fillBreakdown = useMemo(() => {
    const rejectedCount = dataState.fills.filter((row) => ["REJECTED", "FAILED"].includes(row.status || "")).length;
    const totalAmount = dataState.fills.reduce((sum, row) => {
      const amount = toNumber(row.filled_amount);
      return Number.isFinite(amount) ? sum + amount : sum;
    }, 0);
    return { rejectedCount, totalAmount };
  }, [dataState.fills]);

  const recentNavRows = useMemo(() => {
    return [...sortedNavRows].slice(-10).reverse();
  }, [sortedNavRows]);

  const stageCoverage = useMemo(() => {
    return extractStageNotes(reportMarkdown).size;
  }, [reportMarkdown]);

  const reportExcerpt = useMemo(() => {
    return extractMarkdownExcerpt(reportMarkdown);
  }, [reportMarkdown]);

  const calendarMonthRows = useMemo(() => {
    return sortedNavRows.filter((row) => String(row.trade_date || "").startsWith(`${calendarMonth}-`));
  }, [calendarMonth, sortedNavRows]);

  const calendarMonthSummary = useMemo(() => {
    return calendarMonthRows.reduce<{ upDays: number; downDays: number; flatDays: number }>(
      (summary, row) => {
        const dailyReturn = toNumber(row.daily_return);
        if (Number.isFinite(dailyReturn)) {
          if (dailyReturn > 0) {
            summary.upDays += 1;
          } else if (dailyReturn < 0) {
            summary.downDays += 1;
          } else {
            summary.flatDays += 1;
          }
        }
        return summary;
      },
      { upDays: 0, downDays: 0, flatDays: 0 },
    );
  }, [calendarMonthRows]);

  const riskInterceptCount = toNumber(reportMetrics?.risk_intercept_count);
  const acceptedOrderCountValue = toNumber(metricView.acceptedOrderCount);
  const filledOrderCountValue = toNumber(metricView.filledOrderCount);
  const executionGap =
    Number.isFinite(acceptedOrderCountValue) && Number.isFinite(filledOrderCountValue)
      ? Math.max(0, acceptedOrderCountValue - filledOrderCountValue)
      : Number.NaN;
  const selectedEquityDelta = previousNavRow
    ? toNumber(selectedNavRow?.total_equity) - toNumber(previousNavRow.total_equity)
    : Number.NaN;

  const overviewSummaryItems: SummaryGridItem[] = [
    {
      label: "持仓 / 仓位",
      value: `${positions.length} / ${formatPercent(totalPositionWeight)}`,
    },
    {
      label: "最大权重",
      value: topPosition ? `${topPosition.symbol || "--"} ${formatPercent(topPosition.weight)}` : "--",
      toneClassName: topPosition && toNumber(topPosition.weight) > 0 ? "summary-up" : undefined,
    },
    {
      label: "风险模式",
      value: metricView.riskMode,
    },
    {
      label: "最大回撤",
      value: formatPercent(metricView.maxDrawdown),
    },
    {
      label: "拦截 / 失败",
      value: `${displayValue(reportMetrics?.risk_intercept_count)} / ${fillBreakdown.rejectedCount}`,
      toneClassName: fillBreakdown.rejectedCount > 0 ? "summary-down" : undefined,
    },
    {
      label: "成交总额",
      value: formatCurrency(fillBreakdown.totalAmount),
    },
  ];

  const calendarRecapItems: SummaryGridItem[] = [
    {
      label: "当日收益",
      value: <DeltaText value={metricView.dailyReturn} kind="percent" />,
      toneClassName: metricToneClass(metricView.dailyReturn),
    },
    {
      label: "净值变化(较前日)",
      value: formatSignedCurrency(selectedEquityDelta),
      toneClassName: metricToneClass(selectedEquityDelta),
    },
    {
      label: "成交 / 通过",
      value: `${metricView.filledOrderCount ?? "--"} / ${metricView.acceptedOrderCount ?? "--"}`,
    },
    {
      label: "风险模式",
      value: metricView.riskMode,
    },
    {
      label: "月内涨跌平",
      value: `${calendarMonthSummary.upDays}/${calendarMonthSummary.downDays}/${calendarMonthSummary.flatDays}`,
    },
  ];

  const reportBriefItems: SummaryGridItem[] = [
    {
      label: "交易日",
      value: metricView.tradeDate,
    },
    {
      label: "风险模式",
      value: reportMetrics?.risk_mode || "--",
    },
    {
      label: "成交 / 通过",
      value: `${metricView.filledOrderCount ?? "--"} / ${metricView.acceptedOrderCount ?? "--"}`,
    },
    {
      label: "风险拦截",
      value: displayValue(reportMetrics?.risk_intercept_count),
    },
    {
      label: "阶段注记",
      value: `${stageCoverage}/7`,
    },
  ];

  const overviewConclusion = useMemo(() => {
    const headline =
      marketSnapshot.className === "trend-up"
        ? "结论：组合偏强运行，可以执行通过计划，但仍需约束节奏。"
        : marketSnapshot.className === "trend-down"
          ? "结论：组合进入回撤区间，先验证防守动作是否到位。"
          : "结论：组合震荡，优先评估执行质量而不是扩张仓位。";

    let nextFocus = "优先核对计划→成交链路是否顺畅，并在下一交易日复用有效动作。";
    if (marketSnapshot.className === "trend-down") {
      nextFocus = `优先检查减仓/止损动作与风险拦截（${displayValue(reportMetrics?.risk_intercept_count)} 次），确认回撤是否受控。`;
    } else if (Number.isFinite(executionGap) && executionGap > 0) {
      nextFocus = `当前仍有 ${formatNumber(executionGap, 0)} 条通过计划未完成成交，先确认执行阻塞点。`;
    } else if (Number.isFinite(riskInterceptCount) && riskInterceptCount > 0) {
      nextFocus = `风控本日触发 ${formatNumber(riskInterceptCount, 0)} 次，建议复核拦截原因并筛选可恢复动作。`;
    } else if (stageCoverage < 7) {
      nextFocus = `日报注记覆盖 ${stageCoverage}/7 个阶段，需补齐缺失阶段再做次日动作复用。`;
    }

    const points: DecisionPoint[] = [
      {
        label: "发生了什么",
        detail: `${metricView.tradeDate} 净值 ${metricView.equity}，日收益 ${formatPercent(metricView.dailyReturn)}，市场信号 ${marketSnapshot.symbol} ${marketSnapshot.label}。`,
      },
      {
        label: "为什么重要",
        detail: `计划通过 ${acceptedPlans}/${dataState.plans.length}，成交 ${completedFills}/${dataState.fills.length}，风险模式 ${metricView.riskMode}，最大回撤 ${formatPercent(metricView.maxDrawdown)}。`,
      },
      {
        label: "下一步关注",
        detail: nextFocus,
        toneClassName: toneClassFromTrend(marketSnapshot.className),
      },
    ];

    return {
      headline,
      points,
    };
  }, [
    acceptedPlans,
    completedFills,
    dataState.fills.length,
    dataState.plans.length,
    executionGap,
    marketSnapshot.className,
    marketSnapshot.label,
    marketSnapshot.symbol,
    metricView.dailyReturn,
    metricView.equity,
    metricView.maxDrawdown,
    metricView.riskMode,
    metricView.tradeDate,
    reportMetrics?.risk_intercept_count,
    riskInterceptCount,
    stageCoverage,
  ]);

  const calendarReplayConclusion = useMemo(() => {
    const headline =
      marketSnapshot.className === "trend-up"
        ? "复盘结论：当日收益为正，重点确认上涨来自可重复动作。"
        : marketSnapshot.className === "trend-down"
          ? "复盘结论：当日出现回撤，先验证风险动作是否充分。"
          : "复盘结论：当日震荡，重点看执行与风控是否一致。";

    const contextText =
      reportExcerpt === "暂无报告摘要。"
        ? "当日报告暂无额外文字摘要。"
        : `报告线索：${reportExcerpt}`;

    let nextFocus = "下一步聚焦：把当日有效动作沉淀为次日执行优先级。";
    if (marketSnapshot.className === "trend-down") {
      nextFocus = "下一步聚焦：逐条核对减仓/止损与拦截记录，避免回撤延续。";
    } else if (Number.isFinite(executionGap) && executionGap > 0) {
      nextFocus = `下一步聚焦：仍有 ${formatNumber(executionGap, 0)} 条通过计划未成交，先处理执行缺口。`;
    } else if (stageCoverage < 7) {
      nextFocus = `下一步聚焦：阶段注记仅覆盖 ${stageCoverage}/7，补齐上下文后再定次日重点。`;
    }

    const points: DecisionPoint[] = [
      {
        label: "当日结果",
        detail: `${metricView.tradeDate} 净值 ${metricView.equity}，日收益 ${formatPercent(metricView.dailyReturn)}，较前一交易日净值变化 ${formatSignedCurrency(selectedEquityDelta)}。`,
      },
      {
        label: "所处背景",
        detail: `当月涨/跌/平为 ${calendarMonthSummary.upDays}/${calendarMonthSummary.downDays}/${calendarMonthSummary.flatDays}；${contextText}`,
      },
      {
        label: "下一关注点",
        detail: nextFocus,
        toneClassName: toneClassFromTrend(marketSnapshot.className),
      },
    ];

    return {
      headline,
      points,
    };
  }, [
    calendarMonthSummary.downDays,
    calendarMonthSummary.flatDays,
    calendarMonthSummary.upDays,
    executionGap,
    marketSnapshot.className,
    metricView.dailyReturn,
    metricView.equity,
    metricView.tradeDate,
    reportExcerpt,
    selectedEquityDelta,
    stageCoverage,
  ]);

  const reportDecisionBrief = useMemo(() => {
    const headline =
      marketSnapshot.className === "trend-up"
        ? "日报判断：当前偏进攻，但应以风控约束下的可执行动作为主。"
        : marketSnapshot.className === "trend-down"
          ? "日报判断：当前偏防守，优先保证风险收敛而非扩大仓位。"
          : "日报判断：当前偏中性，重点在执行效率和规则一致性。";

    const evidenceText =
      reportExcerpt === "暂无报告摘要。" ? "报告暂无额外摘要。" : `报告线索：${reportExcerpt}`;

    let actionText = "建议动作：保留通过计划中的高确定性条目，并继续跟踪执行偏差。";
    if (marketSnapshot.className === "trend-down") {
      actionText = "建议动作：按拦截与失败记录回放，先修复风险暴露再考虑新增动作。";
    } else if (Number.isFinite(executionGap) && executionGap > 0) {
      actionText = `建议动作：优先解决 ${formatNumber(executionGap, 0)} 条未完成成交的执行问题。`;
    } else if (Number.isFinite(riskInterceptCount) && riskInterceptCount > 0) {
      actionText = `建议动作：复核 ${formatNumber(riskInterceptCount, 0)} 次风控拦截原因，识别可恢复订单。`;
    }

    const points: DecisionPoint[] = [
      {
        label: "结果判断",
        detail: `${metricView.tradeDate} 日收益 ${formatPercent(metricView.dailyReturn)}，累计收益 ${formatPercent(metricView.cumReturn)}，最大回撤 ${formatPercent(metricView.maxDrawdown)}。`,
      },
      {
        label: "执行与风控",
        detail: `成交/通过 ${metricView.filledOrderCount ?? "--"}/${metricView.acceptedOrderCount ?? "--"}，风险拦截 ${displayValue(reportMetrics?.risk_intercept_count)}，阶段注记覆盖 ${stageCoverage}/7。${evidenceText}`,
      },
      {
        label: "后续动作",
        detail: actionText,
        toneClassName: toneClassFromTrend(marketSnapshot.className),
      },
    ];

    return {
      headline,
      points,
    };
  }, [
    executionGap,
    marketSnapshot.className,
    metricView.acceptedOrderCount,
    metricView.cumReturn,
    metricView.dailyReturn,
    metricView.filledOrderCount,
    metricView.maxDrawdown,
    metricView.tradeDate,
    reportExcerpt,
    reportMetrics?.risk_intercept_count,
    riskInterceptCount,
    stageCoverage,
  ]);

  const tabCounts: Record<TabId, string> = {
    overview: `${sortedNavRows.length} 日`,
    calendar: `${calendarMonthRows.length} 日`,
    positions: `${positions.length} 条`,
    plans: `${dataState.plans.length} 条`,
    fills: `${dataState.fills.length} 条`,
    report: reportMetrics ? "已生成" : "暂无",
  };

  useEffect(() => {
    void refreshDashboard();
  }, []);

  useEffect(() => {
    if (dataState.selectedDate) {
      setCalendarMonth(toMonthValue(dataState.selectedDate));
    }
  }, [dataState.selectedDate]);

  useEffect(() => {
    if (!toast) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setToast(null);
    }, 2800);
    return () => {
      window.clearTimeout(timer);
    };
  }, [toast]);

  async function refreshDashboard({
    preferredDate = "",
    baseOverride = apiBase,
    forceLatest = false,
  }: RefreshOptions = {}): Promise<void> {
    const targetBase = normalizeBaseUrl(baseOverride);
    setIsRefreshing(true);
    setServiceState(DEFAULT_SERVICE_STATE);

    try {
      let nextServiceState = DEFAULT_SERVICE_STATE;
      try {
        await fetchJson<{ status: string }>(targetBase, "/healthz");
        nextServiceState = {
          label: "在线",
          statusClass: "status-ok",
          hint: `已连接 ${targetBase}`,
        };
      } catch (error) {
        nextServiceState = {
          label: "不可用",
          statusClass: "status-error",
          hint: getErrorMessage(error),
        };
      }

      const [positionsPayload, navPayload] = await Promise.all([
        safeFetch<PositionsPayload>(targetBase, "/positions/latest"),
        safeFetch<NavPayload>(targetBase, "/nav"),
      ]);

      const nextLatestDate = positionsPayload?.trade_date || "";
      const fallbackDate = forceLatest
        ? nextLatestDate || preferredDate || tradeDateInput || INITIAL_TRADE_DATE
        : preferredDate || dataState.selectedDate || nextLatestDate || tradeDateInput || INITIAL_TRADE_DATE;

      let nextPlans: PlanRow[] = [];
      let nextFills: FillRow[] = [];
      let nextReport: ReportPayload | null = null;

      if (fallbackDate) {
        const [plansPayload, fillsPayload, reportPayload] = await Promise.all([
          safeFetch<PlansPayload>(targetBase, `/plans/${fallbackDate}`),
          safeFetch<FillsPayload>(targetBase, `/fills/${fallbackDate}`),
          safeFetch<ReportPayload>(targetBase, `/reports/daily/${fallbackDate}`),
        ]);
        nextPlans = plansPayload?.plans || [];
        nextFills = fillsPayload?.fills || [];
        nextReport = reportPayload;
      }

      setServiceState(nextServiceState);
      setDataState({
        selectedDate: fallbackDate,
        latestDate: nextLatestDate,
        latestPositions: positionsPayload,
        navRows: navPayload?.nav || [],
        plans: nextPlans,
        fills: nextFills,
        report: nextReport,
        lastSync: new Date().toLocaleString("zh-CN", { hour12: false }),
      });
      setTradeDateInput(fallbackDate || INITIAL_TRADE_DATE);
      setRunForm((current) => ({
        ...current,
        trade_date: fallbackDate || current.trade_date,
      }));
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleApplyApiBase(): Promise<void> {
    const normalized = normalizeBaseUrl(apiBaseInput);
    setApiBase(normalized);
    setApiBaseInput(normalized);
    showToast(`已切换 API 地址：${normalized}`);
    await refreshDashboard({
      preferredDate: dataState.selectedDate,
      baseOverride: normalized,
    });
  }

  async function handleLoadDate(): Promise<void> {
    if (!tradeDateInput) {
      showToast("请先选择交易日。", true);
      return;
    }
    await refreshDashboard({
      preferredDate: tradeDateInput,
      baseOverride: apiBase,
    });
  }

  async function handleSelectTradeDate(date: string): Promise<void> {
    if (!date || date === dataState.selectedDate) {
      setTradeDateInput(date || tradeDateInput);
      return;
    }
    setTradeDateInput(date);
    setCalendarMonth(toMonthValue(date));
    await refreshDashboard({
      preferredDate: date,
      baseOverride: apiBase,
    });
  }

  async function handleShiftTradeDate(offset: -1 | 1): Promise<void> {
    const targetDate = offset < 0 ? prevTradeDate : nextTradeDate;
    if (!targetDate) {
      return;
    }
    await handleSelectTradeDate(targetDate);
  }

  async function handleRunDaily(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const body = Object.entries(runForm).reduce<Record<string, string>>((result, [key, value]) => {
      const cleaned = String(value || "").trim();
      if (cleaned) {
        result[key] = cleaned;
      }
      return result;
    }, {});

    setIsRunning(true);
    try {
      const payload = await fetchJson<{ trade_date?: string; run_id?: string }>(apiBase, "/jobs/run-daily", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const nextTradeDate = payload.trade_date || body.trade_date || dataState.latestDate || tradeDateInput;
      showToast(`单日任务已完成：${payload.run_id || "unknown-run"}`);
      setTradeDateInput(nextTradeDate || INITIAL_TRADE_DATE);
      setRunForm((current) => ({
        ...current,
        trade_date: nextTradeDate || current.trade_date,
      }));
      setActiveTab("overview");
      await refreshDashboard({
        preferredDate: nextTradeDate,
        baseOverride: apiBase,
        forceLatest: true,
      });
    } catch (error) {
      showToast(getErrorMessage(error), true);
    } finally {
      setIsRunning(false);
    }
  }

  function showToast(message: string, isError = false): void {
    setToast({ message, isError });
  }

  return (
    <div className="app-root">
      <div className="app-shell">
        <aside className="sidebar">
          <section className="brand-card card">
            <div className="brand-mark">AT</div>
            <div>
              <p className="eyebrow">AI Trader Decision</p>
              <h1>策略决策工作台</h1>
            </div>
          </section>

          <CardSection
            eyebrow="连接"
            title="数据连接状态"
            chip={<StatusPill label={serviceState.label} statusClass={serviceState.statusClass} />}
          >
            <label className="field">
              <span>API Base URL</span>
              <input
                type="text"
                value={apiBaseInput}
                onChange={(event) => setApiBaseInput(event.target.value)}
              />
            </label>
            <div className="button-row">
              <button
                type="button"
                className="button button-secondary"
                disabled={isRefreshing}
                onClick={() => void handleApplyApiBase()}
              >
                应用地址
              </button>
              <button
                type="button"
                className="button"
                disabled={isRefreshing}
                onClick={() => void refreshDashboard({ preferredDate: dataState.selectedDate })}
              >
                {isRefreshing ? "刷新中…" : "刷新数据"}
              </button>
            </div>
            <p className="helper-text">{serviceState.hint}</p>
          </CardSection>

          <CollapsibleSection
            eyebrow="任务"
            title="运行单日回放"
            summaryText="技术参数（默认收起）"
            defaultOpen={false}
          >
            <form className="stack-form" onSubmit={(event) => void handleRunDaily(event)}>
              <label className="field">
                <span>交易日</span>
                <input
                  type="date"
                  value={runForm.trade_date}
                  onChange={(event) => setRunForm((current) => ({ ...current, trade_date: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>运行 ID</span>
                <input
                  type="text"
                  placeholder="可留空自动生成"
                  value={runForm.run_id}
                  onChange={(event) => setRunForm((current) => ({ ...current, run_id: event.target.value }))}
                />
              </label>
              <details className="advanced-card">
                <summary>高级参数</summary>
                <div className="advanced-fields">
                  <label className="field">
                    <span>输入快照</span>
                    <input
                      type="text"
                      value={runForm.input_file}
                      onChange={(event) => setRunForm((current) => ({ ...current, input_file: event.target.value }))}
                    />
                  </label>
                  <label className="field">
                    <span>配置文件</span>
                    <input
                      type="text"
                      value={runForm.config_file}
                      onChange={(event) => setRunForm((current) => ({ ...current, config_file: event.target.value }))}
                    />
                  </label>
                  <label className="field">
                    <span>输出目录</span>
                    <input
                      type="text"
                      value={runForm.output_root}
                      onChange={(event) => setRunForm((current) => ({ ...current, output_root: event.target.value }))}
                    />
                  </label>
                </div>
              </details>
              <button className="button button-wide" type="submit" disabled={isRunning}>
                {isRunning ? "运行中…" : "运行单日回放"}
              </button>
            </form>
          </CollapsibleSection>

          <CollapsibleSection
            eyebrow="时间轴"
            title="选择观察交易日"
            summaryText={`当前 ${dataState.selectedDate || "--"}`}
            defaultOpen={false}
          >
            <label className="field">
              <span>查看日期</span>
              <input
                type="date"
                value={tradeDateInput}
                onChange={(event) => setTradeDateInput(event.target.value)}
              />
            </label>
            <div className="button-row">
              <button
                type="button"
                className="button button-secondary"
                disabled={isRefreshing}
                onClick={() => void handleLoadDate()}
              >
                加载日期
              </button>
              <button
                type="button"
                className="button button-ghost"
                disabled={isRefreshing}
                onClick={() => void refreshDashboard({ baseOverride: apiBase, forceLatest: true })}
              >
                回到最新
              </button>
            </div>
          </CollapsibleSection>
        </aside>

        <main className="workspace">
          <div className="workspace-header">
            <section className="hero card toolbar-card">
              <div>
                <p className="eyebrow">Decision Workbench</p>
                <h2>先判断、再执行、再复盘</h2>
              </div>
              <div className="hero-meta">
                <button
                  type="button"
                  className="button button-ghost button-small"
                  disabled={!prevTradeDate || isRefreshing}
                  onClick={() => void handleShiftTradeDate(-1)}
                >
                  上一交易日
                </button>
                <button
                  type="button"
                  className="button button-ghost button-small"
                  disabled={!nextTradeDate || isRefreshing}
                  onClick={() => void handleShiftTradeDate(1)}
                >
                  下一交易日
                </button>
                <span className={cx("trend-chip", marketSnapshot.className)}>
                  {marketSnapshot.symbol} {marketSnapshot.label}
                </span>
                <span className="subtle-chip">
                  同步于 <strong>{dataState.lastSync}</strong>
                </span>
              </div>
            </section>

            <section className="metrics-grid">
              <MetricCard label="交易日" value={metricView.tradeDate} />
              <MetricCard label="组合净值" value={metricView.equity} />
              <MetricCard
                label="日收益"
                value={<DeltaText value={metricView.dailyReturn} kind="percent" />}
                className={metricToneClass(metricView.dailyReturn)}
              />
              <MetricCard
                label="累计收益"
                value={<DeltaText value={metricView.cumReturn} kind="percent" />}
                className={metricToneClass(metricView.cumReturn)}
              />
              <MetricCard label="最大回撤" value={formatPercent(metricView.maxDrawdown)} />
              <MetricCard label="风险模式" value={metricView.riskMode} />
            </section>

            <section className="card tabs-shell" role="tablist" aria-label="工作台标签页">
              {TAB_ITEMS.map((tab) => (
                <button
                  key={tab.id}
                  id={`tab-${tab.id}`}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  aria-controls={`panel-${tab.id}`}
                  className={cx("tab-button", activeTab === tab.id && "is-active")}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <span className="tab-label">{tab.label}</span>
                  <span className="tab-count">{tabCounts[tab.id]}</span>
                </button>
              ))}
            </section>
          </div>

            <section
              id={`panel-${activeTab}`}
              className={cx("workspace-section", activeTab === "overview" ? "workspace-section-overview" : "workspace-section-detail")}
              role="tabpanel"
              aria-labelledby={`tab-${activeTab}`}
            >
            {activeTab === "overview" ? (
              <div className="overview-layout">
                <div className="overview-main">
                  <CardSection
                    eyebrow="今日决策结论"
                    title="先做判断，再看明细"
                    chip={<span className={cx("trend-chip", marketSnapshot.className)}>{marketSnapshot.symbol} {marketSnapshot.label}</span>}
                    className="conclusion-card"
                  >
                    <p className="conclusion-headline">{overviewConclusion.headline}</p>
                    <DecisionPointList items={overviewConclusion.points} className="decision-list-compact" />
                  </CardSection>

                  <div className="overview-top-grid">
                    <CardSection
                      eyebrow="趋势"
                      title="NAV 走势"
                      chip={<span className="subtle-chip">{sortedNavRows.length} 个样本</span>}
                      className="chart-card"
                    >
                      <NavChart rows={sortedNavRows} fallbackDelta={metricView.dailyReturn} />
                    </CardSection>

                    <CardSection
                      eyebrow="时间"
                      title="轻量交易日导航"
                      chip={<span className="subtle-chip">{metricView.tradeDate}</span>}
                      className="calendar-card"
                    >
                      <QuickDateNavigator
                        rows={recentNavRows}
                        selectedDate={dataState.selectedDate}
                        prevDate={prevTradeDate}
                        nextDate={nextTradeDate}
                        onSelectDate={(date) => void handleSelectTradeDate(date)}
                        onShiftDate={(offset) => void handleShiftTradeDate(offset)}
                        disabled={isRefreshing}
                      />
                    </CardSection>
                  </div>
                </div>

                <div className="overview-side">
                  <CardSection eyebrow="决策上下文" title="组合 / 风险 / 执行补充" className="overview-summary-card">
                    <SummaryBar items={overviewSummaryItems} className="summary-bar-tight" />
                    <div className="report-preview compact evidence-preview">
                      <p className="report-preview-label">报告线索</p>
                      <p className="report-preview-text">{reportExcerpt}</p>
                    </div>
                  </CardSection>
                </div>
              </div>
            ) : null}

            {activeTab === "calendar" ? (
              <div className="calendar-layout">
                <CardSection
                  eyebrow="交易日历"
                  title="按日回放"
                  chip={<span className="subtle-chip">{formatMonthLabel(calendarMonth)}</span>}
                  className="calendar-shell"
                >
                  <CalendarPanel
                    month={calendarMonth}
                    selectedDate={dataState.selectedDate}
                    rows={sortedNavRows}
                    onSelectDate={(date) => void handleSelectTradeDate(date)}
                    onPrevMonth={() => setCalendarMonth((current) => shiftMonthValue(current, -1))}
                    onNextMonth={() => setCalendarMonth((current) => shiftMonthValue(current, 1))}
                    onCurrentMonth={() => setCalendarMonth(toMonthValue(dataState.selectedDate || INITIAL_TRADE_DATE))}
                    disabled={isRefreshing}
                  />
                </CardSection>

                <div className="calendar-side">
                  <CardSection
                    eyebrow="单日复盘结论"
                    title={dataState.selectedDate || "未选择日期"}
                    chip={<span className={cx("trend-chip", marketSnapshot.className)}>{marketSnapshot.symbol} {marketSnapshot.label}</span>}
                  >
                    <p className="conclusion-headline">{calendarReplayConclusion.headline}</p>
                    <SummaryBar items={calendarRecapItems} className="summary-bar-tight" />
                    <DecisionPointList items={calendarReplayConclusion.points} />
                    <div className="button-row">
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={!prevTradeDate || isRefreshing}
                        onClick={() => void handleShiftTradeDate(-1)}
                      >
                        上一交易日
                      </button>
                      <button
                        type="button"
                        className="button button-ghost"
                        disabled={!nextTradeDate || isRefreshing}
                        onClick={() => void handleShiftTradeDate(1)}
                      >
                        下一交易日
                      </button>
                    </div>
                  </CardSection>

                  <CardSection
                    eyebrow="复盘证据链"
                    title="七段流水线注记"
                    chip={<span className="subtle-chip">{stageCoverage}/7</span>}
                  >
                    <PipelineTimeline markdown={reportMarkdown} />
                  </CardSection>
                </div>
              </div>
            ) : null}

            {activeTab === "positions" ? (
              <div className="detail-stack">
                <div className="detail-layout detail-layout-split">
                  <CardSection eyebrow="仓位" title="权重分布" className="detail-side-card scroll-card">
                    <AllocationList rows={positions} />
                  </CardSection>

                  <CardSection
                    eyebrow="持仓"
                    title="最新组合视图"
                    chip={<span className="subtle-chip">{positions.length} 条</span>}
                    className="scroll-card"
                  >
                    <DataTable
                      rows={positions}
                      columns={POSITION_COLUMNS}
                      emptyText="暂无持仓数据"
                      rowClassName={(row) => positionRowClassName(row)}
                    />
                  </CardSection>
                </div>
              </div>
            ) : null}

            {activeTab === "plans" ? (
              <div className="detail-stack">
                <CardSection eyebrow="计划" title="交易计划" className="scroll-card">
                  <DataTable
                    rows={dataState.plans}
                    columns={PLAN_COLUMNS}
                    emptyText="该日期暂无交易计划"
                    rowClassName={(row) => actionRowClassName(row.action)}
                  />
                </CardSection>
              </div>
            ) : null}

            {activeTab === "fills" ? (
              <div className="detail-stack">
                <CardSection eyebrow="执行" title="模拟成交" className="scroll-card">
                  <DataTable
                    rows={dataState.fills}
                    columns={FILL_COLUMNS}
                    emptyText="该日期暂无成交记录"
                    rowClassName={(row) => actionRowClassName(row.action)}
                  />
                </CardSection>
              </div>
            ) : null}

            {activeTab === "report" ? (
              <div className="detail-stack">
                <CardSection
                  eyebrow="决策简报"
                  title="先看判断，再读全文"
                  chip={<span className="subtle-chip">{dataState.selectedDate || "--"}</span>}
                >
                  <p className="conclusion-headline">{reportDecisionBrief.headline}</p>
                  <SummaryBar items={reportBriefItems} className="summary-bar-tight" />
                  <DecisionPointList items={reportDecisionBrief.points} />
                </CardSection>

                <CardSection
                  eyebrow="报告全文"
                  title="风险日报 Markdown（原文）"
                  className="scroll-card"
                >
                  <MarkdownRenderer markdown={reportMarkdown} emptyText="该日期暂无风险报告" />
                </CardSection>
              </div>
            ) : null}
          </section>
        </main>
      </div>

      {toast ? (
        <div
          className="toast"
          style={{
            borderColor: toast.isError ? "rgba(255, 107, 125, 0.3)" : "rgba(99, 179, 255, 0.3)",
          }}
        >
          {toast.message}
        </div>
      ) : null}
    </div>
  );
}

function CardSection({ eyebrow, title, chip = null, className = "", children }: CardSectionProps) {
  return (
    <section className={cx("card", "panel-card", className)}>
      <div className="section-heading">
        <div>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h2>{title}</h2>
        </div>
        {chip}
      </div>
      {children}
    </section>
  );
}

function CollapsibleSection({
  eyebrow,
  title,
  chip = null,
  summaryText,
  className = "",
  defaultOpen = false,
  children,
}: CollapsibleSectionProps) {
  return (
    <details className={cx("card", "panel-card", "collapsible-card", className)} open={defaultOpen}>
      <summary>
        <div>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h2>{title}</h2>
        </div>
        <div className="collapsible-meta">
          {summaryText ? <span className="subtle-chip">{summaryText}</span> : null}
          {chip}
        </div>
      </summary>
      <div className="collapsible-content">{children}</div>
    </details>
  );
}

function MetricCard({ label, value, footnote, className = "" }: MetricCardProps) {
  return (
    <article className={cx("metric-card", "card", className)}>
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
      {footnote ? <p className="metric-footnote">{footnote}</p> : null}
    </article>
  );
}

function SummaryBar({ items, className = "" }: SummaryBarProps) {
  return (
    <div className={cx("summary-bar", className)}>
      {items.map((item, index) => (
        <article key={`${item.label}-${index}`} className="summary-pill">
          <span className="summary-pill-label">{item.label}</span>
          <strong className={cx("summary-pill-value", item.toneClassName)}>{item.value}</strong>
        </article>
      ))}
    </div>
  );
}

function DecisionPointList({ items, className = "" }: { items: DecisionPoint[]; className?: string }) {
  return (
    <div className={cx("decision-list", className)}>
      {items.map((item, index) => (
        <article key={`${item.label}-${index}`} className="decision-item">
          <p className="decision-label">{item.label}</p>
          <p className={cx("decision-detail", item.toneClassName)}>{item.detail}</p>
        </article>
      ))}
    </div>
  );
}

function QuickDateNavigator({
  rows,
  selectedDate,
  prevDate,
  nextDate,
  disabled = false,
  onSelectDate,
  onShiftDate,
}: QuickDateNavigatorProps) {
  if (!rows.length) {
    return <div className="empty-block">暂无可导航的交易日</div>;
  }

  return (
    <div className="quick-date-nav">
      <div className="quick-date-toolbar">
        <button type="button" className="button button-secondary button-small" disabled={!prevDate || disabled} onClick={() => onShiftDate(-1)}>
          上一日
        </button>
        <span className="quick-date-selected">{selectedDate || "--"}</span>
        <button type="button" className="button button-ghost button-small" disabled={!nextDate || disabled} onClick={() => onShiftDate(1)}>
          下一日
        </button>
      </div>
      <div className="quick-date-list">
        {rows.map((row, index) => {
          const tradeDate = String(row.trade_date || "");
          const trend = marketTrendMeta(row.daily_return);
          return (
            <button
              key={`${tradeDate}-${index}`}
              type="button"
              className={cx("quick-date-item", tradeDate === selectedDate && "is-selected")}
              onClick={() => onSelectDate(tradeDate)}
              disabled={disabled}
            >
              <span className="mono">{tradeDate || "--"}</span>
              <span className={cx("quick-date-delta", trend.deltaClassName)}>
                {trend.symbol} {formatPercent(row.daily_return)}
              </span>
            </button>
          );
        })}
      </div>
      <p className="helper-text">总览用于快速判断；需要复盘上下文时请切到「交易日复盘」。</p>
    </div>
  );
}

function CalendarPanel({
  month,
  selectedDate,
  rows,
  onSelectDate,
  onPrevMonth,
  onNextMonth,
  onCurrentMonth,
  disabled = false,
}: CalendarPanelProps) {
  const cells = buildCalendarCells(month, rows);
  const monthRows = rows.filter((row) => String(row.trade_date || "").startsWith(`${month}-`));
  const monthSummary = monthRows.reduce<{ upDays: number; downDays: number; flatDays: number }>(
    (summary, row) => {
      const dailyReturn = toNumber(row.daily_return);
      if (Number.isFinite(dailyReturn)) {
        if (dailyReturn > 0) {
          summary.upDays += 1;
        } else if (dailyReturn < 0) {
          summary.downDays += 1;
        } else {
          summary.flatDays += 1;
        }
      }
      return summary;
    },
    { upDays: 0, downDays: 0, flatDays: 0 },
  );

  if (!cells.length) {
    return <div className="empty-block">暂无日历数据</div>;
  }

  return (
    <div className="calendar-panel">
      <div className="calendar-toolbar">
        <div>
          <strong>{formatMonthLabel(month)}</strong>
          <span>{monthRows.length} 个交易日</span>
        </div>
        <div className="calendar-toolbar-actions">
          <button type="button" className="icon-button" onClick={onPrevMonth} aria-label="上个月">
            ‹
          </button>
          <button type="button" className="button button-ghost button-small" onClick={onCurrentMonth}>
            选中月
          </button>
          <button type="button" className="icon-button" onClick={onNextMonth} aria-label="下个月">
            ›
          </button>
        </div>
      </div>

      <div className="calendar-meta">
        <span className="mini-stat">{monthRows.length} 个交易日</span>
        <span className="mini-stat summary-up">涨 {monthSummary.upDays}</span>
        <span className="mini-stat summary-down">跌 {monthSummary.downDays}</span>
        <span className="mini-stat">平 {monthSummary.flatDays}</span>
      </div>

      <div className="calendar-weekdays">
        {["一", "二", "三", "四", "五", "六", "日"].map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>

      <div className="calendar-grid">
        {cells.map((cell) => {
          const trend = marketTrendMeta(cell.row?.daily_return);
          const isDisabled = disabled || !cell.row;
          return (
            <button
              key={cell.date}
              type="button"
              className={cx(
                "calendar-cell",
                !cell.inCurrentMonth && "is-outside",
                cell.date === selectedDate && "is-selected",
                cell.row && trend.className,
              )}
              disabled={isDisabled}
              onClick={() => onSelectDate(cell.date)}
              title={
                cell.row
                  ? `${cell.date} · 净值 ${formatCurrency(cell.row.total_equity)} · 日收益 ${formatPercent(cell.row.daily_return)}`
                  : cell.date
              }
            >
              <span className="calendar-day">{cell.day}</span>
              <span className="calendar-cell-value">{cell.row ? formatPercent(cell.row.daily_return) : "—"}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StatusPill({ label, statusClass }: StatusPillProps) {
  return <span className={cx("status-pill", statusClass)}>{label}</span>;
}

function SymbolCell({ symbol, name }: SymbolCellProps) {
  return (
    <div>
      <div className="mono">{symbol || "--"}</div>
      <div className="muted symbol-subtext">{name || "--"}</div>
    </div>
  );
}

function Badge({ value, tone }: BadgeProps) {
  return <span className={cx("badge", tone)}>{value || "--"}</span>;
}

function DeltaText({ value, kind = "percent" }: DeltaTextProps) {
  const numericValue = toNumber(value);
  if (!Number.isFinite(numericValue)) {
    return <>--</>;
  }

  const trend = marketTrendMeta(numericValue);
  const formatted = kind === "percent" ? formatPercent(numericValue) : formatNumber(numericValue, 2);
  return (
    <span className={cx("delta-value", trend.deltaClassName)}>
      <span className="delta-arrow">{trend.symbol}</span>
      {formatted}
    </span>
  );
}

function NavChart({ rows, fallbackDelta }: NavChartProps) {
  const series = rows.filter((row) => Number.isFinite(toNumber(row.total_equity)));
  if (!series.length) {
    return <div className="chart-area empty-block">暂无净值序列</div>;
  }

  const values = series.map((row) => toNumber(row.total_equity));
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const width = 640;
  const height = 260;
  const padding = 24;
  const usableHeight = height - padding * 2;
  const usableWidth = width - padding * 2;
  const range = maxValue - minValue || 1;

  const points = series.map((row, index) => {
    const x = padding + (series.length === 1 ? usableWidth / 2 : (usableWidth * index) / (series.length - 1));
    const y = height - padding - ((toNumber(row.total_equity) - minValue) / range) * usableHeight;
    return { x, y };
  });

  const linePath = points.map((point) => `${point.x},${point.y}`).join(" ");
  const areaPath = [
    `${points[0].x},${height - padding}`,
    ...points.map((point) => `${point.x},${point.y}`),
    `${points[points.length - 1].x},${height - padding}`,
  ].join(" ");

  const latestRow = series[series.length - 1];
  const previousRow = series.length > 1 ? series[series.length - 2] : null;
  const delta = previousRow ? toNumber(latestRow.total_equity) - toNumber(previousRow.total_equity) : toNumber(fallbackDelta);
  const trend = marketTrendMeta(delta);
  const firstDate = series[0].trade_date || "--";
  const lastDate = latestRow.trade_date || "--";
  const lastPoint = points[points.length - 1];

  return (
    <div>
      <div className={cx("chart-area", "market-chart", trend.className)}>
        <div className="chart-headline">
          <span className={cx("trend-chip", trend.className)}>
            {trend.symbol} {trend.label}
          </span>
        </div>
        <svg className={cx("sparkline", trend.className)} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-label="组合净值走势">
          <g className="grid">
            {Array.from({ length: 4 }, (_, index) => {
              const y = padding + (usableHeight * index) / 3;
              return <line key={index} x1={padding} y1={y} x2={width - padding} y2={y}></line>;
            })}
          </g>
          <polygon className="area" points={areaPath}></polygon>
          <polyline className="line" points={linePath}></polyline>
          <circle className="point" cx={lastPoint.x} cy={lastPoint.y} r="5"></circle>
        </svg>
        <div className="sparkline-labels">
          <span>{firstDate}</span>
          <span>{lastDate}</span>
        </div>
      </div>

      <div className="chart-summary">
        <div className="chart-stat">
          <span>最新净值</span>
          <strong>{formatCurrency(latestRow.total_equity)}</strong>
        </div>
        <div className="chart-stat">
          <span>区间变化</span>
          <strong className={trend.deltaClassName}>
            {trend.symbol} {formatSignedCurrency(delta)}
          </strong>
        </div>
        <div className="chart-stat">
          <span>最新日收益</span>
          <strong>{formatPercent(latestRow.daily_return)}</strong>
        </div>
      </div>
    </div>
  );
}

function PipelineTimeline({ markdown }: PipelineTimelineProps) {
  const noteMap = extractStageNotes(markdown);

  return (
    <div className="timeline-list">
      {PIPELINE_STAGES.map((stage) => (
        <article key={stage.key} className={cx("timeline-item", noteMap.has(stage.key) && "is-active")}>
          <div className="timeline-title">
            <div>
              <strong>
                {stage.order}. {stage.label}
              </strong>
              <div className="timeline-meta">{stage.key}</div>
            </div>
          </div>
          <p>{noteMap.get(stage.key) || stage.description}</p>
        </article>
      ))}
    </div>
  );
}

function AllocationList({ rows }: AllocationListProps) {
  if (!rows.length) {
    return <div className="allocation-list empty-block">暂无持仓数据</div>;
  }

  const sortedRows = [...rows].sort((left, right) => toNumber(right.weight) - toNumber(left.weight)).slice(0, 8);

  return (
    <div className="allocation-list">
      {sortedRows.map((row, index) => {
        const numericWeight = toNumber(row.weight);
        const width = Number.isFinite(numericWeight) ? Math.max(6, Math.min(100, numericWeight * 100)) : 6;
        return (
          <article key={`${row.symbol || "allocation"}-${index}`} className="allocation-item">
            <div className="allocation-head">
              <div>
                <div className="allocation-symbol">{row.symbol || "--"}</div>
                <div className="allocation-name">{row.name || "--"}</div>
              </div>
              <strong>{formatPercent(row.weight)}</strong>
            </div>
            <div className="allocation-bar">
              <div className="allocation-fill" style={{ width: `${width}%` }}></div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function DataTable<RowType>({
  rows,
  columns,
  emptyText,
  rowClassName,
}: {
  rows: RowType[];
  columns: TableColumn<RowType>[];
  emptyText: string;
  rowClassName?: (row: RowType, index: number) => string;
}) {
  if (!rows.length) {
    return <div className="table-host empty-block">{emptyText}</div>;
  }

  return (
    <div className="table-host">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.label} className={column.className || ""}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className={rowClassName ? rowClassName(row, rowIndex) : ""}>
              {columns.map((column, columnIndex) => (
                <td key={`${rowIndex}-${columnIndex}`} className={column.className || ""}>
                  {column.render(row, rowIndex)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MarkdownRenderer({ markdown, emptyText }: MarkdownRendererProps) {
  const blocks = parseMarkdownBlocks(markdown);
  if (!blocks.length) {
    return <div className="markdown-body empty-block">{emptyText}</div>;
  }

  return <div className="markdown-body">{blocks.map((block, index) => renderMarkdownBlock(block, index))}</div>;
}

function renderMarkdownBlock(block: MarkdownBlock, index: number) {
  switch (block.type) {
    case "h1":
      return <h1 key={index}>{block.text}</h1>;
    case "h2":
      return <h2 key={index}>{block.text}</h2>;
    case "h3":
      return <h3 key={index}>{block.text}</h3>;
    case "ul":
      return (
        <ul key={index}>
          {block.items.map((item, itemIndex) => (
            <li key={itemIndex}>{item}</li>
          ))}
        </ul>
      );
    default:
      return <p key={index}>{block.text}</p>;
  }
}

function extractMarkdownExcerpt(markdown: string): string {
  if (!markdown) {
    return "暂无报告摘要。";
  }

  const lines = markdown.split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("# ")) {
      continue;
    }
    if (line.startsWith("## Stage Notes")) {
      continue;
    }
    if (line.startsWith("## ")) {
      continue;
    }
    if (line.startsWith("- ")) {
      return line.slice(2);
    }
    return line;
  }

  return "暂无报告摘要。";
}

function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  if (!markdown) {
    return [];
  }

  const lines = markdown.split(/\r?\n/);
  const blocks: MarkdownBlock[] = [];
  let listItems: string[] = [];

  const flushList = () => {
    if (listItems.length) {
      blocks.push({ type: "ul", items: listItems });
      listItems = [];
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }
    if (line.startsWith("# ")) {
      flushList();
      blocks.push({ type: "h1", text: line.slice(2) });
      continue;
    }
    if (line.startsWith("## ")) {
      flushList();
      blocks.push({ type: "h2", text: line.slice(3) });
      continue;
    }
    if (line.startsWith("### ")) {
      flushList();
      blocks.push({ type: "h3", text: line.slice(4) });
      continue;
    }
    if (line.startsWith("- ")) {
      listItems.push(line.slice(2));
      continue;
    }
    flushList();
    blocks.push({ type: "p", text: line });
  }

  flushList();
  return blocks;
}

function extractStageNotes(markdown: string): Map<string, string> {
  const notes = new Map<string, string>();
  if (!markdown) {
    return notes;
  }

  const lines = markdown.split(/\r?\n/);
  let inStageSection = false;

  for (const line of lines) {
    if (line.startsWith("## ")) {
      inStageSection = line.trim() === "## Stage Notes";
      continue;
    }
    if (!inStageSection) {
      continue;
    }
    const matched = line.match(/^- ([^:]+):\s*(.*)$/);
    if (matched) {
      notes.set(matched[1].trim(), matched[2].trim());
    }
  }

  return notes;
}

async function safeFetch<ResponseType>(apiBase: string, path: string, options?: RequestInit): Promise<ResponseType | null> {
  try {
    return await fetchJson<ResponseType>(apiBase, path, options);
  } catch {
    return null;
  }
}

async function fetchJson<ResponseType>(apiBase: string, path: string, options: RequestInit = {}): Promise<ResponseType> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  const response = await fetch(buildUrl(apiBase, path), {
    ...options,
    headers,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload: unknown = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    let message = `请求失败：${response.status} ${response.statusText}`;
    if (typeof payload === "string") {
      message = payload;
    } else if (
      payload &&
      typeof payload === "object" &&
      "error" in payload &&
      typeof (payload as { error?: unknown }).error === "string"
    ) {
      message = (payload as { error: string }).error;
    }
    throw new Error(message);
  }

  return payload as ResponseType;
}

function buildUrl(apiBase: string, path: string): string {
  const base = normalizeBaseUrl(apiBase);
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

function deriveDefaultApiBase(): string {
  if (window.location.protocol.startsWith("http")) {
    return window.location.origin.replace(/\/$/, "");
  }
  return "http://127.0.0.1:8787";
}

function normalizeBaseUrl(value: string): string {
  const cleaned = String(value || "").trim();
  return cleaned.replace(/\/+$/, "") || deriveDefaultApiBase();
}

function toMonthValue(date: string): string {
  if (/^\d{4}-\d{2}/.test(date)) {
    return date.slice(0, 7);
  }
  return todayIso().slice(0, 7);
}

function shiftMonthValue(month: string, offset: number): string {
  const matched = month.match(/^(\d{4})-(\d{2})$/);
  if (!matched) {
    return todayIso().slice(0, 7);
  }
  const next = new Date(Number(matched[1]), Number(matched[2]) - 1 + offset, 1);
  return `${next.getFullYear()}-${padNumber(next.getMonth() + 1)}`;
}

function formatMonthLabel(month: string): string {
  const matched = month.match(/^(\d{4})-(\d{2})$/);
  if (!matched) {
    return "--";
  }
  return `${matched[1]}年${matched[2]}月`;
}

function buildCalendarCells(month: string, rows: NavRow[]): CalendarCell[] {
  const matched = month.match(/^(\d{4})-(\d{2})$/);
  if (!matched) {
    return [];
  }

  const year = Number(matched[1]);
  const monthIndex = Number(matched[2]) - 1;
  const firstDay = new Date(year, monthIndex, 1);
  const firstWeekday = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const totalCells = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;
  const rowMap = new Map(rows.filter((row) => row.trade_date).map((row) => [String(row.trade_date), row]));

  return Array.from({ length: totalCells }, (_, index) => {
    const date = new Date(year, monthIndex, index - firstWeekday + 1);
    const isoDate = `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`;
    return {
      date: isoDate,
      day: date.getDate(),
      inCurrentMonth: date.getMonth() === monthIndex,
      row: rowMap.get(isoDate) || null,
    };
  });
}

function metricToneClass(value: NumberLike): string {
  const trend = marketTrendMeta(value);
  if (trend.className === "trend-up") {
    return "metric-card-up";
  }
  if (trend.className === "trend-down") {
    return "metric-card-down";
  }
  return "";
}

function toneClassFromTrend(trendClassName: string): string {
  if (trendClassName === "trend-up") {
    return "summary-up";
  }
  if (trendClassName === "trend-down") {
    return "summary-down";
  }
  return "";
}

function formatRatio(numerator: number, denominator: number): string {
  if (!denominator) {
    return "--";
  }
  return `${numerator}/${denominator} (${formatPercent(numerator / denominator)})`;
}

function marketTrendMeta(value: NumberLike): {
  className: string;
  deltaClassName: string;
  label: string;
  symbol: string;
} {
  const numericValue = toNumber(value);
  if (!Number.isFinite(numericValue) || numericValue === 0) {
    return {
      className: "trend-flat",
      deltaClassName: "delta-flat",
      label: "持平",
      symbol: "•",
    };
  }

  if (numericValue > 0) {
    return {
      className: "trend-up",
      deltaClassName: "delta-positive",
      label: "上涨",
      symbol: "▲",
    };
  }

  return {
    className: "trend-down",
    deltaClassName: "delta-negative",
    label: "回撤",
    symbol: "▼",
  };
}

function actionRowClassName(action?: string): string {
  if (["BUILD", "ADD"].includes(action || "")) {
    return "table-row-up";
  }
  if (["REDUCE", "EXIT"].includes(action || "")) {
    return "table-row-down";
  }
  return "table-row-neutral";
}

function positionRowClassName(row: PositionRow): string {
  const pnl = toNumber(row.unrealized_pnl_pct);
  if (!Number.isFinite(pnl) || pnl === 0) {
    return "table-row-neutral";
  }
  return pnl > 0 ? "table-row-up" : "table-row-down";
}

function actionTone(action?: string): string {
  if (["BUILD", "ADD"].includes(action || "")) {
    return "badge-buy";
  }
  if (["REDUCE", "EXIT"].includes(action || "")) {
    return "badge-sell";
  }
  return "badge-hold";
}

function statusTone(status?: string): string {
  if (["FILLED", "ACCEPTED", "COMPLETED"].includes(status || "")) {
    return "badge-positive";
  }
  if (["REJECTED", "FAILED"].includes(status || "")) {
    return "badge-negative";
  }
  return "badge-neutral";
}

function boardTone(board?: string): string {
  if (board === "CHINEXT") {
    return "badge-board-chinext";
  }
  if (board === "STAR") {
    return "badge-board-star";
  }
  if (board === "BSE") {
    return "badge-board-bse";
  }
  if (board === "MAIN") {
    return "badge-board-main";
  }
  return "badge-board-other";
}

function formatBoardLabel(board?: string): string {
  if (board === "CHINEXT") {
    return "创业板";
  }
  if (board === "STAR") {
    return "科创板";
  }
  if (board === "BSE") {
    return "北交所";
  }
  if (board === "MAIN") {
    return "主板";
  }
  return board || "--";
}

function formatAvailablePosition(availableQuantity: NumberLike, quantity: NumberLike): string {
  const available = formatNumber(availableQuantity, 0);
  const total = formatNumber(quantity, 0);
  if (available === "--" && total === "--") {
    return "--";
  }
  return `${available === "--" ? "0" : available} / ${total === "--" ? "0" : total}`;
}

function intradayReturn(prevClose: NumberLike, lastPrice: NumberLike): number {
  const previous = toNumber(prevClose);
  const latest = toNumber(lastPrice);
  if (!Number.isFinite(previous) || !Number.isFinite(latest) || previous === 0) {
    return Number.NaN;
  }
  return (latest - previous) / previous;
}

function planReferencePrice(row: PlanRow): NumberLike {
  if (["BUILD", "ADD"].includes(row.action || "")) {
    return row.entry_price_final;
  }
  if (row.action === "REDUCE") {
    return row.reduce_price_final;
  }
  if (row.action === "EXIT") {
    return row.exit_price_final;
  }
  return row.entry_price_final ?? row.reduce_price_final ?? row.exit_price_final;
}

function formatBasisPoints(value: NumberLike): string {
  const numericValue = toNumber(value);
  if (!Number.isFinite(numericValue)) {
    return "--";
  }
  return `${numericValue >= 0 ? "+" : ""}${numericValue.toFixed(0)}`;
}

function formatCurrency(value: NumberLike): string {
  const numericValue = toNumber(value);
  if (!Number.isFinite(numericValue)) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numericValue);
}

function formatSignedCurrency(value: NumberLike): string {
  const numericValue = toNumber(value);
  if (!Number.isFinite(numericValue)) {
    return "--";
  }
  return `${numericValue >= 0 ? "+" : ""}${formatCurrency(numericValue)}`;
}

function formatPercent(value: NumberLike): string {
  const numericValue = toNumber(value);
  if (!Number.isFinite(numericValue)) {
    return "--";
  }
  return `${(numericValue * 100).toFixed(2)}%`;
}

function formatNumber(value: NumberLike, digits = 2): string {
  const numericValue = toNumber(value);
  if (!Number.isFinite(numericValue)) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(numericValue);
}

function toNumber(value: NumberLike): number {
  if (typeof value === "number") {
    return value;
  }
  const numericValue = Number.parseFloat(String(value ?? "").replace(/,/g, ""));
  return Number.isFinite(numericValue) ? numericValue : Number.NaN;
}

function displayValue(value: unknown): string {
  if (value === 0) {
    return "0";
  }
  if (value === false) {
    return "false";
  }
  if (value === true) {
    return "true";
  }
  return String(value || "--");
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "未知错误");
}

function todayIso(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function padNumber(value: number): string {
  return String(value).padStart(2, "0");
}

function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}
