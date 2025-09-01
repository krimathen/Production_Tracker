import sqlite3
import sys, shutil
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDate


DB_NAME = "app.db"

def get_data_dir() -> Path:
    """Return path to a persistent data directory (next to exe when frozen)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe → use folder next to the exe
        base_dir = Path(sys.executable).resolve().parent
    else:
        # Running from source
        base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    """Return full path to the SQLite database inside the data directory."""
    return get_data_dir() / DB_NAME


def get_connection():
    """Return a robust SQLite connection (WAL, timeout, autocommit, FK)."""
    conn = sqlite3.connect(get_db_path(), timeout=30.0, isolation_level=None)  # autocommit
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def migrate_dates():
    """Normalize all stored dates in repair_orders, employee_hours, and credit_audit to ISO yyyy-MM-dd."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # --- Repair Orders ---
        cursor.execute("SELECT id, date FROM repair_orders")
        for ro_id, date in cursor.fetchall():
            if not date:
                continue
            qdate = QDate.fromString(str(date), "MM/dd/yyyy")
            if qdate.isValid():
                iso = qdate.toString("yyyy-MM-dd")
                cursor.execute("UPDATE repair_orders SET date=? WHERE id=?", (iso, ro_id))

        # --- Employee Hours ---
        cursor.execute("SELECT id, date FROM employee_hours")
        for row_id, date in cursor.fetchall():
            if not date:
                continue
            qdate = QDate.fromString(str(date), "M/d/yyyy")  # handles 8/1/2025 style
            if not qdate.isValid():
                qdate = QDate.fromString(str(date), "MM/dd/yyyy")
            if qdate.isValid():
                iso = qdate.toString("yyyy-MM-dd")
                cursor.execute("UPDATE employee_hours SET date=? WHERE id=?", (iso, row_id))

        # --- Credit Audit ---
        cursor.execute("SELECT id, date FROM credit_audit")
        for row_id, date in cursor.fetchall():
            if not date:
                continue
            iso_str = str(date).split()[0]  # cut off timestamp if present
            qdate = QDate.fromString(iso_str, "MM/dd/yyyy")
            if qdate.isValid():
                iso = qdate.toString("yyyy-MM-dd")
                cursor.execute("UPDATE credit_audit SET date=? WHERE id=?", (iso, row_id))

        conn.commit()
    print("✅ Migrated all dates to ISO (yyyy-MM-dd)")


def migrate_db():
    """Flattened baseline migration for v2.0 (schema_version 200)."""
    conn = get_connection()
    cursor = conn.cursor()

    # Ensure schema_version table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)
    """)
    row = cursor.execute("SELECT version FROM schema_version LIMIT 1").fetchone()

    if row:
        version = row[0]
    else:
        # Brand-new DB (already v2 from initialize_db)
        cursor.execute("INSERT INTO schema_version (version) VALUES (200)")
        version = 200

    if version < 200:
        # --- Backup old DB ---
        db_path = get_db_path()
        backup_path = db_path.with_name(f"{db_path.stem}_before_v2.db")
        if not backup_path.exists():
            import shutil
            shutil.copy(db_path, backup_path)
            print(f"💾 Backup created at {backup_path}")

        # --- Drop existing tables (we’ll rebuild) ---
        existing_tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (t,) in existing_tables:
            if t in ("schema_version",) or t.startswith("sqlite_"):
                continue
            cursor.execute(f"DROP TABLE IF EXISTS {t}")

        # --- Create clean v2 schema ---
        cursor.executescript("""
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            nickname TEXT,
            role TEXT
        );

        CREATE TABLE repair_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_number INTEGER NOT NULL UNIQUE,
            date TEXT NOT NULL,
            estimator_id INTEGER,
            stage TEXT NOT NULL DEFAULT 'Intake',
            status TEXT NOT NULL DEFAULT 'Open',
            hours_total REAL,
            hours_body REAL,
            hours_refinish REAL,
            hours_mechanical REAL,
            hours_taken REAL,
            hours_remaining REAL,
            FOREIGN KEY (estimator_id) REFERENCES employees(id)
        );

        CREATE TABLE ro_hours_allocation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            percent REAL NOT NULL,
            FOREIGN KEY (ro_id) REFERENCES repair_orders(id) ON DELETE CASCADE,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_ro_hours_allocation_ro ON ro_hours_allocation(ro_id);

        CREATE TABLE employee_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            hours_worked REAL,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );

        CREATE TABLE credit_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            hours REAL NOT NULL,
            note TEXT,
            FOREIGN KEY (ro_id) REFERENCES repair_orders(id) ON DELETE CASCADE,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );

        CREATE TABLE ro_stage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (ro_id) REFERENCES repair_orders(id) ON DELETE CASCADE
        );

        CREATE TABLE settings_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            order_index INTEGER
        );

        CREATE TABLE settings_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        """)

        # --- Bump schema version ---
        cursor.execute("DELETE FROM schema_version")
        cursor.execute("INSERT INTO schema_version (version) VALUES (200)")
        print("✅ Migrated DB to version 200 (v2.0 baseline)")

    conn.commit()
    conn.close()


EXPECTED_COLUMNS = [
    ("id", "INTEGER"),
    ("ro_number", "INTEGER"),
    ("date", "TEXT"),
    ("estimator_id", "INTEGER"),
    ("stage", "TEXT"),
    ("status", "TEXT"),
    ("hours_total", "REAL"),
    ("hours_body", "REAL"),
    ("hours_refinish", "REAL"),
    ("hours_mechanical", "REAL"),
    ("hours_taken", "REAL"),
    ("hours_remaining", "REAL"),
]

def initialize_db():
    """Create tables if they don’t exist yet, and check schema (multi-role baseline)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            nickname TEXT
        );

        CREATE TABLE IF NOT EXISTS employee_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_roles_emp ON employee_roles(employee_id);

        CREATE TABLE IF NOT EXISTS repair_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_number INTEGER NOT NULL UNIQUE,
            date TEXT NOT NULL,
            estimator_id INTEGER,
            stage TEXT NOT NULL DEFAULT 'Intake',
            status TEXT NOT NULL DEFAULT 'Open',
            hours_total REAL,
            hours_body REAL,
            hours_refinish REAL,
            hours_mechanical REAL,
            hours_taken REAL,
            hours_remaining REAL,
            FOREIGN KEY (estimator_id) REFERENCES employees(id)
        );

        CREATE TABLE IF NOT EXISTS ro_hours_allocation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            percent REAL NOT NULL,
            FOREIGN KEY (ro_id) REFERENCES repair_orders(id) ON DELETE CASCADE,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_ro_hours_allocation_ro ON ro_hours_allocation(ro_id);

        CREATE TABLE IF NOT EXISTS employee_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            hours_worked REAL,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS credit_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            hours REAL NOT NULL,
            note TEXT,
            FOREIGN KEY (ro_id) REFERENCES repair_orders(id) ON DELETE CASCADE,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_credit_ro ON credit_audit(ro_id);
        CREATE INDEX IF NOT EXISTS idx_credit_emp ON credit_audit(employee_id);

        CREATE TABLE IF NOT EXISTS ro_stage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (ro_id) REFERENCES repair_orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            order_index INTEGER
        );

        CREATE TABLE IF NOT EXISTS settings_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()




