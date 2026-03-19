import asyncio
import base64
import csv
import io
import json
import logging
import os
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from register import run as _register_account, check_alive as _check_alive, check_proxy as _check_proxy
from database import get_conn, init_db

# .env 在根目录（backend/ 的上一级）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))


def _env_first(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return default

# ---------------------------------------------------------------------------
# 读取系统代理
# ---------------------------------------------------------------------------

def _get_system_proxy() -> str:
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    try:
        import winreg
        reg_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        enabled, _ = winreg.QueryValueEx(reg_key, "ProxyEnable")
        if enabled:
            server, _ = winreg.QueryValueEx(reg_key, "ProxyServer")
            server = server.strip()
            if "=" in server:
                for part in server.split(";"):
                    part = part.strip()
                    if part.startswith("http="):
                        server = part[5:]
                        break
                    if part.startswith("https="):
                        server = part[6:]
            if server and "://" not in server:
                server = "http://" + server
            return server
    except Exception:
        pass
    return ""

# ---------------------------------------------------------------------------
# App 初始化
# ---------------------------------------------------------------------------

app = FastAPI(title="Account Registrar API")

FRONTEND_PORT = int(_env_first("FRONTEND_PORT", default="5173"))
FRONTEND_ORIGINS = os.getenv("FRONTEND_ORIGINS", "").strip()
if FRONTEND_ORIGINS:
    allow_origins = [o.strip() for o in FRONTEND_ORIGINS.split(",") if o.strip()]
else:
    allow_origins = [
        f"http://localhost:{FRONTEND_PORT}",
        f"http://127.0.0.1:{FRONTEND_PORT}",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=1000)

# session_id -> list[asyncio.Queue]（每个 WS 客户端一个队列）
active_ws: dict[int, list[asyncio.Queue]] = defaultdict(list)

# session_id -> asyncio.Event（用于暂停/恢复）
session_pause_events: dict[int, asyncio.Event] = {}

# check_session_id -> list[asyncio.Queue]
active_check_ws: dict[str, list[asyncio.Queue]] = defaultdict(list)


@app.on_event("startup")
async def startup():
    init_db()
    # 修正重启后遗留的运行中/已暂停状态
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET status='done' WHERE status IN ('running','paused','importing')")
    asyncio.create_task(_auto_refresh_loop())
    asyncio.create_task(_schedule_loop())


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


async def _broadcast(session_id: int, msg: dict):
    for q in list(active_ws.get(session_id, [])):
        try:
            await q.put(msg)
        except Exception:
            pass



def _build_account_where(
    session_id: Optional[int],
    status: Optional[str],
    search: Optional[str],
    alive: Optional[str] = None,
) -> tuple[str, list]:
    conditions: list[str] = []
    params: list = []
    if session_id is not None:
        conditions.append("session_id = ?")
        params.append(session_id)
    if status == "success":
        conditions.append("error IS NULL")
    elif status == "failed":
        conditions.append("error IS NOT NULL")
    if search:
        kw = f"%{search}%"
        conditions.append("(email LIKE ? OR account_id LIKE ?)")
        params.extend([kw, kw])
    if alive == "unchecked":
        conditions.append("alive IS NULL")
    elif alive in ("alive", "dead", "error"):
        conditions.append("alive = ?")
        params.append(alive)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params


# ---------------------------------------------------------------------------
# 代理预检
# ---------------------------------------------------------------------------

async def _filter_proxies(proxy_list: list[str], concurrency: int = 10) -> list[str]:
    """并发检测代理可用性，返回可用的代理列表。相同地址只检测一次。"""
    unique = list(dict.fromkeys(proxy_list))  # 去重保序
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(concurrency)
    checked = {}  # proxy -> (ok, reason)

    async def _test(proxy: str):
        async with sem:
            ok, reason = await loop.run_in_executor(executor, _check_proxy, proxy)
            checked[proxy] = (ok, reason)
            if not ok:
                logger.info("代理不可用: %s -> %s", proxy, reason)

    await asyncio.gather(*[_test(p) for p in unique])
    # 按原始列表顺序返回可用的（保留重复项，因为多个相同代理 = 代理池轮换出口）
    return [p for p in proxy_list if checked.get(p, (False,))[0]]


# ---------------------------------------------------------------------------
# 注册后台任务
# ---------------------------------------------------------------------------

async def _run_session(session_id: int, proxy_list: list[str], target: int, concurrency: int):
    """持续注册直到 **成功数** 达到 target，失败会自动重试。"""
    # 预检代理
    valid_proxies = await _filter_proxies(proxy_list)
    if not valid_proxies:
        logger.warning("session %s: 所有代理均不可用", session_id)
        with get_conn() as conn:
            conn.execute("UPDATE sessions SET status='failed' WHERE id=?", (session_id,))
        return
    logger.info("session %s: %d/%d 代理可用", session_id, len(valid_proxies), len(proxy_list))
    proxy_list = valid_proxies

    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(concurrency)

    # 暂停控制：Event set = 运行中，clear = 暂停
    pause_event = asyncio.Event()
    pause_event.set()
    session_pause_events[session_id] = pause_event

    # 用 asyncio 锁保护计数器，避免并发竞争
    lock = asyncio.Lock()
    counters = {"success": 0, "failed": 0, "consecutive_fails": 0}
    max_consecutive_fails = max(target * 3, 50)

    async def _do_one():
        # 随机启动延迟，避免并发请求同时发出
        await asyncio.sleep(random.uniform(0.2, 1.5))
        proxy = random.choice(proxy_list)
        t0 = time.time()
        try:
            result_str = await loop.run_in_executor(executor, _register_account, proxy)
            elapsed = round(time.time() - t0, 1)

            if result_str is None:
                raise RuntimeError("Account creation failed (server rejected)")

            data = json.loads(result_str)
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO accounts
                       (session_id, created_at, email, account_id, refresh_token,
                        id_token, access_token, expired, last_refresh, proxy_used,
                        auto_refresh, exit_ip)
                       VALUES (?,?,?,?,?,?,?,?,?,?,1,?)""",
                    (
                        session_id, _now(),
                        data.get("email"), data.get("account_id"),
                        data.get("refresh_token"), data.get("id_token"),
                        data.get("access_token"), data.get("expired"),
                        data.get("last_refresh"), proxy,
                        data.get("exit_ip"),
                    ),
                )
                conn.execute(
                    "UPDATE sessions SET success = success + 1 WHERE id = ?",
                    (session_id,),
                )

            async with lock:
                counters["success"] += 1
                counters["consecutive_fails"] = 0
                idx = counters["success"]

            await _broadcast(session_id, {
                "type": "success",
                "index": idx,
                "email": data.get("email"),
                "proxy": proxy,
                "elapsed": elapsed,
            })

            # 成功后随机等待
            await asyncio.sleep(random.uniform(3, 8))

        except Exception as exc:
            elapsed = round(time.time() - t0, 1)
            err_msg = str(exc)
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO accounts
                       (session_id, created_at, proxy_used, error)
                       VALUES (?,?,?,?)""",
                    (session_id, _now(), proxy, err_msg),
                )
                conn.execute(
                    "UPDATE sessions SET failed = failed + 1 WHERE id = ?",
                    (session_id,),
                )

            async with lock:
                counters["failed"] += 1
                counters["consecutive_fails"] += 1

            await _broadcast(session_id, {
                "type": "failed",
                "error": err_msg,
                "proxy": proxy,
                "elapsed": elapsed,
            })

            # 失败后短暂等待再重试
            await asyncio.sleep(random.uniform(1, 3))

    async def _worker():
        while True:
            # 暂停时在此等待
            await pause_event.wait()
            async with lock:
                done = counters["success"] >= target
                stopped = counters["consecutive_fails"] >= max_consecutive_fails
            if done or stopped:
                break
            async with sem:
                await pause_event.wait()
                async with lock:
                    if counters["success"] >= target:
                        break
                await _do_one()

    workers = [asyncio.create_task(_worker()) for _ in range(min(concurrency, target))]
    await asyncio.gather(*workers)
    session_pause_events.pop(session_id, None)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT success, failed FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        conn.execute(
            "UPDATE sessions SET status = 'done' WHERE id = ?", (session_id,)
        )

    await _broadcast(session_id, {
        "type": "done",
        "success": row["success"] if row else 0,
        "failed": row["failed"] if row else 0,
        "total": target,
    })


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/sessions/{session_id}")
async def ws_session(websocket: WebSocket, session_id: int):
    await websocket.accept()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, success, failed, requested FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

    if row and row["status"] == "done":
        await websocket.send_json({
            "type": "done",
            "success": row["success"],
            "failed": row["failed"],
            "total": row["requested"],
        })
        await websocket.close()
        return

    q: asyncio.Queue = asyncio.Queue()
    active_ws[session_id].append(q)

    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=120)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(msg)
            if msg.get("type") == "done":
                break
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        try:
            active_ws[session_id].remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# 系统代理
