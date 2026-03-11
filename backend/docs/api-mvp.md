# AI Trader API 调用指南

本文面向“要调用项目”的用户，重点说明：

- 如何启动服务
- 最推荐的调用顺序
- 每个接口的用途和参数
- 如何理解“最新结果”

## 1. 启动方式

在项目根目录执行：

```bash
python3 backend/run_api.py --host 127.0.0.1 --port 8787
```

默认行为：

- 输出根目录：`backend/outputs`
- 默认配置：`backend/app/config/pipeline.yaml`
- 默认输入：`backend/examples/input/daily_snapshot.json`
- 若 `frontend/dist/` 存在，会顺便托管前端静态文件

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
3. `GET /positions/latest`：看最新持仓
4. `GET /plans/{trade_date}`：看交易计划
5. `GET /fills/{trade_date}`：看模拟成交
6. `GET /nav?start=&end=`：看净值序列
7. `GET /reports/daily/{trade_date}`：看日报和指标

## 3. 接口总览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 健康检查 |
| `POST` | `/jobs/run-daily` | 同步触发一次单日流水线 |
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
  "input_file": "backend/examples/input/daily_snapshot.json",
  "config_file": "backend/app/config/pipeline.yaml",
  "output_root": "backend/outputs",
  "trade_date": "2026-03-10",
  "run_id": "api-demo-20260310"
}
```

#### 字段说明

| 字段 | 说明 |
| --- | --- |
| `input_file` | 单日快照 JSON 路径 |
| `config_file` | 配置文件路径 |
| `output_root` | 输出根目录 |
| `trade_date` | 交易日，必须为 `YYYY-MM-DD` |
| `run_id` | 运行 ID；不传会自动生成 |

补充规则：

- 若未传 `trade_date`，优先取输入快照里的 `trade_date`
- 若仍为空，回退到服务调用当天日期
- 路径既可传绝对路径，也可传相对路径

#### 调用示例

```bash
curl -X POST http://127.0.0.1:8787/jobs/run-daily \
  -H 'Content-Type: application/json' \
  -d '{
    "input_file": "backend/examples/input/daily_snapshot.json",
    "config_file": "backend/app/config/pipeline.yaml",
    "run_id": "api-demo-20260310"
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
  "output_dir": "/abs/path/backend/outputs/api-demo-20260310",
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
    "analyst_failed": false,
    "selector_failed": false,
    "risk_mode": "NEUTRAL"
  },
  "artifacts": {
    "metrics_t.json": "/abs/path/backend/outputs/api-demo-20260310/metrics_t.json",
    "risk_report_t.md": "/abs/path/backend/outputs/api-demo-20260310/risk_report_t.md"
  }
}
```

#### 常见错误

| 状态码 | 含义 |
| --- | --- |
| `400` | `trade_date` 非法、请求体不是 JSON object、JSON 格式不合法 |
| `404` | 输入文件或配置文件不存在 |
| `500` | 未预期内部错误 |

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
  "output_dir": "/abs/path/backend/outputs/api-demo-20260310",
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
  "output_dir": "/abs/path/backend/outputs/api-demo-20260310",
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
      "output_dir": "/abs/path/backend/outputs/api-demo-20260310"
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
  "output_dir": "/abs/path/backend/outputs/api-demo-20260310",
  "metrics": {
    "daily_return": 0.00884,
    "cum_return": 0.2025,
    "max_drawdown": 0.06
  },
  "risk_report_markdown": "# AI Trader Risk Report\n..."
}
```

这个接口适合：

- 前端展示日报页面
- 自动生成通知
- 外部系统抓取 Markdown 报告

## 5. “最新结果”到底怎么判定

这是调用方最容易忽略的一点。

服务会同时扫描：

- `backend/outputs/<run_id>/`
- `backend/outputs/backtests/<run_id>/days/<trade_date>/`

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

## 7. 前端如何调用这些接口

本仓库前端默认把以下路径代理到 `http://127.0.0.1:8787`：

- `/healthz`
- `/jobs`
- `/positions`
- `/plans`
- `/fills`
- `/nav`
- `/reports`

因此开发前端时，只要先启动 `backend/run_api.py` 即可。

更多前端说明见 `frontend/README.md`。
