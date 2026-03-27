# AI Trader API 调用指南

本文面向“要调用项目”的用户，重点说明：

- 如何启动服务
- 最推荐的调用顺序
- 每个接口的用途和参数
- 如何理解“最新结果”

## 1. 启动方式

在项目根目录执行：

```bash
python3 run_api.py --host 127.0.0.1 --port 8787
```

默认行为：

- 输出根目录：`outputs`
- 默认配置：`app/config/pipeline.yaml`
- 默认输入：`examples/input/daily_snapshot.json`

如需调用东方财富选股 / 资讯搜索接口，请先设置：

```bash
export MX_APIKEY=your_api_key
```

健康检查：

```bash
curl http://127.0.0.1:8787/healthz
```

预期返回：

```json
{"status":"ok"}
```

## 2. 推荐调用顺序

如果你是第一次集成，最推荐的顺序是：

1. `GET /healthz`：确认服务活着
2. `POST /jobs/run-daily`：触发一次单日任务
3. `POST /stock-screen/query`：做一次自然语言选股并导出全量 CSV
4. `POST /news-search/query`：做一次金融资讯搜索并导出可读 Markdown
5. `GET /positions/latest`：看最新持仓
6. `GET /plans/{trade_date}`：看交易计划
7. `GET /fills/{trade_date}`：看模拟成交
8. `GET /nav?start=&end=`：看净值序列
9. `GET /reports/daily/{trade_date}`：看日报和指标

## 3. 接口总览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 健康检查 |
| `POST` | `/jobs/run-daily` | 同步触发一次单日流水线 |
| `POST` | `/stock-screen/query` | 调用东方财富自然语言选股并导出全量 CSV |
| `POST` | `/news-search/query` | 调用东方财富金融资讯搜索并导出可读 Markdown |
| `GET` | `/positions/latest` | 读取最新持仓 |
| `GET` | `/plans/{trade_date}` | 读取指定交易日交易计划 |
| `GET` | `/fills/{trade_date}` | 读取指定交易日模拟成交 |
| `GET` | `/nav?start=&end=` | 读取日级净值序列 |
| `GET` | `/reports/daily/{trade_date}` | 读取指定交易日报 |

## 4. 详细接口

### 4.1 `GET /healthz`

最轻量的可用性检测接口。

调用示例：

```bash
curl http://127.0.0.1:8787/healthz
```

返回：

```json
{
  "status": "ok"
}
```

### 4.2 `POST /jobs/run-daily`

同步执行一次单日流水线，并立刻返回任务摘要。

#### 请求体

所有字段都可选：

```json
{
  "snapshot": {
    "trade_date": "2026-03-10",
    "account": {"cash": 120000, "total_equity": 320000},
    "positions": [],
    "watchlist": []
  },
  "pipeline_preset": "planning",
  "pipeline_stages": ["update_holding_actions", "selector", "analyst"],
  "input_file": "examples/input/daily_snapshot.json",
  "config_file": "app/config/pipeline.yaml",
  "output_root": "outputs",
  "trade_date": "2026-03-10",
  "run_id": "api-demo-20260310"
}
```

#### 字段说明

| 字段 | 说明 |
| --- | --- |
| `snapshot` | 直接内联提交单日快照 JSON；传了它就不再读取 `input_file` |
| `pipeline_preset` | 可选：按预设组合阶段，如 `full` / `planning` / `research` |
| `pipeline_stages` | 可选：显式阶段列表，优先级高于 `pipeline_preset` |
| `input_file` | 单日快照 JSON 路径 |
| `config_file` | 配置文件路径 |
| `output_root` | 输出根目录 |
| `trade_date` | 交易日，必须为 `YYYY-MM-DD` |
| `run_id` | 运行 ID；不传会自动生成 |

补充规则：

- 若同时传 `snapshot` 和 `input_file`，优先使用 `snapshot`
- 若同时传 `pipeline_preset` 和 `pipeline_stages`，优先使用 `pipeline_stages`
- 若未传 `trade_date`，优先取输入快照里的 `trade_date`
- 若仍为空，回退到服务调用当天日期
- 路径既可传绝对路径，也可传相对路径