# ---------------------------------------------------------------------------

def _get_proxy_pool() -> str:
    """从 .env PROXY_POOL 读取代理池，支持逗号或换行分隔。"""
    raw = os.getenv("PROXY_POOL", "").strip()
    if not raw:
        # 回退到系统代理
        sp = _get_system_proxy()
        return sp
    # 统一逗号分隔 → 换行
    lines = [p.strip() for p in raw.replace(",", "\n").splitlines() if p.strip()]
    return "\n".join(lines)


@app.get("/api/system-proxy")
async def system_proxy():
    return {"proxy": _get_proxy_pool()}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class StartSessionRequest(BaseModel):
    proxies: str
    count: int
    concurrency: int = 3

    @field_validator("count")
    @classmethod
    def count_range(cls, v):
        if v < 1:
            raise ValueError("count must be >= 1")
        return v

    @field_validator("concurrency")
    @classmethod
    def concurrency_range(cls, v):
        if not (1 <= v <= 1000):
            raise ValueError("concurrency must be 1-1000")
        return v


@app.post("/api/sessions", status_code=201)
async def start_session(req: StartSessionRequest):
    proxy_list = [p.strip() for p in req.proxies.splitlines() if p.strip()]
    if not proxy_list:
        raise HTTPException(400, "至少需要一个代理地址")

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO sessions (created_at, proxies, proxy_count, requested, concurrency)
               VALUES (?,?,?,?,?)""",
            (_now(), req.proxies, len(proxy_list), req.count, req.concurrency),
        )
        session_id = cur.lastrowid

    active_ws[session_id]  # 预初始化 defaultdict
    asyncio.create_task(_run_session(session_id, proxy_list, req.count, req.concurrency))

    return {"session_id": session_id}


@app.get("/api/sessions/active")
async def get_active_session():
    """查询当前运行中或暂停的 session（用于前端恢复进度界面）。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE status IN ('running','paused') ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {"session": None}
    return {"session": dict(row)}


