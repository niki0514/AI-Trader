# AI Trader 各环节输入输出 Demo

本文基于一次真实样例运行整理，方便接口联调、产品评审、接口说明。

- 示例输入：`examples/input/daily_snapshot.json`
- 示例运行：`python3 run_single_day.py --run-id io-demo-20260310`
- 示例输出目录：`outputs/io-demo-20260310/`

## 1. 总入口输入 Demo

单日流水线的统一输入是一个 `snapshot` JSON。

最小理解可以抓这几个顶层字段：

- `trade_date`
- `account`
- `positions`
- `watchlist`
- `recent_events`
- `fundamentals`
- `market`

输入片段示例：

```json
{
  "trade_date": "2026-03-10",
  "market": {
    "regime": "NEUTRAL"
  },
  "account": {
    "cash": 120000,
    "total_equity": 320000,
    "prev_total_equity": 318600,
    "initial_equity": 300000,
    "portfolio_drawdown_pct": 0.054
  },
  "positions": [
    {
      "symbol": "600519.SH",
      "name": "贵州茅台",
      "quantity": 100,
      "avg_cost": 1580.0,
      "last_price": 1642.0,
      "last_trade_date": "2026-03-04",
      "board": "MAIN",
      "is_st": false,
      "suspended": false
    }
  ],
  "watchlist": [
    {
      "symbol": "601899.SH",
      "name": "紫金矿业",
      "last_price": 18.42,
      "momentum_score": 0.82,
      "breakout_score": 0.79,
      "liquidity_score": 0.86
    }
  ]
}
```

## 2. 环节一：`update_holding_actions`

功能：复核已有持仓，生成 `HOLD / REDUCE / EXIT` 建议，并标准化上一日持仓视图。

输入关注字段：

- `snapshot.account`
- `snapshot.positions`
- `snapshot.recent_events`
- 配置：`holding.*`、`risk_rules.single_stock_cap`

输出新增 payload 字段：

- `account`
- `risk_mode`
- `positions_prev`
- `positions`
- `holding_actions`

输出文件：

- `holding_actions_t.csv`

输出 demo：

```csv
trade_date,symbol,name,action_today,current_weight,target_weight,risk_level,reason
2026-03-10,600519.SH,贵州茅台,REDUCE,0.513125,0.12,MEDIUM,rebalance_to_cap current_weight=51.31%; cap=12.00%
2026-03-10,300750.SZ,宁德时代,REDUCE,0.15375,0.12,MEDIUM,rebalance_to_cap current_weight=15.38%; cap=12.00%
2026-03-10,601318.SH,中国平安,HOLD,0.098625,0.098625,LOW,within_band pnl=3.54%; event_score=0.57
```

说明：

- 贵州茅台仓位达到 `51.31%`，超过单票上限 `12%`，所以被标记为 `REDUCE`
- 中国平安处于合理区间，因此保留 `HOLD`

## 3. 环节二：`selector`

功能：从观察池中筛出技术候选，并计算技术评分。

输入关注字段：

- `snapshot.watchlist`
- 配置：`selection.*`、`a_share.selection.*`

输出新增 payload 字段：

- `tech_candidates`
- `selector_failed`

输出文件：

- `tech_candidates_t.csv`

输出 demo：

```csv
trade_date,symbol,name,rule_pass,tech_score,turnover_rate,relative_volume,trigger_tags
2026-03-10,300308.SZ,中际旭创,true,0.8308250891270623,0.056,1.72,momentum|breakout|liquidity|volume_ratio|chinext
2026-03-10,601899.SH,紫金矿业,true,0.8188449845124357,0.041,1.68,momentum|breakout|liquidity|volume_ratio
2026-03-10,002371.SZ,北方华创,true,0.7837324929039791,0.038,1.45,momentum|breakout|liquidity
```

说明：

- `rule_pass=true` 表示通过了技术和流动性过滤
- `tech_score` 是后续 AI 研判的重要输入之一

