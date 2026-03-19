# Code-Patch

## 配置端口（.env）

`.env` 在项目根目录。推荐先复制一份示例：

```bash
cp .env.example .env
```

常用配置项：

- `FRONTEND_PORT`：前端端口（默认 `5173`，如果被占用就改成 `5174/5175/...`）
- `BACKEND_HOST` / `APP_HOST`：后端监听地址（推荐 `127.0.0.1`）
- `BACKEND_PORT` / `APP_PORT`：后端端口（默认 `8000`）

修改端口后，需要把前后端都重启一次（后端的 CORS 白名单依赖 `FRONTEND_PORT`）。

## 启动

### 后端

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install fastapi "uvicorn[standard]" pydantic python-dotenv curl-cffi

cd backend
./.venv/bin/python main.py
```

后端接口文档：`http://127.0.0.1:8000/docs`（端口以 `.env` 为准）

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 重启命令（分别）

### 重启后端

```bash
# 停止占用端口的进程（把 8000 换成你的 BACKEND_PORT）
PID=$(lsof -tiTCP:8000 -sTCP:LISTEN) && kill $PID

# 重新启动
cd backend
./.venv/bin/python main.py
```

### 重启前端

```bash
# 停止占用端口的进程（把 5174 换成你的 FRONTEND_PORT，默认 5173）
PID=$(lsof -tiTCP:5174 -sTCP:LISTEN) && kill $PID

cd frontend
npm run dev
```

### 核心功能
- 批量注册 — 代理池 + 可调并发，实时 WebSocket 进度推送，支持暂停 / 继续

- 账号管理 — 多维度筛选（关键词 / 状态 / 存活），支持 CSV 导入导出

- 存活检测 — 一键批量检活，自动标记存活 / 死亡状态

- Token 自动刷新 — 后台定时刷新 refresh_token，保持账号活跃

- 任务中心 — 支持单次 / 每日定时任务，覆盖注册、检活、清理三种任务类型

- 代理检测 — 注册前可预先检测代理可用性及出口 IP
