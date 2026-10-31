import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMUNITY = "昌福里社区27区党群物业服务站"
DATA = Path(os.environ.get("ELEVATOR_DATA_DIR", ROOT / "data"))
STORAGE = Path(os.environ.get("ELEVATOR_STORAGE_DIR", ROOT / "storage"))
EXPORTS = Path(os.environ.get("ELEVATOR_EXPORT_DIR", ROOT / "exports"))
BACKUPS = Path(os.environ.get("ELEVATOR_BACKUP_DIR", ROOT / "backups"))
LOGS = Path(os.environ.get("ELEVATOR_LOG_DIR", ROOT / "logs"))
DB = DATA / "elevator.db"

for directory in (DATA, STORAGE, EXPORTS, BACKUPS, LOGS):
    directory.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now().astimezone().isoformat(timespec="microseconds")


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 310_000)
    return f"{salt}${value.hex()}"


def verify_password(password, encoded):
    try:
        salt, expected = encoded.split("$", 1)
        return secrets.compare_digest(password_hash(password, salt), encoded)
    except (ValueError, AttributeError):
        return False


def audit(db, user_id, action, target, target_id, before=None, after=None):
    db.execute("INSERT INTO audit_logs(user_id,action,target,target_id,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)",
               (user_id, action, target, target_id, json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False) if after is not None else None, now()))


def init_db():
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','staff')),
          active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS buildings (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, deleted_at TEXT);
        CREATE TABLE IF NOT EXISTS units (
          id INTEGER PRIMARY KEY, building_id INTEGER NOT NULL REFERENCES buildings(id), name TEXT NOT NULL,
          deleted_at TEXT, UNIQUE(building_id,name));
        CREATE TABLE IF NOT EXISTS elevators (
          id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL REFERENCES units(id), name TEXT NOT NULL,
          internal_number TEXT, equipment_number TEXT, brand TEXT, model TEXT, manufactured_on TEXT,
          started_on TEXT, maintenance_company TEXT, maintenance_contact TEXT, maintenance_phone TEXT,
          inspection_on TEXT, maintenance_due_on TEXT, status TEXT NOT NULL DEFAULT '正常', notes TEXT,
          deleted_at TEXT, UNIQUE(unit_id,name));
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, elevator_id INTEGER NOT NULL REFERENCES elevators(id), type TEXT NOT NULL,
          title TEXT NOT NULL, occurred_on TEXT NOT NULL, started_at TEXT, ended_at TEXT,
          work_content TEXT, resolution TEXT, workers TEXT, company TEXT, completed INTEGER NOT NULL DEFAULT 1,
          cost_cents INTEGER NOT NULL DEFAULT 0, notes TEXT, fault_at TEXT, symptom TEXT, stopped INTEGER,
          reported_at TEXT, arrived_at TEXT, restored_at TEXT, cause TEXT, remedy TEXT, recovered INTEGER,
          created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          deleted_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_events_elevator_date ON events(elevator_id,occurred_on DESC);
        CREATE TABLE IF NOT EXISTS event_parts (
          id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id), name TEXT NOT NULL,
          model TEXT, quantity INTEGER NOT NULL, unit_price_cents INTEGER NOT NULL DEFAULT 0,
          replaced_on TEXT NOT NULL, reason TEXT, brand TEXT, warranty_days INTEGER NOT NULL DEFAULT 0,
          warranty_from TEXT, warranty_until TEXT, notes TEXT);
        CREATE INDEX IF NOT EXISTS idx_parts_name ON event_parts(name);
        CREATE TABLE IF NOT EXISTS attachments (
          id TEXT PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id), elevator_id INTEGER NOT NULL REFERENCES elevators(id),
          original_name TEXT NOT NULL, relative_path TEXT NOT NULL, category TEXT NOT NULL,
          mime_type TEXT NOT NULL, size INTEGER NOT NULL, uploaded_by INTEGER NOT NULL REFERENCES users(id),
          created_at TEXT NOT NULL, deleted_at TEXT);
        CREATE TABLE IF NOT EXISTS audit_logs (
          id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, target TEXT NOT NULL,
          target_id TEXT, before_json TEXT, after_json TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS export_drafts (
          id INTEGER PRIMARY KEY, created_by INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL,
          filters_json TEXT NOT NULL, source_json TEXT NOT NULL, blocks_json TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          docx_name TEXT, zip_name TEXT);
        """)
        # Old records have no reliable indication of manual versus calculated cost.
        # Preserve their recorded totals; new records retain the user's choice.
        if 'cost_auto' not in {row['name'] for row in db.execute('PRAGMA table_info(events)')}:
            db.execute('ALTER TABLE events ADD COLUMN cost_auto INTEGER NOT NULL DEFAULT 0')
        if 'sort_order' not in {row['name'] for row in db.execute('PRAGMA table_info(attachments)')}:
            db.execute('ALTER TABLE attachments ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0')
        if 'version' not in {row['name'] for row in db.execute('PRAGMA table_info(elevators)')}:
            db.execute('ALTER TABLE elevators ADD COLUMN version INTEGER NOT NULL DEFAULT 1')


def get_one(db, sql, args=()):
    row = db.execute(sql, args).fetchone()
    return dict(row) if row else None


def must_exist(db, table, record_id):
    if table not in {"buildings", "units", "elevators", "events"}:
        raise ValueError("无效的数据类型")
    return get_one(db, f"SELECT * FROM {table} WHERE id=? AND deleted_at IS NULL", (record_id,))
