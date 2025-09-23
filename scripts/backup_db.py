# scripts/backup_db.py
import os, sys, sqlite3, zipfile, time
from datetime import datetime

DB_PATH = os.getenv("DATABASE_FILE", "./app.db")
BACKUP_DIR = os.getenv("BACKUP_DIR", "./backups")
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "14"))

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def sqlite_hot_backup(src, dst):
    # "Горячая" копия через SQLite backup API
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as dest:
        source.backup(dest)

def integrity_check(db_file: str) -> bool:
    try:
        with sqlite3.connect(db_file) as conn:
            cur = conn.execute("PRAGMA integrity_check;")
            return cur.fetchone()[0] == "ok"
    except Exception:
        return False

def zip_file(src_path: str, zip_path: str):
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(src_path, arcname=os.path.basename(src_path))

def cleanup_old_backups(folder: str, retention_days: int):
    cutoff = time.time() - retention_days * 86400
    for name in os.listdir(folder):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except Exception:
            pass

def main():
    ensure_dir(BACKUP_DIR)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    raw_copy = os.path.join(BACKUP_DIR, f"app_{ts}.db")
    zip_copy = os.path.join(BACKUP_DIR, f"app_{ts}.zip")

    # 1) горячая копия
    sqlite_hot_backup(DB_PATH, raw_copy)

    # 2) проверка целостности
    if not integrity_check(raw_copy):
        try:
            os.remove(raw_copy)
        except Exception:
            pass
        print("Integrity check failed", file=sys.stderr)
        sys.exit(1)

    # 3) архив и уборка сырого .db
    zip_file(raw_copy, zip_copy)
    try:
        os.remove(raw_copy)
    except Exception:
        pass

    # 4) ротация
    cleanup_old_backups(BACKUP_DIR, RETENTION_DAYS)

    print(f"OK: {zip_copy}")

if __name__ == "__main__":
    main()