@app.post("/api/sessions/{session_id}/pause")
async def pause_session(session_id: int):
    ev = session_pause_events.get(session_id)
    if not ev:
        # 任务已不在内存中，修正数据库状态
        with get_conn() as conn:
            conn.execute("UPDATE sessions SET status='done' WHERE id=? AND status IN ('running','paused')", (session_id,))
        raise HTTPException(409, "任务已结束，状态已修正")
    ev.clear()
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET status='paused' WHERE id=?", (session_id,))
    await _broadcast(session_id, {"type": "paused"})
    return {"status": "paused"}


@app.post("/api/sessions/{session_id}/resume")
async def resume_session(session_id: int):
    ev = session_pause_events.get(session_id)
    if not ev:
        with get_conn() as conn:
            conn.execute("UPDATE sessions SET status='done' WHERE id=? AND status IN ('running','paused')", (session_id,))
        raise HTTPException(409, "任务已结束，状态已修正")
    ev.set()
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET status='running' WHERE id=?", (session_id,))
    await _broadcast(session_id, {"type": "resumed"})
    return {"status": "running"}


@app.get("/api/sessions")
async def list_sessions():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM sessions ORDER BY id DESC").fetchall()
        # 统计每个 session 的出口 IP 使用情况
        ip_stats = conn.execute(
            """SELECT session_id,
                      COUNT(DISTINCT exit_ip) AS unique_ips,
                      COUNT(exit_ip) AS total_uses
               FROM accounts
               WHERE exit_ip IS NOT NULL
               GROUP BY session_id"""
        ).fetchall()
    ip_map = {r["session_id"]: {"unique_ips": r["unique_ips"], "reused_ips": r["total_uses"] - r["unique_ips"]} for r in ip_stats}
    result = []
    for r in rows:
        d = dict(r)
        stats = ip_map.get(d["id"], {"unique_ips": 0, "reused_ips": 0})
        d.update(stats)
        result.append(d)
    return result


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT email, account_id, refresh_token, id_token, access_token,
                      expired, last_refresh, proxy_used, created_at
               FROM accounts
               WHERE session_id = ? AND error IS NULL
               ORDER BY id""",
            (session_id,),
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "email", "account_id", "refresh_token", "id_token", "access_token",
        "expired", "last_refresh", "proxy_used", "created_at",
    ])
    for row in rows:
        writer.writerow(list(row))
    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="session_{session_id}.csv"'},
    )


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@app.get("/api/accounts")
async def list_accounts(
    session_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    alive: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    page_size = min(page_size, 200)
    offset = (page - 1) * page_size
    where, params = _build_account_where(session_id, status, search, alive)

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM accounts {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT id, session_id, created_at, email, account_id,
                       expired, proxy_used, error, alive, checked_at, plan_type,
                       auto_refresh, last_auto_refresh, exit_ip, usage_json
                FROM accounts {where}
                ORDER BY id DESC LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()

    return {"total": total, "page": page, "page_size": page_size, "items": [dict(r) for r in rows]}


@app.get("/api/accounts/export")
async def export_accounts(
    session_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    alive: Optional[str] = None,
):
    where, params = _build_account_where(session_id, status, search, alive)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT email, account_id, refresh_token, id_token, access_token,
                       expired, last_refresh, proxy_used, created_at
                FROM accounts {where}
                ORDER BY id DESC""",
            params,
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "email", "account_id", "refresh_token", "id_token", "access_token",
        "expired", "last_refresh", "proxy_used", "created_at",
    ])
    for row in rows:
        writer.writerow(list(row))
    output.seek(0)

    filename = "accounts_search.csv" if search else "accounts.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ImportAccountsRequest(BaseModel):
    tokens: str
    proxy: str = ""
    concurrency: int = 3

    @field_validator("concurrency")
    @classmethod
    def concurrency_range(cls, v):
        if not (1 <= v <= 10):
            raise ValueError("concurrency must be 1-10")
        return v


