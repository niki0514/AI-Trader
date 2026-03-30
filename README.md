# AI Trader

一个面向 **A 股日级交易决策** 的本地化交易决策项目，用来把单日交易快照转成可追溯、可回放、可查询的交易结果。

当前仓库聚焦策略流水线与 API 服务，工作台界面已移除。项目核心设计是：

- 文件驱动：所有运行结果都会落盘到 `outputs/`
- 单日、API、回测共用一条流水线
- 输出可审计：既有业务文件，也有阶段级调试产物
- 支持组合式 pipeline：可以跑完整链路，也可以只跑部分阶段

项目目前不包含数据库、消息队列、真实券商交易接口或用户系统，默认定位是研发验证和策略实验环境。

## 核心能力

- 单日运行：输入一份 `snapshot`，输出持仓动作、候选池、AI 研判、交易计划、模拟成交、净值和风险报告
- 状态化回测：按 manifest 逐日运行，并把组合状态沿时间推进
- HTTP API：触发单日任务、读取持仓/计划/成交/NAV/日报
- 东方财富能力：支持自然语言选股和资讯搜索
- 阶段编排：支持 `pipeline.preset` 和 `pipeline.stages` 两种组合方式

## 快速开始

以下命令默认都在项目根目录执行。

### 1. 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

`requirements.txt` 当前包含：

- `PyYAML`：加载配置
- `PyMySQL`、`SQLAlchemy`：Wind / MySQL 相关访问
- `cryptography`：底层依赖

### 2. 配置环境变量

最常见的是这两个：

```bash
export GMN_API_KEY=your_api_key
export MX_APIKEY=your_api_key
```

如果需要接 Wind / MySQL 数据，也可以设置：

```bash
export MYSQL_SERVER_URL=10.100.0.28:3306
export WIND_DB_USER=wind_admin
export WIND_DB_PASS=your_password
export WIND_DB_NAME=winddb
```

或者直接覆盖连接串：

```bash
export DB_WIND_URL='mysql+pymysql://user:pass@host:3306/winddb?charset=utf8mb4'
```

### 3. 跑一个单日样例

```bash
python3 run_single_day.py --run-id demo-single
```

成功后可在 `outputs/demo-single/` 看到：

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
- `final_payload.json`
- `stages/*.json`

### 4. 启动 API

```bash
python3 run_api.py --host 127.0.0.1 --port 8787
```

健康检查：

```bash
curl http://127.0.0.1:8787/healthz
```

### 5. 运行测试

```bash
python3 -m unittest discover -s tests
```

## 常见工作流

### 工作流 A：跑完整单日流水线

```bash
python3 run_single_day.py \
  --input examples/input/daily_snapshot.json \
  --config app/config/pipeline.yaml \
  --output-root outputs \
  --trade-date 2026-03-10 \
  --run-id demo-single
```

适合：

- 验证一份输入快照能否跑通
- 查看完整 7 段流水线输出
- 对比参数调整前后的结果差异

### 工作流 A2：候选池模式

如果你每天自己提供候选池，只想让系统负责买卖、仓位和风控，可使用：

```bash
python3 run_single_day.py \
  --input examples/input/candidate_pool_snapshot.json \
  --config app/config/pipeline_candidate_pool.yaml \
  --output-root outputs \
  --trade-date 2026-03-10 \
  --run-id candidate-pool-demo
```

这个模式默认：

- `selection.source = candidate_pool`
- 关闭 Wind 行情增强
- 关闭新闻检索

### 工作流 A3：只跑部分阶段

按预设运行：

```bash
python3 run_single_day.py \
  --input examples/input/candidate_pool_snapshot.json \
  --config app/config/pipeline_candidate_pool.yaml \
  --pipeline-preset planning \
  --run-id planning-demo
```

按显式阶段运行：

```bash
python3 run_single_day.py \
  --input examples/input/candidate_pool_snapshot.json \
  --config app/config/pipeline_candidate_pool.yaml \
  --pipeline-stages update_holding_actions,selector,analyst \
  --run-id research-demo
```

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

也可以直接内联提交 snapshot：

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

查询结果：

```bash
curl http://127.0.0.1:8787/positions/latest
curl http://127.0.0.1:8787/plans/2026-03-10
curl http://127.0.0.1:8787/fills/2026-03-10
curl "http://127.0.0.1:8787/nav?start=2026-03-01&end=2026-03-10"
curl http://127.0.0.1:8787/reports/daily/2026-03-10
```

### 工作流 C：回测

```bash
python3 run_backtest.py \
  --manifest examples/input/backtest_manifest.json \
  --config app/config/pipeline.yaml
```

输出目录：

```text
outputs/backtests/<run_id>/
```

其中通常会包含：

- `backtest_nav.csv`
- `backtest_fills.csv`
- `backtest_summary.json`
- `walk_forward_report.md`
- `days/<trade_date>/...`

### 工作流 D：东方财富自然语言选股

```bash
export MX_APIKEY=your_api_key

python3 run_stock_screen.py \
  --keyword "今日涨幅2%的股票" \
  --market A股 \
  --request-id stock-screen-demo
```

输出目录：

```text
outputs/stock_screen/stock-screen-demo/
```

### 工作流 E：东方财富资讯搜索

```bash
export MX_APIKEY=your_api_key

python3 run_news_search.py \
  --query "立讯精密的资讯" \
  --request-id news-search-demo
```