## 4. 环节三：`analyst`

功能：把技术面、事件面、基本面合成为交易倾向，生成 `BUILD / ADD / HOLD` 提示和论点。

输入关注字段：

- `tech_candidates`
- `snapshot.recent_events`
- `snapshot.fundamentals`
- `positions_prev`

输出新增 payload 字段：

- `ai_insights`

输出文件：

- `ai_insights_t.csv`

输出 demo：

```csv
trade_date,symbol,action_hint,confidence,combined_score,thesis
2026-03-10,300308.SZ,BUILD,0.83,0.80,"光模块景气延续，技术强度和事件催化共振，适合试探建仓"
2026-03-10,601899.SH,BUILD,0.83,0.81,"金铜价格维持高位，供给兑现配合趋势突破，可继续跟随"
2026-03-10,000858.SZ,HOLD,0.76,0.68,"消费修复仍在但弹性一般，暂不追价，维持观察"
```

说明：

- `combined_score` 足够高且当前未持仓时，通常会给出 `BUILD`
- 分数不够或边际一般时，给出 `HOLD`

## 5. 环节四：`decider`

功能：把“存量持仓动作”和“新增 AI 建议”合并成订单草案。

输入关注字段：

- `holding_actions`
- `ai_insights`
- `positions_prev`
- `risk_mode`

输出新增 payload 字段：

- `orders_candidate`

输出文件：

- `orders_candidate_t.csv`

输出 demo：

```csv
trade_date,order_id,symbol,action,w_ai,w_candidate,target_weight,entry_price
2026-03-10,20260310-600519SH-reduce-001,600519.SH,REDUCE,0.0,0.12,0.12,0.0
2026-03-10,20260310-300308SZ-build-004,300308.SZ,BUILD,0.036121467286123754,0.036121467286123754,0.036121467286123754,158.52671999999998
2026-03-10,20260310-601899SH-build-005,601899.SH,BUILD,0.040240236221497847,0.040240236221497847,0.040240236221497847,18.434736
```

说明：

- 存量仓位会变成 `REDUCE/HOLD/EXIT` 订单草案
- 新候选股会变成 `BUILD/ADD` 草案，并带出建议仓位和进场价

## 6. 环节五：`risk_guard`

功能：把订单草案套上组合风控、单票上限、板块上限、流动性上限、回撤保护等规则，形成正式交易计划。

输入关注字段：

- `orders_candidate`
- `positions_prev`
- `tech_candidates`
- `account`
- `risk_mode`

输出新增 payload 字段：

- `trade_plan`
- `risk_events`
- `risk_guard_failed`

输出文件：

- `trade_plan_t.csv`

输出 demo：

```csv
trade_date,order_id,symbol,action,target_weight,w_final,status,cap_hit_reason,risk_mode
2026-03-10,20260310-600519SH-reduce-001,600519.SH,REDUCE,0.12,0.12,ACCEPTED,,NEUTRAL
2026-03-10,20260310-601899SH-build-005,601899.SH,BUILD,0.040240236221497847,0.040240236221497847,ACCEPTED,,NEUTRAL
2026-03-10,20260310-688111SH-build-008,688111.SH,BUILD,0.028938326157461277,0.00886456243907019,ACCEPTED,cap_trimmed,NEUTRAL
```

说明：

- `w_final` 是风控之后真正允许执行的最终仓位
- `688111.SH` 虽然被接受，但因为风险预算不够，被从 `2.89%` 砍到 `0.89%`

## 7. 环节六：`executor`

功能：按交易计划做模拟成交，计算成交价、费用、现金变化、最新持仓和日终净值。

输入关注字段：

- `trade_plan`
- `account`
- `positions_prev`
- `snapshot.watchlist`

输出新增 payload 字段：

- `sim_fill`
- `positions`
- `nav`
- `executor_failed`

输出文件：