def _parse_import_lines(raw: str) -> list[str]:
    """将导入文本解析为行列表，支持 CSV 格式（自动转为 JSON 行）。"""
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return []
    # 检测是否为 CSV：首行包含 refresh_token 表头
    header = lines[0].lower()
    if "refresh_token" in header and "," in header:
        reader = csv.DictReader(io.StringIO(raw))
        result = []
        for row in reader:
            rt = (row.get("refresh_token") or "").strip()
            if rt:
                result.append(json.dumps({k: v for k, v in row.items() if v}, ensure_ascii=False))
        return result
    return lines


@app.post("/api/accounts/import", status_code=201)
async def import_accounts(req: ImportAccountsRequest):
    lines = _parse_import_lines(req.tokens)
    if not lines:
        raise HTTPException(400, "请输入至少一个 token")
    proxy = req.proxy.strip() or _get_proxy_pool()
    if not proxy:
        raise HTTPException(400, "请提供代理地址")

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO sessions (created_at, proxies, proxy_count, requested, concurrency, status)
               VALUES (?,?,?,?,?,?)""",
            (_now(), proxy, 1, len(lines), req.concurrency, "importing"),
        )
        session_id = cur.lastrowid

    import_id = str(_uuid.uuid4())
    active_check_ws[import_id]
    asyncio.create_task(_run_import_session(import_id, session_id, lines, proxy, req.concurrency))
    return {"import_id": import_id, "session_id": session_id, "total": len(lines)}


@app.put("/api/accounts/{account_id_pk}/auto-refresh")
async def set_auto_refresh(account_id_pk: int, enabled: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE accounts SET auto_refresh=? WHERE id=?",
            (1 if enabled else 0, account_id_pk),
        )
    return {"auto_refresh": enabled}


@app.get("/api/accounts/{account_id_pk}")
async def get_account(account_id_pk: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id_pk,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Account not found")
    return dict(row)


@app.delete("/api/accounts/dead")
async def delete_dead_accounts():
    """删除所有已失效（alive='dead'）的账号。"""
    with get_conn() as conn:
        result = conn.execute("DELETE FROM accounts WHERE alive = 'dead'")
        count = result.rowcount
    return {"deleted": count}


# ---------------------------------------------------------------------------
# 存活检测
# ---------------------------------------------------------------------------

import uuid as _uuid

class CheckSessionRequest(BaseModel):
    account_ids: list[int]
    proxies: str
    concurrency: int = 5

    @field_validator("concurrency")
    @classmethod
    def concurrency_range(cls, v):
        if not (1 <= v <= 1000):
            raise ValueError("concurrency must be 1-1000")
        return v


async def _broadcast_check(check_id: str, msg: dict):
    for q in list(active_check_ws.get(check_id, [])):
        try:
            await q.put(msg)
        except Exception:
            pass


async def _run_check_session(
    check_id: str, account_ids: list[int], proxy_list: list[str], concurrency: int
):
    # 预检代理
    valid_proxies = await _filter_proxies(proxy_list)
    if not valid_proxies:
        logger.warning("check %s: 所有代理均不可用", check_id)
        _broadcast(f"check:{check_id}", {"type": "done", "detail": "所有代理均不可用"})
        return
    logger.info("check %s: %d/%d 代理可用", check_id, len(valid_proxies), len(proxy_list))
    proxy_list = valid_proxies

    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(concurrency)
    total = len(account_ids)

    async def _check_one(acct_id: int):
        async with sem:
            # 随机启动延迟，避免并发请求同时发出
            await asyncio.sleep(random.uniform(0.2, 1.0))
            # 获取 refresh_token
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT refresh_token FROM accounts WHERE id = ?", (acct_id,)
                ).fetchone()
            if not row or not row["refresh_token"]:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE accounts SET alive='error', checked_at=? WHERE id=?",
                        (_now(), acct_id),
                    )
                await _broadcast_check(check_id, {
                    "type": "result", "account_id": acct_id, "alive": "error"
                })
                return

            proxy = random.choice(proxy_list)
            result = await loop.run_in_executor(
                executor, _check_alive, row["refresh_token"], proxy
            )
            alive_status, new_access, new_refresh, new_id, plan_type, expires_at, usage_json = result

            with get_conn() as conn:
                if alive_status == "alive":
                    conn.execute(
                        """UPDATE accounts
                           SET alive=?, checked_at=?,
                               access_token=COALESCE(?,access_token),
                               refresh_token=COALESCE(?,refresh_token),
                               id_token=COALESCE(?,id_token),
                               plan_type=COALESCE(?,plan_type),
                               expired=COALESCE(?,expired),
                               usage_json=COALESCE(?,usage_json)
                           WHERE id=?""",
                        (alive_status, _now(), new_access, new_refresh, new_id,
                         plan_type, expires_at, usage_json, acct_id),
                    )
                else:
                    conn.execute(
                        "UPDATE accounts SET alive=?, checked_at=? WHERE id=?",
                        (alive_status, _now(), acct_id),
                    )

            await _broadcast_check(check_id, {
                "type": "result", "account_id": acct_id, "alive": alive_status
            })

    await asyncio.gather(*[_check_one(aid) for aid in account_ids])

    # 统计
    with get_conn() as conn:
        stats = conn.execute(
            """SELECT alive, COUNT(*) as cnt FROM accounts
               WHERE id IN ({}) GROUP BY alive""".format(
                ",".join("?" * len(account_ids))
            ),
            account_ids,
        ).fetchall()
    stat_map = {r["alive"]: r["cnt"] for r in stats}

    await _broadcast_check(check_id, {
        "type": "done",
        "total": total,
        "alive": stat_map.get("alive", 0),
        "dead": stat_map.get("dead", 0),
        "error": stat_map.get("error", 0),
    })


@app.post("/api/check-sessions", status_code=201)
async def start_check_session(req: CheckSessionRequest):
    if not req.account_ids:
        raise HTTPException(400, "account_ids 不能为空")
    proxy_list = [p.strip() for p in req.proxies.splitlines() if p.strip()]
    if not proxy_list:
        raise HTTPException(400, "至少需要一个代理地址")

    check_id = str(_uuid.uuid4())
    active_check_ws[check_id]  # 预初始化
    asyncio.create_task(
        _run_check_session(check_id, req.account_ids, proxy_list, req.concurrency)
    )
    return {"check_id": check_id, "total": len(req.account_ids)}


@app.websocket("/ws/check/{check_id}")
async def ws_check(websocket: WebSocket, check_id: str):
    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue()
    active_check_ws[check_id].append(q)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=120)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(msg)
            if msg.get("type") == "done":
                break
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        try:
            active_check_ws[check_id].remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# 导入账号
# ---------------------------------------------------------------------------

def _extract_from_id_token(id_token: str) -> tuple:
    """从 JWT id_token 中解析 email 和 account_id（不校验签名）。"""
    if not id_token or id_token.count(".") < 2:
        return "", ""
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii")).decode("utf-8"))
        email = str(payload.get("email") or "")
        auth_claims = payload.get("https://api.openai.com/auth") or {}
        account_id = str(auth_claims.get("chatgpt_account_id") or "")
        return email, account_id
    except Exception:
        return "", ""


async def _run_import_session(import_id: str, session_id: int, lines: list, proxy: str, concurrency: int):
    # 预检代理
    loop = asyncio.get_event_loop()
    ok, reason = await loop.run_in_executor(executor, _check_proxy, proxy)
    if not ok:
        logger.warning("import %s: 代理不可用: %s -> %s", import_id, proxy, reason)
        _broadcast(f"session:{import_id}", {"type": "done", "detail": f"代理不可用: {reason}"})
        return

    sem = asyncio.Semaphore(concurrency)

    async def _import_one(line: str):
        async with sem:
            # 随机启动延迟，避免并发请求同时发出
            await asyncio.sleep(random.uniform(0.2, 1.0))
            refresh_token = None
            extra = {}
            try:
                obj = json.loads(line)
                refresh_token = obj.get("refresh_token") or obj.get("token")
                extra = {k: obj.get(k) for k in ("access_token", "id_token", "email", "account_id", "expired", "last_refresh")}
            except (json.JSONDecodeError, ValueError):
                refresh_token = line.strip()

            if not refresh_token:
                with get_conn() as conn:
                    conn.execute("UPDATE sessions SET failed = failed + 1 WHERE id = ?", (session_id,))
                await _broadcast_check(import_id, {"type": "result", "alive": "error", "email": None})
                return

            result = await loop.run_in_executor(executor, _check_alive, refresh_token, proxy)
            alive_status, new_access, new_refresh, new_id, plan_type, expires_at, usage_json = result

            # 从 id_token 里解析 email / account_id
            email = extra.get("email") or ""
            account_id = extra.get("account_id") or ""
            if new_id and (not email or not account_id):
                em, aid = _extract_from_id_token(new_id)
                email = email or em
                account_id = account_id or aid

            now = _now()
            with get_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO accounts
                       (session_id, created_at, email, account_id, refresh_token, id_token,
                        access_token, expired, last_refresh, proxy_used, alive, checked_at,
                        plan_type, auto_refresh, usage_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                    (
                        session_id, now,
                        email or None,
                        account_id or None,
                        new_refresh or refresh_token,
                        new_id or extra.get("id_token"),
                        new_access or extra.get("access_token"),
                        expires_at or extra.get("expired"),
                        extra.get("last_refresh") or now,
                        proxy,
                        alive_status,
                        now,
                        plan_type,
                        usage_json,
                    ),
                )
                acct_id = cur.lastrowid
                if alive_status == "alive":
                    conn.execute("UPDATE sessions SET success = success + 1 WHERE id = ?", (session_id,))
                else:
                    conn.execute("UPDATE sessions SET failed = failed + 1 WHERE id = ?", (session_id,))

            await _broadcast_check(import_id, {
                "type": "result",
                "account_id": acct_id,
                "alive": alive_status,
                "email": email or None,
            })

    await asyncio.gather(*[_import_one(line) for line in lines])

    with get_conn() as conn:
        row = conn.execute("SELECT success, failed FROM sessions WHERE id = ?", (session_id,)).fetchone()
        conn.execute("UPDATE sessions SET status = 'done' WHERE id = ?", (session_id,))

    await _broadcast_check(import_id, {
        "type": "done",
        "total": len(lines),
        "alive": row["success"] if row else 0,
        "dead": 0,
        "error": row["failed"] if row else 0,
    })


# ---------------------------------------------------------------------------
# 自动保活
# ---------------------------------------------------------------------------

async def _do_auto_refresh():
    pool_str = _get_proxy_pool()
    proxy_pool = [p.strip() for p in pool_str.splitlines() if p.strip()] if pool_str else []

    # 刷新 10 分钟内即将过期的账号（或 expired 为空）
    threshold = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, refresh_token, proxy_used FROM accounts
               WHERE auto_refresh=1 AND alive != 'dead' AND refresh_token IS NOT NULL
               AND (expired IS NULL OR expired <= ?)""",
            (threshold,),
        ).fetchall()

    if not rows:
        return

    logger.info(f"Auto-refresh: 刷新 {len(rows)} 个账号")
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(3)

    async def _refresh_one(row):
        proxy = random.choice(proxy_pool) if proxy_pool else row["proxy_used"]
        if not proxy:
            return
        async with sem:
            result = await loop.run_in_executor(executor, _check_alive, row["refresh_token"], proxy)
            alive_status, new_access, new_refresh, new_id, plan_type, expires_at, usage_json = result
            with get_conn() as conn:
                conn.execute(
                    """UPDATE accounts
                       SET alive=?, checked_at=?, last_auto_refresh=?,
                           access_token=COALESCE(?,access_token),
                           refresh_token=COALESCE(?,refresh_token),
                           id_token=COALESCE(?,id_token),
                           plan_type=COALESCE(?,plan_type),
                           expired=COALESCE(?,expired),
                           usage_json=COALESCE(?,usage_json)
                       WHERE id=?""",
                    (alive_status, _now(), _now(),
                     new_access, new_refresh, new_id, plan_type, expires_at, usage_json,
                     row["id"]),
                )

    await asyncio.gather(*[_refresh_one(row) for row in rows])