#### 调用示例

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

#### 典型成功响应

```json
{
  "job_id": "api-demo-20260310",
  "status": "completed",
  "mode": "sync",
  "run_id": "api-demo-20260310",
  "trade_date": "2026-03-10",
  "output_dir": "/abs/path/outputs/api-demo-20260310",
  "metrics": {
    "run_id": "api-demo-20260310",
    "trade_date": "2026-03-10",
    "daily_return": 0.00884,
    "cum_return": 0.2025,
    "max_drawdown": 0.06,
    "trading_fees": 35.16,
    "risk_intercept_count": 0,
    "filled_order_count": 4,
    "accepted_order_count": 5,
    "selector_failed": false,
    "risk_mode": "NEUTRAL"
  },
  "artifacts": {
    "metrics_t.json": "/abs/path/outputs/api-demo-20260310/metrics_t.json",
    "risk_report_t.md": "/abs/path/outputs/api-demo-20260310/risk_report_t.md"
  }
}
```

#### 常见错误

| 状态码 | 含义 |
| --- | --- |
| `400` | `trade_date` 非法、请求体不是 JSON object、JSON 格式不合法 |
| `404` | 输入文件或配置文件不存在 |
| `500` | 未预期内部错误 |

### 4.2.1 `POST /stock-screen/query`

调用东方财富选股接口，支持自然语言条件，自动翻页拉取全量结果，并导出：

- 中文列名 CSV
- 字段说明 JSON
- 原始分页返回 JSON

#### 请求体

`keyword` 必填，其余字段可选：

```json
{
  "keyword": "今日涨幅2%的股票",
  "market": "A股",
  "page_size": 100,
  "fetch_all": true,
  "include_rows": false,
  "preview_limit": 20,
  "config_file": "app/config/pipeline.yaml",
  "output_root": "outputs",
  "request_id": "stock-screen-demo"
}
```

#### 字段说明

| 字段 | 说明 |
| --- | --- |
| `keyword` | 自然语言选股条件 |
| `market` | 可选：`A股` / `港股` / `美股`；若 keyword 未显式带市场，会自动前置 |
| `page_size` | 单页拉取条数，默认取配置里的 `stock_screen.default_page_size` |
| `fetch_all` | 是否自动翻页拉全量，默认 `true` |
| `include_rows` | 是否在接口响应内返回全量中文行数据，默认 `false` |
| `preview_limit` | 预览行数，默认 `20` |
| `config_file` | 配置文件路径，可覆盖默认配置 |
| `output_root` | 输出根目录，默认 `outputs` |
| `request_id` | 自定义导出目录名；不传则自动生成 |

#### 调用示例

```bash
curl -X POST http://127.0.0.1:8787/stock-screen/query \
  -H 'Content-Type: application/json' \
  -d '{
    "keyword": "今日涨幅2%的股票",
    "market": "A股",
    "page_size": 100,
    "fetch_all": true,
    "request_id": "stock-screen-demo"
  }'
```

#### 典型成功响应

```json
{
  "request_id": "stock-screen-demo",
  "keyword": "今日涨幅2%的股票",
  "effective_keyword": "A股今日涨幅2%的股票",
  "market": "A股",
  "total": 128,
  "row_count": 128,
  "page_size": 100,
  "pages_fetched": 2,
  "parser_text": "今日涨幅在[1.5%,2.5%]之间",
  "columns": [
    {
      "index": 1,
      "key": "SECURITY_CODE",
      "csv_header": "股票代码",
      "title": "股票代码"
    }
  ],
  "preview_rows": [
    {
      "股票代码": "600519",
      "股票简称": "贵州茅台"
    }
  ],
  "artifacts": {
    "directory": "/abs/path/outputs/stock_screen/stock-screen-demo",
    "csv": "/abs/path/outputs/stock_screen/stock-screen-demo/stock_screen_result.csv",
    "description_json": "/abs/path/outputs/stock_screen/stock-screen-demo/stock_screen_description.json",
    "raw_json": "/abs/path/outputs/stock_screen/stock-screen-demo/stock_screen_raw.json"
  }
}
```

