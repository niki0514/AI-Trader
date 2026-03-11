# AI Trader Backend

一个基于 `Python 3` 标准库实现的交易后端 MVP，用来把 **日级交易快照** 转成可追溯的：

- 持仓动作
- 候选股票
- AI 研判结论
- 交易计划
- 模拟成交
- 净值与风险报告

当前默认语境为 **A 股**，并支持：

1. 单日流水线运行
2. 状态化回测
3. 同步 HTTP API 查询

如果你第一次看这个项目，推荐阅读顺序：

1. `README.md`
2. `backend/README.md`
3. `backend/docs/architecture.md`
4. `backend/docs/api-mvp.md`

## 1. 后端能做什么

### 1.1 单日运行

输入一份交易日快照，产出完整日级结果。

入口：

```text
backend/run_single_day.py
```

### 1.2 状态化回测

按 manifest 定义的多个交易日逐日执行流水线，并可把上一日持仓和现金传递给下一日。

入口：

```text
backend/run_backtest.py
```

### 1.3 HTTP API

可通过接口触发单日任务、读取持仓、交易计划、成交、NAV 和报告。

入口：

```text
backend/run_api.py
```

## 2. 最短上手路径

### 2.1 跑一个单日样例

```bash
python3 backend/run_single_day.py --run-id demo-single
```

完成后查看：

```text
backend/outputs/demo-single/
```

### 2.2 启动 API

```bash
python3 backend/run_api.py --host 127.0.0.1 --port 8787
```

验证：

```bash
curl http://127.0.0.1:8787/healthz
```

### 2.3 跑一个回测样例

```bash
python3 backend/run_backtest.py \
  --manifest backend/examples/input/backtest_manifest.json \
  --config backend/app/config/pipeline.yaml
```

## 3. 核心概念

### 3.1 `snapshot`

单日运行的输入对象，示例见：

```text
backend/examples/input/daily_snapshot.json
```

顶层关键字段包括：

- `trade_date`
- `account`
- `positions`
- `watchlist`
- `recent_events`
- `fundamentals`
- `market`

### 3.2 `run_id`

每次运行的唯一标识，用来决定输出目录名称。

例如：

```text
backend/outputs/demo-single/
backend/outputs/backtests/backtest-demo-123456/
```

### 3.3 `trade_date`

交易日，格式必须是：

```text
YYYY-MM-DD
```

### 3.4 `risk_mode`

风险模式，影响仓位上限和建仓强度。默认可能为：

- `RISK_ON`
- `NEUTRAL`
- `RISK_OFF`

在回撤保护触发时也可能出现：

- `DRAWDOWN_GUARD`

## 4. 单日流水线

### 4.1 7 个阶段

| 顺序 | 阶段 | 作用 | 主要产物 |
| --- | --- | --- | --- |
| 01 | `update_holding_actions` | 复核已有持仓，生成 HOLD / REDUCE / EXIT | `holding_actions_t.csv` |
| 02 | `selector` | 从观察池筛出技术候选 | `tech_candidates_t.csv` |
| 03 | `analyst` | 合成技术、事件、基本面，生成 AI 结论 | `ai_insights_t.csv` |
| 04 | `decider` | 合并存量动作与新增建议为订单草案 | `orders_candidate_t.csv` |
| 05 | `risk_guard` | 套用仓位和风控规则 | `trade_plan_t.csv` |
| 06 | `executor` | 做模拟成交并更新组合 | `sim_fill_t.csv`、`positions_t.csv`、`nav_t.csv` |
| 07 | `reporter` | 汇总指标和风险报告 | `metrics_t.json`、`risk_report_t.md` |

### 4.2 输出目录结构

```text
backend/outputs/<run_id>/
├── holding_actions_t.csv
├── tech_candidates_t.csv
├── ai_insights_t.csv
├── orders_candidate_t.csv
├── trade_plan_t.csv
├── sim_fill_t.csv
├── positions_t.csv
├── nav_t.csv
├── metrics_t.json
├── risk_report_t.md
├── final_payload.json
└── stages/
    ├── 01_update_holding_actions.json
    ├── 02_selector.json
    ├── 03_analyst.json
    ├── 04_decider.json
    ├── 05_risk_guard.json
    ├── 06_executor.json
    └── 07_reporter.json
```

### 4.3 如何理解这些文件

| 文件 | 用途 |
| --- | --- |
| `holding_actions_t.csv` | 对现有持仓的动作建议 |
| `tech_candidates_t.csv` | 技术筛选后的候选池 |
| `ai_insights_t.csv` | AI / 规则研判结果 |
| `orders_candidate_t.csv` | 风控前订单草案 |
| `trade_plan_t.csv` | 风控后的正式计划 |
| `sim_fill_t.csv` | 模拟成交明细 |
| `positions_t.csv` | 日终持仓 |
| `nav_t.csv` | 日终净值 |
| `metrics_t.json` | 结构化指标摘要 |
| `risk_report_t.md` | 可读风险日报 |
| `stages/*.json` | 每个阶段的完整中间状态 |