async def _auto_refresh_loop():
    while True:
        try:
            await asyncio.sleep(1800)  # 每 30 分钟检查一次
            await _do_auto_refresh()
        except Exception as e:
            logger.error(f"Auto-refresh 异常: {e}")


# ---------------------------------------------------------------------------
# 定时任务
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    name: str = ""
    task_type: str = "register"  # 'register' | 'check' | 'refresh' | 'clean'
    proxies: str = ""
    target: int = 0
    concurrency: int = 3
    check_filter: str = "all"   # 'all' | 'alive' | 'unchecked'
    check_limit: int = 0        # 0 = 全部
    auto_clean: bool = False    # 检测后自动清理 dead
    schedule_type: str           # 'once' | 'daily'
    run_time: str                # once: "2026-03-20T10:30:00" | daily: "10:30"

    @field_validator("schedule_type")
    @classmethod
    def validate_type(cls, v):
        if v not in ("once", "daily"):
            raise ValueError("schedule_type must be 'once' or 'daily'")
        return v

    @field_validator("task_type")
    @classmethod
    def validate_task_type(cls, v):
        if v not in ("register", "check", "refresh", "clean"):
            raise ValueError("task_type must be 'register', 'check', 'refresh' or 'clean'")
        return v


def _calc_next_run(schedule_type: str, run_time: str) -> str:
    """计算下次运行时间（本地时间）。"""
    now = datetime.now()
    if schedule_type == "once":
        return run_time
    # daily: run_time 格式 "HH:MM"
    h, m = map(int, run_time.split(":"))
    next_run = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run.strftime("%Y-%m-%dT%H:%M:%S")