#### 常见错误

| 状态码 | 含义 |
| --- | --- |
| `400` | `keyword` 缺失、`market` 非法、结果页数超过 `max_pages` |
| `500` | 未配置 `MX_APIKEY` |
| `502` | 上游东方财富/妙想接口不可用或返回异常 |
| `504` | 上游接口超时 |

### 4.2.2 `POST /news-search/query`

调用东方财富资讯搜索接口，返回金融相关资讯条目，并导出：

- 标准化结果 JSON
- 可直接阅读的 Markdown
- 原始返回 JSON

#### 请求体

`query` 必填，其余字段可选：

```json
{
  "query": "立讯精密的资讯",
  "size": 12,
  "start_date": "2026-03-01",
  "end_date": "2026-03-16",
  "include_items": false,
  "preview_limit": 6,
  "request_id": "news-search-demo"
}
```

#### 字段说明

| 字段 | 说明 |
| --- | --- |
| `query` | 自然语言资讯问题，如个股资讯、板块新闻、政策解读 |
| `size` | 请求结果条数，默认取配置里的 `news_search.default_size` |
| `start_date` | 可选起始日期，透传给上游接口 |
| `end_date` | 可选结束日期，透传给上游接口 |
| `child_search_type` | 可选子搜索类型，透传给上游接口 |
| `include_items` | 是否在响应内返回全量标准化资讯项，默认 `false` |
| `preview_limit` | 预览资讯条数，默认 `6` |
| `excerpt_chars` | 预览摘要长度，默认 `240` |
| `request_id` | 自定义导出目录名；不传则自动生成 |

#### 调用示例

```bash
curl -X POST http://127.0.0.1:8787/news-search/query \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "立讯精密的资讯",
    "size": 12,
    "request_id": "news-search-demo"
  }'
```

#### 典型成功响应

```json
{
  "request_id": "news-search-demo",
  "query": "立讯精密的资讯",
  "protocol_type": "SEARCH_NEWS",
  "trace_id": "trace-id-demo",
  "search_id": "search-id-demo",
  "count": 14,
  "preview_items": [
    {
      "index": 1,
      "title": "立讯精密:关于股份回购进展情况的公告",
      "date": "2026-03-03 00:18:13",
      "information_type": "NOTICE",
      "attach_type": "PDF",
      "jump_url": "https://pdf.example.com/notice.pdf",
      "trunk_excerpt": "立讯精密工业股份有限公司关于股份回购进展情况的公告……"
    }
  ],
  "artifacts": {
    "directory": "/abs/path/outputs/news_search/news-search-demo",
    "result_json": "/abs/path/outputs/news_search/news-search-demo/news_search_result.json",
    "result_markdown": "/abs/path/outputs/news_search/news-search-demo/news_search_result.md",
    "raw_json": "/abs/path/outputs/news_search/news-search-demo/news_search_raw.json"
  }
}
```

#### 常见错误

| 状态码 | 含义 |
| --- | --- |
| `400` | `query` 缺失 |
| `500` | 未配置 `MX_APIKEY` |
| `502` | 上游东方财富/妙想接口不可用或返回异常 |
| `504` | 上游接口超时 |

### 4.3 `GET /positions/latest`

返回当前可发现产物中的“最新持仓”。

调用示例：

```bash
curl http://127.0.0.1:8787/positions/latest
```

典型返回结构：

```json
{
  "trade_date": "2026-03-10",
  "run_id": "api-demo-20260310",
  "source": "single_day",
  "output_dir": "/abs/path/outputs/api-demo-20260310",
  "count": 4,
  "positions": [
    {
      "symbol": "600519.SH",
      "name": "贵州茅台",
      "weight": "0.0824"
    }
  ]
}
```

字段说明：

- `source` 可能为 `single_day`
- 也可能为 `backtest:<backtest_run_id>`

### 4.4 `GET /plans/{trade_date}`

返回指定交易日的最新 `trade_plan_t.csv`。