## 5. 输入与调用方式

### 5.1 单日命令

```bash
python3 backend/run_single_day.py \
  --input backend/examples/input/daily_snapshot.json \
  --config backend/app/config/pipeline.yaml \
  --output-root backend/outputs \
  --trade-date 2026-03-10 \
  --run-id demo-single
```

参数说明：

- `--input`：输入快照 JSON
- `--config`：配置文件
- `--output-root`：输出根目录
- `--trade-date`：覆盖输入里的交易日
- `--run-id`：指定输出目录名

### 5.2 回测命令

```bash
python3 backend/run_backtest.py \
  --manifest backend/examples/input/backtest_manifest.json \
  --config backend/app/config/pipeline.yaml \
  --output-root backend/outputs/backtests
```

回测输出目录：

```text
backend/outputs/backtests/<run_id>/
```

### 5.3 API 命令

```bash
python3 backend/run_api.py \
  --host 127.0.0.1 \
  --port 8787 \
  --output-root backend/outputs \
  --default-config backend/app/config/pipeline.yaml \
  --default-input backend/examples/input/daily_snapshot.json
```

完整接口说明见 `backend/docs/api-mvp.md`。

## 6. API 输出扫描规则

API 不依赖数据库，而是扫描输出目录。

### 6.1 扫描位置

- 单日运行：`backend/outputs/<run_id>/`
- 回测逐日：`backend/outputs/backtests/<backtest_run_id>/days/<trade_date>/`

### 6.2 “最新结果”的定义

对同一个 `trade_date`：

- 单日结果和回测日结果都会被纳入候选
- API 按目录更新时间选出“最新”那一份

这意味着：

- 你先跑回测、再跑单日，接口通常会优先返回单日那次的结果
- `GET /nav` 也是按日期去重后返回最新结果集合

## 7. 配置与环境变量

默认配置文件：

```text
backend/app/config/pipeline.yaml
```

### 7.1 推荐环境

- `Python 3.10+`
- 不安装第三方依赖也可跑通样例
- 若安装了 `PyYAML`，配置会优先走 `yaml.safe_load`

### 7.2 常用配置项

| 配置项 | 作用 |
| --- | --- |
| `selection.top_n` | 候选池保留数量 |
| `decision.build_score_floor` | 新开仓分数阈值 |
| `decision.add_score_floor` | 加仓分数阈值 |
| `risk.mode_caps.*` | 风险模式下组合总仓位上限 |
| `risk_rules.single_stock_cap.value` | 单票仓位上限 |
| `execution.slippage_bps` | 模拟执行滑点 |
| `llm.enable_live` | 是否启用 live LLM |
| `degrade.disable_selector` | 关闭 selector 做降级测试 |
| `degrade.disable_executor` | 关闭 executor 做降级测试 |

### 7.3 LLM 相关

默认：

- `llm.enable_live=false`
- 未配置外部模型也能完整跑通示例

若要启用 live LLM：

1. 在配置中把 `llm.enable_live` 改为 `true`
2. 设置环境变量 `GMN_API_KEY`

示例：

```bash
export GMN_API_KEY=your_api_key
python3 backend/run_single_day.py --run-id live-llm-demo
```

如果 LLM 调用失败，系统会降级到本地规则结论。

## 8. 常见问题

### 8.1 为什么 API 查不到数据

常见原因：

- 还没跑过单日或回测
- `output_root` 与你实际写出的目录不一致
- `trade_date` 格式不是 `YYYY-MM-DD`

### 8.2 为什么接口里的数字是字符串

因为 `positions / plans / fills / nav` 来自 CSV，经 `DictReader` 读取后大多是字符串。

只有 `metrics_t.json` 这类 JSON 产物会保留数值类型。

### 8.3 为什么 live LLM 没有生效

检查：

- `pipeline.yaml` 里是否把 `llm.enable_live` 打开
- 是否设置了 `GMN_API_KEY`
- `llm.endpoint` 是否可访问

### 8.4 为什么前端页面打开但没有数据

检查：

- 是否先启动了 `backend/run_api.py`
- 是否使用了正确端口 `8787`
- 若走静态托管，是否已执行 `npm run build`

## 9. 相关文档

- 功能架构：`backend/docs/architecture.md`
- API 调用：`backend/docs/api-mvp.md`
- 产品规划：`backend/docs/backend-plan.md`
- 前端说明：`frontend/README.md`