@app.get("/api/schedules")
async def list_schedules():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM schedules ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/schedules", status_code=201)
async def create_schedule(req: ScheduleRequest):
    proxy_list = [p.strip() for p in req.proxies.splitlines() if p.strip()]
    if req.task_type != "clean" and not proxy_list:
        raise HTTPException(400, "至少需要一个代理地址")
    next_run = _calc_next_run(req.schedule_type, req.run_time)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO schedules
               (created_at, name, task_type, proxies, target, concurrency,
                check_filter, check_limit, auto_clean, schedule_type, run_time, next_run, enabled)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (_now(), req.name, req.task_type, req.proxies, req.target, req.concurrency,
             req.check_filter, req.check_limit, int(req.auto_clean),
             req.schedule_type, req.run_time, next_run),
        )
        sid = cur.lastrowid
    return {"id": sid}


@app.put("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, req: ScheduleRequest):
    next_run = _calc_next_run(req.schedule_type, req.run_time)
    with get_conn() as conn:
        conn.execute(
            """UPDATE schedules
               SET name=?, task_type=?, proxies=?, target=?, concurrency=?,
                   check_filter=?, check_limit=?, auto_clean=?,
                   schedule_type=?, run_time=?, next_run=?
               WHERE id=?""",
            (req.name, req.task_type, req.proxies, req.target, req.concurrency,
             req.check_filter, req.check_limit, int(req.auto_clean),
             req.schedule_type, req.run_time, next_run, schedule_id),
        )
    return {"ok": True}


@app.put("/api/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT enabled, schedule_type, run_time FROM schedules WHERE id=?", (schedule_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        new_enabled = 0 if row["enabled"] else 1
        updates = {"enabled": new_enabled}
        if new_enabled:
            updates["next_run"] = _calc_next_run(row["schedule_type"], row["run_time"])
        conn.execute(
            "UPDATE schedules SET enabled=?, next_run=? WHERE id=?",
            (new_enabled, updates.get("next_run", None), schedule_id),
        )
    return {"enabled": bool(new_enabled)}


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
    return {"ok": True}


@app.get("/api/schedules/{schedule_id}/runs")
async def get_schedule_runs(schedule_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_runs WHERE schedule_id=? ORDER BY id DESC LIMIT 50",
            (schedule_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/schedule-runs")
async def get_all_runs(limit: int = 50):
    """获取所有任务的最近执行记录。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT r.*, s.name as schedule_name
               FROM schedule_runs r
               LEFT JOIN schedules s ON s.id = r.schedule_id
               ORDER BY r.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


async def _check_schedules():
    """检查是否有到期的定时任务，触发注册/检测/刷新/清理。"""
    now_str = _now()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE enabled=1 AND next_run <= ?",
            (now_str,),
        ).fetchall()

    for sched in rows:
        sched = dict(sched)
        proxy_list = [p.strip() for p in (sched.get("proxies") or "").splitlines() if p.strip()]

        task_type = sched.get("task_type") or "register"
        logger.info("定时任务触发: id=%s name=%s type=%s", sched["id"], sched["name"], task_type)

        # 创建执行记录
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO schedule_runs (schedule_id, started_at, task_type, status, detail) VALUES (?,?,?,?,?)",
                (sched["id"], now_str, task_type, "running", ""),
            )
            run_id = cur.lastrowid

        session_id = None

        if task_type == "register":
            if not proxy_list:
                _finish_run(run_id, "failed", "无可用代理")
                continue
            with get_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO sessions (created_at, proxies, proxy_count, requested, concurrency)
                       VALUES (?,?,?,?,?)""",
                    (_now(), sched["proxies"], len(proxy_list), sched["target"], sched["concurrency"]),
                )
                session_id = cur.lastrowid
            active_ws[session_id]
            asyncio.create_task(
                _tracked_register(run_id, session_id, proxy_list, sched["target"], sched["concurrency"])
            )

        elif task_type == "check":
            if not proxy_list:
                _finish_run(run_id, "failed", "无可用代理")
                continue
            check_filter = sched.get("check_filter") or "all"
            check_limit = sched.get("check_limit") or 0
            auto_clean = bool(sched.get("auto_clean"))
            with get_conn() as conn:
                limit_clause = f" ORDER BY RANDOM() LIMIT {check_limit}" if check_limit > 0 else ""
                if check_filter == "alive":
                    sql = f"SELECT id FROM accounts WHERE alive='alive' AND refresh_token IS NOT NULL{limit_clause}"
                elif check_filter == "unchecked":
                    sql = f"SELECT id FROM accounts WHERE alive IS NULL AND refresh_token IS NOT NULL{limit_clause}"
                else:
                    sql = f"SELECT id FROM accounts WHERE error IS NULL AND refresh_token IS NOT NULL{limit_clause}"
                acct_rows = conn.execute(sql).fetchall()

            account_ids = [r["id"] for r in acct_rows]
            if account_ids:
                check_id = str(_uuid.uuid4())
                active_check_ws[check_id]
                asyncio.create_task(
                    _tracked_check(run_id, check_id, account_ids, proxy_list, sched["concurrency"], auto_clean)
                )
            else:
                _finish_run(run_id, "done", "无需检测的账号")

        elif task_type == "refresh":
            if not proxy_list:
                _finish_run(run_id, "failed", "无可用代理")
                continue
            check_limit = sched.get("check_limit") or 0
            with get_conn() as conn:
                limit_clause = f" ORDER BY RANDOM() LIMIT {check_limit}" if check_limit > 0 else ""
                acct_rows = conn.execute(
                    f"SELECT id FROM accounts WHERE error IS NULL AND refresh_token IS NOT NULL{limit_clause}"
                ).fetchall()
            account_ids = [r["id"] for r in acct_rows]
            if account_ids:
                check_id = str(_uuid.uuid4())
                active_check_ws[check_id]
                asyncio.create_task(
                    _tracked_refresh(run_id, check_id, account_ids, proxy_list, sched["concurrency"])
                )
            else:
                _finish_run(run_id, "done", "无需刷新的账号")

        elif task_type == "clean":
            with get_conn() as conn:
                result = conn.execute("DELETE FROM accounts WHERE alive = 'dead'")
                count = result.rowcount
            _finish_run(run_id, "done", f"清理 {count} 个失效账号")

        # 更新定时任务状态
        with get_conn() as conn:
            if sched["schedule_type"] == "once":
                conn.execute(
                    "UPDATE schedules SET enabled=0, last_run_at=?, last_session_id=?, next_run=NULL WHERE id=?",
                    (now_str, session_id, sched["id"]),
                )
            else:
                next_run = _calc_next_run("daily", sched["run_time"])
                conn.execute(
                    "UPDATE schedules SET last_run_at=?, last_session_id=?, next_run=? WHERE id=?",
                    (now_str, session_id, next_run, sched["id"]),
                )


def _finish_run(run_id: int, status: str, detail: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE schedule_runs SET finished_at=?, status=?, detail=? WHERE id=?",
            (_now(), status, detail, run_id),
        )


def _update_run_detail(run_id: int, detail: str):
    with get_conn() as conn:
        conn.execute("UPDATE schedule_runs SET detail=? WHERE id=?", (detail, run_id))


async def _tracked_register(run_id, session_id, proxy_list, target, concurrency):
    """注册任务包装：实时更新进度，完成后更新执行记录。"""
    try:
        # 启动一个后台任务定期更新进度
        done_event = asyncio.Event()

        async def _poll_progress():
            while not done_event.is_set():
                await asyncio.sleep(5)
                with get_conn() as conn:
                    row = conn.execute("SELECT success, failed FROM sessions WHERE id=?", (session_id,)).fetchone()
                if row:
                    _update_run_detail(run_id, f"成功 {row['success']} / 目标 {target}，失败 {row['failed']}")

        poll_task = asyncio.create_task(_poll_progress())
        await _run_session(session_id, proxy_list, target, concurrency)
        done_event.set()
        await poll_task

        with get_conn() as conn:
            row = conn.execute("SELECT success, failed FROM sessions WHERE id=?", (session_id,)).fetchone()
        detail = f"成功 {row['success']} / 目标 {target}，失败 {row['failed']}" if row else ""
        _finish_run(run_id, "done", detail)
    except Exception as e:
        _finish_run(run_id, "failed", str(e))


async def _tracked_check(run_id, check_id, account_ids, proxy_list, concurrency, auto_clean):
    """检测任务包装：实时更新进度，完成后可选自动清理。"""
    total = len(account_ids)
    try:
        done_event = asyncio.Event()

        async def _poll_progress():
            while not done_event.is_set():
                await asyncio.sleep(5)
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) as checked FROM accounts WHERE id IN ({}) AND checked_at >= ?".format(
                            ",".join("?" * total)
                        ),
                        [*account_ids, _now()[:10]],
                    ).fetchone()
                checked = row["checked"] if row else 0
                _update_run_detail(run_id, f"已检测 {checked} / {total}")

        poll_task = asyncio.create_task(_poll_progress())
        await _run_check_session(check_id, account_ids, proxy_list, concurrency)
        done_event.set()
        await poll_task

        cleaned = 0
        if auto_clean:
            with get_conn() as conn:
                result = conn.execute("DELETE FROM accounts WHERE alive = 'dead'")
                cleaned = result.rowcount
        detail = f"检测 {total} 个账号"
        if cleaned:
            detail += f"，清理 {cleaned} 个失效"
        _finish_run(run_id, "done", detail)
    except Exception as e:
        _finish_run(run_id, "failed", str(e))


async def _tracked_refresh(run_id, check_id, account_ids, proxy_list, concurrency):
    """刷新任务包装：实时更新进度，完成后更新执行记录。"""
    total = len(account_ids)
    try:
        done_event = asyncio.Event()

        async def _poll_progress():
            while not done_event.is_set():
                await asyncio.sleep(5)
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) as done FROM accounts WHERE id IN ({}) AND last_auto_refresh >= ?".format(
                            ",".join("?" * total)
                        ),
                        [*account_ids, _now()[:10]],
                    ).fetchone()
                done_count = row["done"] if row else 0
                _update_run_detail(run_id, f"已刷新 {done_count} / {total}")

        poll_task = asyncio.create_task(_poll_progress())
        await _run_check_session(check_id, account_ids, proxy_list, concurrency)
        done_event.set()
        await poll_task
        _finish_run(run_id, "done", f"刷新 {total} 个账号")
    except Exception as e:
        _finish_run(run_id, "failed", str(e))


async def _schedule_loop():
    while True:
        try:
            await asyncio.sleep(30)  # 每 30 秒检查一次
            await _check_schedules()
        except Exception as e:
            logger.error(f"Schedule loop 异常: {e}")


if __name__ == '__main__':
    import uvicorn
    backend_host = _env_first("BACKEND_HOST", "APP_HOST", default="127.0.0.1")
    backend_port = int(_env_first("BACKEND_PORT", "APP_PORT", default="8000"))
    uvicorn.run(app, host=backend_host, port=backend_port)
