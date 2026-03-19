import os
import sqlite3
from contextlib import contextmanager

# accounts.db 放在根目录（backend/ 的上一级）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "accounts.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    proxies     TEXT    NOT NULL,
    proxy_count INTEGER NOT NULL,
    requested   INTEGER NOT NULL,
    concurrency INTEGER NOT NULL DEFAULT 1,
    success     INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES sessions(id),
    created_at    TEXT    NOT NULL,
    email         TEXT,
    account_id    TEXT,
    refresh_token TEXT,
    id_token      TEXT,
    access_token  TEXT,
    expired       TEXT,
    last_refresh  TEXT,
    proxy_used    TEXT,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_accounts_session ON accounts(session_id);

CREATE TABLE IF NOT EXISTS schedules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    name          TEXT    NOT NULL DEFAULT '',
    task_type     TEXT    NOT NULL DEFAULT 'register',
    proxies       TEXT    NOT NULL,
    target        INTEGER NOT NULL DEFAULT 0,
    concurrency   INTEGER NOT NULL DEFAULT 3,
    check_filter  TEXT    NOT NULL DEFAULT 'all',
    schedule_type TEXT    NOT NULL DEFAULT 'once',
    run_time      TEXT    NOT NULL,
    next_run      TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    last_run_at   TEXT,
    last_session_id INTEGER
);

CREATE TABLE IF NOT EXISTS schedule_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id   INTEGER NOT NULL REFERENCES schedules(id),
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    task_type     TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'running',
    detail        TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_schedule_runs_sid ON schedule_runs(schedule_id);
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # 迁移：为旧数据库添加新字段
        for col in ["alive TEXT", "checked_at TEXT", "plan_type TEXT",
                    "auto_refresh INTEGER DEFAULT 1", "last_auto_refresh TEXT",
                    "exit_ip TEXT", "usage_json TEXT"]:
            try:
                conn.execute(f"ALTER TABLE accounts ADD COLUMN {col}")
            except Exception:
                pass  # 列已存在
        # 确保所有账号都开启自动刷新
        conn.execute("UPDATE accounts SET auto_refresh=1 WHERE auto_refresh=0 OR auto_refresh IS NULL")
        # 迁移 schedules 新字段
        for col in ["task_type TEXT DEFAULT 'register'", "check_filter TEXT DEFAULT 'all'",
                    "check_limit INTEGER DEFAULT 0", "auto_clean INTEGER DEFAULT 0"]:
            try:
                conn.execute(f"ALTER TABLE schedules ADD COLUMN {col}")
            except Exception:
                pass


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