- `sim_fill_t.csv`
- `positions_t.csv`
- `nav_t.csv`

成交输出 demo：

```csv
trade_date,order_id,symbol,action,fill_price,quantity,filled_amount,total_fee,status,note
2026-03-10,20260310-600519SH-reduce-001,600519.SH,REDUCE,1640.6864,100.0,164068.64,132.89559839999998,FILLED,sell_filled
2026-03-10,20260310-601899SH-build-005,601899.SH,BUILD,18.4494837888,600.0,11069.690273279999,5.1106969027328,FILLED,build_filled
2026-03-10,20260310-300308SZ-build-004,300308.SZ,BUILD,0.0,0.0,0.0,0.0,SKIPPED,no_affordable_round_lot
```

最新持仓 demo：

```csv
trade_date,symbol,name,quantity,avg_cost,last_price,market_value,weight
2026-03-10,300750.SZ,宁德时代,200.0,252.0,246.0,49200.0,0.13490886645539396
2026-03-10,601318.SH,中国平安,600.0,50.8,52.6,31560.0,0.08653910214089906
2026-03-10,601899.SH,紫金矿业,600.0,18.45800161697122,18.4494837888,11069.690273279999,0.030353645666270426
```

净值输出 demo：

```csv
trade_date,cash,market_value,total_equity,trading_fees,daily_return,cum_return,max_drawdown,filled_order_count
2026-03-10,272860.9434314172,91829.69027328,364690.63370469725,138.00629530273278,0.1446661447102864,0.21563544568232415,0.054,2
```

说明：

- `SKIPPED/no_affordable_round_lot` 表示策略想买，但现金和整手规则下无法成交
- 执行后会同步刷新现金、持仓和净值

## 8. 环节七：`reporter`

功能：汇总整条链路的指标和风险日报。

输入关注字段：

- `trade_plan`
- `sim_fill`
- `positions_prev`
- `positions`
- `nav`
- `risk_events`
- `stage_notes`

输出新增 payload 字段：

- `metrics`
- `report_files`

输出文件：

- `metrics_t.json`
- `risk_report_t.md`

指标输出 demo：

```json
{
  "run_id": "io-demo-20260310",
  "trade_date": "2026-03-10",
  "daily_return": 0.1446661447102864,
  "cum_return": 0.21563544568232415,
  "max_drawdown": 0.054,
  "trading_fees": 138.00629530273278,
  "risk_intercept_count": 1,
  "filled_order_count": 2,
  "accepted_order_count": 8,
  "selector_failed": false,
  "risk_mode": "NEUTRAL"
}
```

日报输出片段 demo：

```md
## Risk Events
- 688111.SH BUILD -> ACCEPTED (cap_trimmed)

## Execution
- 600519.SH REDUCE qty=100.00 status=FILLED fee=132.90 note=sell_filled
- 601899.SH BUILD qty=600.00 status=FILLED fee=5.11 note=build_filled
```

## 9. 最终总输出 `final_payload.json`

流水线每个阶段都是“在已有 payload 上继续追加字段”，因此最终 `final_payload.json` 会包含：

- 原始输入：`snapshot`
- 账户与持仓中间态：`account`、`positions_prev`
- 各阶段结果：`holding_actions`、`tech_candidates`、`ai_insights`、`orders_candidate`、`trade_plan`、`sim_fill`、`positions`、`nav`
- 报告和指标：`metrics`、`report_files`
- 运行标记：`selector_failed`、`risk_guard_failed`、`executor_failed`
- 调试说明：`stage_notes`

这份文件最适合做：

- 接口联调
- 回放问题单
- 排查“某个订单为什么被拦截/为什么没成交”

## 10. 一句话串起来

整条链路可以理解为：

```text
snapshot 输入
-> 持仓复核
-> 候选筛选
-> AI 研判
-> 订单草案
-> 风控定稿
-> 模拟执行
-> 指标/报告输出
```
