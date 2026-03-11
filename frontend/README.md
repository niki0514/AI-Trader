# AI Trader Frontend

前端使用 `React + TypeScript + Vite`，主要作用是把后端产物做成更容易浏览的工作台。

## 1. 你能在前端看到什么

当前工作台主要包含这些视图：

- `总览`：关键指标、阶段状态、净值摘要
- `日历`：按交易日浏览结果
- `持仓`：最新持仓明细
- `计划`：风控后交易计划
- `成交`：模拟成交结果
- `报告`：Markdown 风险日报

它不是独立业务系统，而是 **后端 API 的可视化壳层**。

## 2. 本地开发

### 2.1 先启动后端 API

在项目根目录执行：

```bash
python3 backend/run_api.py --host 127.0.0.1 --port 8787
```

### 2.2 再启动前端开发服务器

```bash
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

## 3. 开发环境代理

Vite 开发环境已把以下路径代理到 `http://127.0.0.1:8787`：

- `/healthz`
- `/jobs`
- `/positions`
- `/plans`
- `/fills`
- `/nav`
- `/reports`

所以本地联调时，通常不需要手动改接口地址，只要保证后端 API 已启动即可。

## 4. 生产构建与静态托管

构建命令：

```bash
cd frontend
npm run build
```

构建产物输出到：

```text
frontend/dist/
```

后端 API 默认会直接托管这个目录，因此常见发布方式是：

1. 先执行 `npm run build`
2. 再启动 `python3 backend/run_api.py`
3. 通过后端同一地址访问前端页面和 API

## 5. 常用脚本

| 命令 | 作用 |
| --- | --- |
| `npm run dev` | 启动开发服务器 |
| `npm run build` | TypeScript 检查并构建 |
| `npm run preview` | 本地预览构建产物 |

## 6. 常见问题

### 6.1 页面打开了但没有数据

先检查：

- 后端是否已启动：`python3 backend/run_api.py`
- 后端是否在 `127.0.0.1:8787`
- 是否已经至少跑过一次单日任务或回测

### 6.2 开发环境接口报错

优先检查：

- Vite dev server 是否运行在 `5173`
- 后端 API 是否运行在 `8787`
- 浏览器访问 `http://127.0.0.1:8787/healthz` 是否正常

### 6.3 静态托管打不开

如果你希望由后端直接托管前端页面，请确认：

1. 已执行 `npm run build`
2. `frontend/dist/` 目录存在
3. 启动 `backend/run_api.py` 时没有改错 `--frontend-dir`

## 7. 相关阅读

- 项目总览：`README.md`
- 后端说明：`backend/README.md`
- API 调用指南：`backend/docs/api-mvp.md`
