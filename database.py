import sqlite3
import sys, shutil
from pathlib import Path
from PySide6.QtWidgets import QApplication
from utilities.migration_dialogue import NameMigrationDialog

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
    """Convert old MM/dd/yyyy dates in repair_orders to ISO yyyy-MM-dd format."""
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            # Detect if any dates still have slashes (old format)
            cursor.execute("SELECT date FROM repair_orders WHERE date LIKE '%/%' LIMIT 1")
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE repair_orders
                    SET date = substr(date, 7, 4) || '-' || substr(date, 1, 2) || '-' || substr(date, 4, 2)
                    WHERE length(date) = 10
                      AND date LIKE '__/__/____'
                """)
                print("✅ Migrated repair_orders.date to ISO format (yyyy-MM-dd)")
        except Exception as e:
            print(f"⚠️ migrate_dates failed: {e}")


def migrate_db():
    """Run schema migrations safely without dropping existing data."""
    conn = get_connection()
    cursor = conn.cursor()

    # Ensure schema_version table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
    """)

    cursor.execute("SELECT version FROM schema_version LIMIT 1")
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO schema_version (version) VALUES (1)")
        version = 1
    else:
        version = row[0]

    # v1 → v2: add start_time / end_time to employee_hours
    if version < 2:
        for col in ("start_time", "end_time"):
            try:
                cursor.execute(f"ALTER TABLE employee_hours ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        cursor.execute("UPDATE schema_version SET version=2")
        print("✅ Migrated DB to version 2")

    # v2 → v3: add order_index to settings_stages
    if version < 3:
        try:
            cursor.execute("ALTER TABLE settings_stages ADD COLUMN order_index INTEGER")
        except sqlite3.OperationalError:
            pass
        cursor.execute("SELECT id FROM settings_stages ORDER BY name")
        rows = cursor.fetchall()
        for idx, (sid,) in enumerate(rows, start=1):
            cursor.execute("UPDATE settings_stages SET order_index=? WHERE id=?", (idx, sid))
        cursor.execute("UPDATE schema_version SET version=3")
        print("✅ Migrated DB to version 3")

    # v3 → v4: ensure credit_audit has ro_number
    if version < 4:
        cursor.execute("PRAGMA table_info(credit_audit)")
        cols = [c[1] for c in cursor.fetchall()]
        if "ro_number" not in cols:
            cursor.execute("ALTER TABLE credit_audit ADD COLUMN ro_number INTEGER")
        cursor.execute("UPDATE schema_version SET version=4")
        print("✅ Migrated DB to version 4")

    # v4 → v5: enforce UNIQUE on repair_orders.ro_number
    if version < 5:
        cursor.execute("PRAGMA index_list(repair_orders)")
        indexes = [i[1] for i in cursor.fetchall()]
        if "idx_ro_number_unique" not in indexes:
            cursor.execute("CREATE UNIQUE INDEX idx_ro_number_unique ON repair_orders(ro_number)")
        cursor.execute("UPDATE schema_version SET version=5")
        print("✅ Migrated DB to version 5")

        # inside migrate_db():
        if version < 6:
            cursor.execute("PRAGMA table_info(employees)")
            cols = [c[1] for c in cursor.fetchall()]
            if "nickname" not in cols:
                cursor.execute("ALTER TABLE employees ADD COLUMN nickname TEXT")

            # backup db first
            db_path = get_db_path()
            shutil.copy(db_path, db_path.with_name("app_backup_before_v6.db"))

            # Run Qt dialogs if app context exists
            app = QApplication.instance() or QApplication(sys.argv)

            cursor.execute("SELECT id, name, nickname FROM employees")
            rows = cursor.fetchall()
            for emp_id, current_name, current_nickname in rows:
                if current_nickname:
                    continue
                if " " not in current_name.strip():
                    dlg = NameMigrationDialog(current_name)
                    if dlg.exec() and dlg.full_name:
                        cursor.execute(
                            "UPDATE employees SET name=?, nickname=? WHERE id=?",
                            (dlg.full_name, current_name, emp_id)
                        )

            cursor.execute("UPDATE schema_version SET version=6")
            print("✅ Migrated DB to version 6 (GUI nickname migration)")


    conn.commit()
    conn.close()



EXPECTED_COLUMNS = [
    ("id", "INTEGER"),
    ("date", "TEXT"),
    ("ro_number", "INTEGER"),
    ("estimator", "TEXT"),
    ("tech", "TEXT"),
    ("painter", "TEXT"),
    ("mechanic", "TEXT"),
    ("ro_hours", "REAL"),
    ("body_hours", "REAL"),
    ("refinish_hours", "REAL"),
    ("mechanical_hours", "REAL"),
    ("hours_taken", "REAL"),
    ("hours_remaining", "REAL"),
    ("stage", "TEXT"),
    ("status", "TEXT"),
]

def initialize_db():
    """Create tables if they don’t exist yet, and check schema."""
    conn = get_connection()
    cursor = conn.cursor()

    # Create table if missing
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS repair_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ro_number INTEGER NOT NULL UNIQUE,
            estimator TEXT NOT NULL,
            tech TEXT NOT NULL,
            painter TEXT NOT NULL,
            mechanic TEXT NOT NULL,
            ro_hours REAL NOT NULL,
            body_hours REAL NOT NULL,
            refinish_hours REAL NOT NULL,
            mechanical_hours REAL NOT NULL,
            hours_taken REAL NOT NULL,
            hours_remaining REAL NOT NULL,
            stage  TEXT NOT NULL DEFAULT 'Instake',
            status TEXT NOT NULL DEFAULT 'Open'
        );
            
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS employee_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS settings_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            order_index INTEGER NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS employee_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            employee TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            hours_worked REAL NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS ro_stage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (ro_id) REFERENCES repair_orders(id) ON DELETE CASCADE
        );
            
        CREATE TABLE IF NOT EXISTS credit_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ro_number INTEGER NOT NULL,
            date TEXT NOT NULL,
            employee TEXT NOT NULL,
            hours REAL NOT NULL,
            note TEXT,
            FOREIGN KEY (ro_number) REFERENCES repair_orders(ro_number) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_credit_ro ON credit_audit(ro_number);

        """
    )

    # Check schema
    cursor.execute("PRAGMA table_info(repair_orders)")
    cols = cursor.fetchall()
    existing = [(c[1], c[2].upper()) for c in cols]  # (name, type)

    if existing != EXPECTED_COLUMNS:
        print("⚠️ Database schema mismatch!")
        print("Expected:", EXPECTED_COLUMNS)
        print("Found:   ", existing)
        print("Tip: Delete app.db in the data/ folder to rebuild fresh.")

    conn.commit()
    conn.close()
