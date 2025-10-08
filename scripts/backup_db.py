#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, unquote

# ==== Конфиг через ENV ====
DB_URL      = os.getenv("DATABASE_URL") or os.getenv("DB_URL")  # например: postgres://user:pass@localhost:5432/mydb
BACKUP_DIR  = Path(os.getenv("BACKUP_DIR", "./backups")).resolve()
KEEP_DAYS   = int(os.getenv("BACKUP_KEEP_DAYS", "14"))          # хранить N суток
COMPRESS    = os.getenv("BACKUP_COMPRESS", "1") == "1"          # gzip по умолчанию

BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def _ts() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")

def _rotate_old_backups():
    cutoff = datetime.utcnow() - timedelta(days=KEEP_DAYS)
    for p in BACKUP_DIR.glob("db_*.sql*"):
        # извлекаем дату из имени, если не получилось — оставляем
        m = re.search(r"db_(\d{8}_\d{6}Z)\.sql(\.gz)?$", p.name)
        if not m:
            continue
        try:
            dt = datetime.strptime(m.group(1), "%Y%m%d_%H%M%SZ")
        except ValueError:
            continue
        if dt < cutoff:
            p.unlink(missing_ok=True)

def _backup_postgres(u):
    # urlparse для postgres://user:pass@host:port/dbname
    user = unquote(u.username or "")
    password = unquote(u.password or "")
    host = u.hostname or "localhost"
    port = str(u.port or 5432)
    dbname = u.path.lstrip("/")
    if not dbname:
        raise RuntimeError("DATABASE_URL без имени базы.")

    ts = _ts()
    out = BACKUP_DIR / f"db_{ts}.sql"
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        "pg_dump",
        "-h", host,
        "-p", port,
        "-U", user,
        "-d", dbname,
        "-F", "p",            # plain SQL
        "-x",                 # без ACL
        "-O",                 # без owner
    ]
    with open(out, "wb") as f:
        subprocess.run(cmd, check=True, env=env, stdout=f)

    if COMPRESS:
        subprocess.run(["gzip", "-f", str(out)], check=True)

def _backup_sqlite(u):
    # sqlite:///absolute/path/to.db  или sqlite:///:memory:
    path = u.path
    if not path or path == "/:memory:":
        raise RuntimeError("Нельзя бэкапить :memory: SQLite.")
    src = Path(unquote(path)).resolve()
    if not src.exists():
        raise RuntimeError(f"SQLite файл не найден: {src}")

    ts = _ts()
    out = BACKUP_DIR / f"db_{ts}.sql"
    # используем встроенный дамп sqlite3 → plain SQL (лучше, чем просто копия файла)
    cmd = ["sqlite3", str(src), ".dump"]
    with open(out, "wb") as f:
        subprocess.run(cmd, check=True, stdout=f)
    if COMPRESS:
        subprocess.run(["gzip", "-f", str(out)], check=True)

def _backup_mysql(u):
    # mysql://user:pass@host:3306/dbname
    user = unquote(u.username or "")
    password = unquote(u.password or "")
    host = u.hostname or "localhost"
    port = str(u.port or 3306)
    dbname = u.path.lstrip("/")
    if not dbname:
        raise RuntimeError("DATABASE_URL без имени базы.")

    ts = _ts()
    out = BACKUP_DIR / f"db_{ts}.sql"
    env = os.environ.copy()
    # --password=... опасно в ps, используем env и опцию -p без значения нельзя,
    # поэтому безопаснее через MYSQL_PWD
    if password:
        env["MYSQL_PWD"] = password

    cmd = [
        "mysqldump",
        "-h", host,
        "-P", port,
        "-u", user,
        "--single-transaction",
        "--quick",
        dbname,
    ]
    with open(out, "wb") as f:
        subprocess.run(cmd, check=True, env=env, stdout=f)

    if COMPRESS:
        subprocess.run(["gzip", "-f", str(out)], check=True)

def main():
    if not DB_URL:
        print("ERROR: DATABASE_URL/DB_URL не задан.", file=sys.stderr)
        sys.exit(1)

    u = urlparse(DB_URL)

    try:
        if u.scheme.startswith("postgres"):
            _backup_postgres(u)
        elif u.scheme.startswith("sqlite"):
            _backup_sqlite(u)
        elif u.scheme.startswith("mysql"):
            _backup_mysql(u)
        else:
            raise RuntimeError(f"Неподдерживаемая схема в DATABASE_URL: {u.scheme}")
        _rotate_old_backups()
        print(f"OK: backup done to {BACKUP_DIR}")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: dump failed: {e}", file=sys.stderr)
        sys.exit(e.returncode)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