调用示例：

```bash
curl http://127.0.0.1:8787/plans/2026-03-10
```

典型返回结构：

```json
{
  "trade_date": "2026-03-10",
  "run_id": "api-demo-20260310",
  "source": "single_day",
  "output_dir": "/abs/path/outputs/api-demo-20260310",
  "count": 5,
  "plans": [
    {
      "symbol": "601899.SH",
      "action": "BUILD",
      "status": "ACCEPTED",
      "target_weight": "0.05115127692",
      "w_final": "0.05115127692"
    }
  ]
}
```

常见错误：

- `400`：`trade_date` 不是 `YYYY-MM-DD`
- `404`：没有找到该交易日计划

### 4.5 `GET /fills/{trade_date}`

返回指定交易日的最新 `sim_fill_t.csv`。

调用示例：

```bash
curl http://127.0.0.1:8787/fills/2026-03-10
```

典型字段：

- `order_id`
- `symbol`
- `action`
- `planned_price`
- `fill_price`
- `quantity`
- `filled_amount`
- `total_fee`
- `status`
- `note`

### 4.6 `GET /nav?start=&end=`

返回按交易日聚合后的净值序列。

调用示例：

```bash
curl "http://127.0.0.1:8787/nav?start=2026-03-01&end=2026-03-10"
```

参数：

| 参数 | 说明 |
| --- | --- |
| `start` | 起始交易日，可选 |
| `end` | 结束交易日，可选 |

规则：

- `start` / `end` 若提供，必须是 `YYYY-MM-DD`
- 若两者同时提供，则必须满足 `start <= end`

典型返回结构：

```json
{
  "start": "2026-03-01",
  "end": "2026-03-10",
  "count": 6,
  "nav": [
    {
      "trade_date": "2026-03-10",
      "cash": "25123.44",
      "market_value": "98654.32",
      "total_equity": "123777.76",
      "daily_return": "0.0088",
      "cum_return": "0.0312",
      "run_id": "api-demo-20260310",
      "source": "single_day",
      "output_dir": "/abs/path/outputs/api-demo-20260310"
    }
  ]
}
```

### 4.7 `GET /reports/daily/{trade_date}`

返回指定交易日的日报内容和结构化指标。

调用示例：

```bash
curl http://127.0.0.1:8787/reports/daily/2026-03-10
```

典型返回结构：

```json
{
  "trade_date": "2026-03-10",
  "run_id": "api-demo-20260310",
  "source": "single_day",
  "output_dir": "/abs/path/outputs/api-demo-20260310",
  "metrics": {
    "daily_return": 0.00884,
    "cum_return": 0.2025,
    "max_drawdown": 0.06
  },
  "risk_report_markdown": "# AI Trader Risk Report\n..."
}
```

这个接口适合：

- 上游展示层展示日报
- 自动生成通知
- 外部系统抓取 Markdown 报告

## 5. “最新结果”到底怎么判定

这是调用方最容易忽略的一点。

服务会同时扫描：

- `outputs/<run_id>/`
- `outputs/backtests/<run_id>/days/<trade_date>/`

然后：

1. 为每个目录识别出 `trade_date`
2. 对同一个 `trade_date` 聚合候选结果
3. 按目录更新时间选择“最新”的一份

所以：

- `GET /positions/latest` 返回的是全局最新一次产物
- `GET /plans/{trade_date}` 返回的是该日期下更新时间最新的产物
- 如果你先跑了回测，又跑了同一天的单日任务，通常会返回单日任务结果

## 6. 返回值类型注意事项

### 6.1 CSV 接口的数值多数是字符串

以下接口返回的数据主体来自 CSV：

- `/positions/latest`
- `/plans/{trade_date}`
- `/fills/{trade_date}`
- `/nav`

因此像 `weight`、`fill_price`、`total_equity` 这些字段，客户端通常要自行转成数字。

### 6.2 JSON 接口的指标保留原生数值

`/reports/daily/{trade_date}` 中的 `metrics` 来自 JSON，因此数值字段仍是数值类型。
