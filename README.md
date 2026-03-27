# AI Trader

一个面向 **A 股日级交易决策** 的本地化项目，当前包含：

- `app/`：核心业务与编排代码
- 根目录运行脚本：单日、回测、API、选股、资讯搜索入口
- `docs/`、`examples/`、`outputs/`：文档、示例输入与运行产物

当前项目适合三类使用方式：

1. 用一个交易日快照跑完整条交易流水线
2. 用同一套流水线做状态化回测
3. 通过 HTTP API 触发任务并查询结果

项目当前 **不包含** 数据库、消息队列、真实券商交易接口；核心设计是“**文件驱动 + 可回放 + 易审计**”。

当前后端还支持 **可组合 pipeline**：各阶段已注册为独立 stage，可通过配置、CLI 或 API 选择只运行部分阶段。

## 5 分钟跑通

以下命令都默认在项目根目录执行。

### 1. 跑一个单日样例

```bash
python3 run_single_day.py --run-id demo-single
```

成功后会在 `outputs/demo-single/` 下看到：

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
python3 run_api.py --host 127.0.0.1 --port 8787
```

快速检查：

```bash
curl http://127.0.0.1:8787/healthz
```

## 常见工作流

### 工作流 A：单日策略输出

```bash
python3 run_single_day.py \
  --input examples/input/daily_snapshot.json \
  --config app/config/pipeline.yaml \
  --output-root outputs \
  --trade-date 2026-03-10 \
  --run-id demo-single
```

适合：

- 验证一份输入快照能否正常跑通
- 查看 7 个阶段的中间产物
- 调参数后比对输出变化

如果只想跑部分环节，也可以临时覆写 pipeline：

```bash
python3 run_single_day.py \
  --input examples/input/candidate_pool_snapshot.json \
  --config app/config/pipeline_candidate_pool.yaml \
  --pipeline-preset planning \
  --run-id planning-demo
```

也支持显式指定阶段：

```bash
python3 run_single_day.py \
  --input examples/input/candidate_pool_snapshot.json \
  --config app/config/pipeline_candidate_pool.yaml \
  --pipeline-stages update_holding_actions,selector,analyst \
  --run-id research-demo
```

### 工作流 A2：每日候选池模式

如果你每天自己提供候选池，只想让 AI 管买卖和仓位，可以直接切到专用配置：

```bash
python3 run_single_day.py \
  --input examples/input/candidate_pool_snapshot.json \
  --config app/config/pipeline_candidate_pool.yaml \
  --output-root outputs \
  --trade-date 2026-03-10 \
  --run-id candidate-pool-demo
```

这个模式默认做了两件事：

- `selection.source = candidate_pool`，只吃你提供的 `watchlist`
- 关闭 Wind 行情增强和新闻检索，减少外部依赖

### 工作流 B：通过 API 触发任务并查询结果

先启动服务：

```bash
python3 run_api.py
```

再触发一次同步单日任务：

```bash
curl -X POST http://127.0.0.1:8787/jobs/run-daily \
  -H 'Content-Type: application/json' \
  -d '{
    "input_file": "examples/input/daily_snapshot.json",
    "config_file": "app/config/pipeline.yaml",
    "run_id": "api-demo-20260310"
  }'
```

如果不想先落文件，也可以直接提交每日 snapshot：

```bash
curl -X POST http://127.0.0.1:8787/jobs/run-daily \
  -H 'Content-Type: application/json' \
  -d '{
    "config_file": "app/config/pipeline_candidate_pool.yaml",
    "run_id": "candidate-pool-inline-20260310",
    "snapshot": {
      "trade_date": "2026-03-10",
      "market": {"regime": "NEUTRAL"},
      "account": {"cash": 180000, "total_equity": 420000, "prev_total_equity": 418500, "initial_equity": 400000},
      "positions": [],
      "watchlist": [
        {"symbol": "002371.SZ", "name": "北方华创", "sector": "Semis", "prev_close": 421.0, "last_price": 428.0},
        {"symbol": "300308.SZ", "name": "中际旭创", "sector": "Optics", "prev_close": 155.0, "last_price": 158.4}
      ]
    }
  }'
```

如果要临时改成组合 pipeline，也可以在请求里带：

- `pipeline_preset`：如 `holding_review`、`research`、`decision`、`planning`、`execution`
- `pipeline_stages`：如 `["update_holding_actions","selector","analyst"]`

然后查询：

```bash
curl http://127.0.0.1:8787/positions/latest
curl http://127.0.0.1:8787/plans/2026-03-10
curl http://127.0.0.1:8787/fills/2026-03-10
curl "http://127.0.0.1:8787/nav?start=2026-03-01&end=2026-03-10"
curl http://127.0.0.1:8787/reports/daily/2026-03-10
```

如果要直接做东方财富自然语言选股，先设置：

```bash
export MX_APIKEY=your_api_key
```

再调用：

```bash
curl -X POST http://127.0.0.1:8787/stock-screen/query \
  -H 'Content-Type: application/json' \
  -d '{
    "keyword": "今日涨幅2%的股票",
    "market": "A股",
    "request_id": "stock-screen-demo"
  }'
```

如果要检索东方财富金融资讯：

```bash
curl -X POST http://127.0.0.1:8787/news-search/query \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "立讯精密的资讯",
    "request_id": "news-search-demo"
  }'
```

### 工作流 C：回测

```bash
python3 run_backtest.py \
  --manifest examples/input/backtest_manifest.json \
  --config app/config/pipeline.yaml
```

输出位于：

```text
outputs/backtests/<run_id>/
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

更详细的模块图见 `docs/architecture.md`。

## 目录总览

```text
ai_trader/
├── app/                      # 后端核心代码
├── docs/                     # 后端文档
├── examples/input/           # 示例输入
├── outputs/                  # 运行输出
├── run_api.py                # API 服务入口
├── run_backtest.py           # 回测入口
├── run_news_search.py        # 东方财富资讯搜索脚本入口
├── run_stock_screen.py       # 东方财富选股脚本入口
├── run_single_day.py         # 单日入口
├── BACKEND.md                # 后端详细说明
└── README.md
```

## 文档导航

- 项目总览与后端使用：`BACKEND.md`
- 后端功能架构：`docs/architecture.md`
- API 调用手册：`docs/api-mvp.md`

## 当前边界

- 默认语境为 **A 股**
- 默认执行为 **paper simulation**，不会真的下单
- API 当前为 **同步接口**
- 查询结果来自 `outputs/` 文件系统，而不是数据库
- 当前后端依赖 live LLM，请先配置 `GMN_API_KEY`
- 东方财富选股能力依赖环境变量 `MX_APIKEY`
