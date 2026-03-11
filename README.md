# AI Trader

一个面向 **A 股日级交易决策** 的本地化项目，包含：

- `backend/`：Python 标准库实现的交易后端 MVP
- `frontend/`：React + TypeScript + Vite 工作台

当前项目适合三类使用方式：

1. 用一个交易日快照跑完整条交易流水线
2. 用同一套流水线做状态化回测
3. 通过 HTTP API 或前端工作台查看结果

项目当前 **不包含** 数据库、消息队列、真实券商交易接口；核心设计是“**文件驱动 + 可回放 + 易审计**”。

## 5 分钟跑通

以下命令都默认在项目根目录执行。

### 1. 跑一个单日样例

```bash
python3 backend/run_single_day.py --run-id demo-single
```

成功后会在 `backend/outputs/demo-single/` 下看到：

- `holding_actions_t.csv`
- `tech_candidates_t.csv`
- `ai_insights_t.csv`
- `orders_candidate_t.csv`
- `trade_plan_t.csv`
- `sim_fill_t.csv`
- `positions_t.csv`
- `nav_t.csv`
- `metrics_t.json`
- `risk_report_t.md`

### 2. 启动后端 API

```bash
python3 backend/run_api.py --host 127.0.0.1 --port 8787
```

快速检查：

```bash
curl http://127.0.0.1:8787/healthz
```

### 3. 可选：启动前端工作台

```bash
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

## 常见工作流

### 工作流 A：单日策略输出

```bash
python3 backend/run_single_day.py \
  --input backend/examples/input/daily_snapshot.json \
  --config backend/app/config/pipeline.yaml \
  --output-root backend/outputs \
  --trade-date 2026-03-10 \
  --run-id demo-single
```

适合：

- 验证一份输入快照能否正常跑通
- 查看 7 个阶段的中间产物
- 调参数后比对输出变化

### 工作流 B：通过 API 触发任务并查询结果

先启动服务：

```bash
python3 backend/run_api.py
```

再触发一次同步单日任务：

```bash
curl -X POST http://127.0.0.1:8787/jobs/run-daily \
  -H 'Content-Type: application/json' \
  -d '{
    "input_file": "backend/examples/input/daily_snapshot.json",
    "config_file": "backend/app/config/pipeline.yaml",
    "run_id": "api-demo-20260310"
  }'
```

然后查询：

```bash
curl http://127.0.0.1:8787/positions/latest
curl http://127.0.0.1:8787/plans/2026-03-10
curl http://127.0.0.1:8787/fills/2026-03-10
curl "http://127.0.0.1:8787/nav?start=2026-03-01&end=2026-03-10"
curl http://127.0.0.1:8787/reports/daily/2026-03-10
```

### 工作流 C：回测

```bash
python3 backend/run_backtest.py \
  --manifest backend/examples/input/backtest_manifest.json \
  --config backend/app/config/pipeline.yaml
```

输出位于：

```text
backend/outputs/backtests/<run_id>/
```

其中会包含：

- `backtest_nav.csv`
- `backtest_fills.csv`
- `backtest_summary.json`
- `walk_forward_report.md`
- `days/<trade_date>/...` 每日完整流水线产物

## 项目如何工作

后端运行路径统一复用同一条 7 段流水线：

1. `update_holding_actions`
2. `selector`
3. `analyst`
4. `decider`
5. `risk_guard`
6. `executor`
7. `reporter`

你可以把它理解成：

```text
输入快照 -> 持仓复核 -> 候选筛选 -> AI研判 -> 订单草案
         -> 风控拦截 -> 模拟执行 -> 指标/报告/查询产物
```

更详细的模块图见 `backend/docs/architecture.md`。

## 目录总览

```text
ai_trader/
├── backend/
│   ├── app/                  # 后端核心代码
│   ├── docs/                 # 后端文档
│   ├── examples/input/       # 示例输入
│   ├── outputs/              # 运行输出
│   ├── run_api.py            # API 服务入口
│   ├── run_backtest.py       # 回测入口
│   └── run_single_day.py     # 单日入口
├── frontend/
│   ├── src/                  # 前端源码
│   ├── dist/                 # 构建产物
│   └── README.md             # 前端说明
└── README.md
```

## 文档导航

- 项目总览与后端使用：`backend/README.md`
- 后端功能架构：`backend/docs/architecture.md`
- API 调用手册：`backend/docs/api-mvp.md`
- 前端工作台说明：`frontend/README.md`

## 当前边界

- 默认语境为 **A 股**
- 默认执行为 **paper simulation**，不会真的下单
- API 当前为 **同步接口**
- 查询结果来自 `backend/outputs/` 文件系统，而不是数据库
- 若启用 live LLM，需要自行配置 `GMN_API_KEY` 并打开 `llm.enable_live`