输出目录：

```text
outputs/news_search/news-search-demo/
```

## 项目如何工作

项目的三种主要入口：

- `run_single_day.py`
- `run_backtest.py`
- `run_api.py`

最终都会复用同一条流水线：

1. `update_holding_actions`
2. `selector`
3. `analyst`
4. `decider`
5. `risk_guard`
6. `executor`
7. `reporter`

可以把它理解成：

```text
输入快照 -> 持仓复核 -> 候选筛选 -> AI研判 -> 订单草案
         -> 风控拦截 -> 模拟执行 -> 指标/报告/查询产物
```

更细的执行机制见 `docs/architecture.md`。

## 输出文件说明

单日输出目录结构：

```text
outputs/<run_id>/
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
```

主要文件含义：

| 文件 | 用途 |
| --- | --- |
| `holding_actions_t.csv` | 对现有持仓的动作建议 |
| `tech_candidates_t.csv` | 技术筛选后的候选池 |
| `ai_insights_t.csv` | LLM 研判结果 |
| `orders_candidate_t.csv` | 风控前订单草案 |
| `trade_plan_t.csv` | 风控后的正式计划 |
| `sim_fill_t.csv` | 模拟成交明细 |
| `positions_t.csv` | 日终持仓 |
| `nav_t.csv` | 日终净值 |
| `metrics_t.json` | 结构化指标摘要 |
| `risk_report_t.md` | 可读风险日报 |
| `final_payload.json` | 全链路累计结果快照 |
| `stages/*.json` | 每个阶段的调试快照、输出增量与 artifact manifest |

## 目录结构

```text
AI-Trader/
├── app/
│   ├── api/                  # HTTP API
│   ├── components/           # 各业务阶段
│   ├── pipeline/             # 编排、artifact、输出契约
│   ├── config/               # 配置与配置加载器
│   ├── adapters/             # 存储、LLM、文件等适配层
│   └── domain/               # 枚举与领域定义
├── docs/                     # 架构、API、规划文档
├── examples/input/           # 示例输入
├── outputs/                  # 本地运行产物
├── tests/                    # 单测与集成测试
├── run_single_day.py         # 单日入口
├── run_backtest.py           # 回测入口
├── run_api.py                # API 入口
├── run_stock_screen.py       # 东方财富选股入口
├── run_news_search.py        # 东方财富资讯搜索入口
├── requirements.txt
└── README.md
```

## 配置与环境

默认主配置：

```text
app/config/pipeline.yaml
```

常见配置项：

| 配置项 | 作用 |
| --- | --- |
| `pipeline.preset` | 选择内置阶段预设 |
| `pipeline.stages` | 显式指定阶段列表 |
| `selection.source` | `candidate_pool` / `snapshot` / `stock_screen` |
| `selection.top_n` | 候选池保留数量 |
| `decision.build_score_floor` | 新开仓阈值 |
| `decision.add_score_floor` | 加仓阈值 |
| `risk.mode_caps.*` | 风险模式下组合总仓位上限 |
| `risk_rules.single_stock_cap.value` | 单票仓位上限 |
| `execution.slippage_bps` | 模拟执行滑点 |
| `stock_screen.default_page_size` | 选股默认分页大小 |
| `news_search.default_size` | 资讯检索默认返回条数 |
| `llm.enable_live` | 是否启用 live LLM |

如果希望 `selector` 直接从东方财富自然语言选股拉候选池，可在配置中使用：

```yaml
selection:
  source: stock_screen
  stock_screen:
    keyword: 今日涨幅2%的股票
    market: A股
    page_size: 60
    fetch_all: false
```

也可以在 `snapshot` 中临时覆盖：

```json
{
  "selector_query": {
    "source": "stock_screen",
    "keyword": "成交额前100且今日上涨的A股",
    "market": "A股"
  }
}
```

## API 结果读取语义

API 本身不依赖数据库，而是扫描 `outputs/` 中已有产物。

扫描位置：

- 单日运行：`outputs/<run_id>/`
- 回测逐日：`outputs/backtests/<backtest_run_id>/days/<trade_date>/`

“最新结果”的定义：

- 对同一个 `trade_date`，单日和回测日结果都会被纳入候选
- API 会按目录更新时间选出最新那一份

因此：

- `GET /positions/latest` 返回的是当前可发现的全局最新结果
- `GET /plans/{trade_date}`、`GET /fills/{trade_date}`、`GET /reports/daily/{trade_date}` 返回的是该日最新结果
- `GET /nav` 会按日期去重后返回每个交易日最新的一份

## 文档导航

- 架构说明：`docs/architecture.md`
- API 调用手册：`docs/api-mvp.md`
- IO 示例：`docs/pipeline-io-demo.md`
- 产品规划：`docs/product-roadmap.md`

建议阅读顺序：

1. `README.md`
2. `docs/architecture.md`
3. `docs/api-mvp.md`
4. `docs/product-roadmap.md`

## 当前边界

- 默认语境为 **A 股**
- 默认执行为 **paper simulation**，不会真实下单
- API 当前为 **同步接口**
- 查询结果来自 `outputs/` 文件系统，而不是数据库
- 当前没有工作台界面
- 当前没有用户体系、权限控制、任务队列与异步状态机
- 当前没有多账户、多策略、多租户隔离
