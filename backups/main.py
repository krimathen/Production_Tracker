import sys
import os
import sqlite3
import csv
from functools import partial
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget,
    QComboBox, QDateEdit, QHBoxLayout, QMessageBox,
    QListWidget, QAbstractItemView, QHeaderView, QInputDialog,
    QFileDialog
)
from PySide6.QtCore import QDate, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut


# ----------------------------
# Portable data location & config files
# ----------------------------
DATA_DIR = "data"
DB_FILE = os.path.join(DATA_DIR, "records.db")
TECHS_FILE = os.path.join(DATA_DIR, "techs.csv")
STAGES_FILE = os.path.join(DATA_DIR, "stages.txt")
STATUSES_FILE = os.path.join(DATA_DIR, "statuses.txt")
os.makedirs(DATA_DIR, exist_ok=True)

DATE_FMT_QT = "MM-dd-yyyy"
DATE_FMT_PY = "%m-%d-%Y"

DEFAULT_STAGES = ["New Entry", "Intake", "Disassembly", "Body", "Paint", "Reassembly", "Detail", "QC", "Deliver"]
DEFAULT_STATUSES = ["active", "on_hold", "closed"]

# ----------------------------
# Helpers for config lists
# ----------------------------

def load_list_from_file(path, defaults):
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            for item in defaults:
                f.write(item + "\n")
        return defaults[:]
    with open(path, "r", newline="") as f:
        return [line.strip() for line in f if line.strip()]

def save_list_to_file(path, items):
    with open(path, "w", newline="") as f:
        for item in items:
            f.write(item + "\n")

STAGES = load_list_from_file(STAGES_FILE, DEFAULT_STAGES)
STATUSES = load_list_from_file(STATUSES_FILE, DEFAULT_STATUSES)

# ----------------------------
# DB setup
# ----------------------------
conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute(
    """
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY,
        date TEXT,
        tech_name TEXT,
        ro_number TEXT UNIQUE,
        ro_hours REAL,
        hours_taken REAL,
        stage TEXT,
        status TEXT
    )
    """
)
conn.commit()

c.execute(
    """
    CREATE TABLE IF NOT EXISTS technicians (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE
    )
    """
)
conn.commit()

# ---- Stage transitions table (for efficiency credit timing) ----
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS stage_transitions (
        id INTEGER PRIMARY KEY,
        ro_number TEXT,
        from_stage TEXT,
        to_stage TEXT,
        date TEXT
    )
    """
)
conn.commit()

# ---- Manual credit overrides (editable in Efficiency tab) ----
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS credit_overrides (
        id INTEGER PRIMARY KEY,
        ro_number TEXT,
        from_stage TEXT,
        to_stage TEXT,
        note TEXT,
        date TEXT,
        tech TEXT,
        hours REAL,
        UNIQUE(ro_number, from_stage, to_stage, note)
    )
    """
)
conn.commit()

# ---- Credit baselines: first-time hours seen at each milestone (never updated) ----
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS credit_baseline (
        ro_number TEXT,
        milestone TEXT,      -- 'body60', 'body40', 'paint100'
        base_hours REAL,
        PRIMARY KEY (ro_number, milestone)
    )
    """
)
conn.commit()

# ---- Credit adjustments: each later delta after baseline, positive or negative ----
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS credit_adjustments (
        id INTEGER PRIMARY KEY,
        ro_number TEXT,
        milestone TEXT,      -- 'body60', 'body40', 'paint100'
        from_stage TEXT,
        to_stage TEXT,
        date TEXT,           -- MM-dd-yyyy
        tech TEXT,
        delta_hours REAL,    -- in "base" hours before share (e.g. +10 body hours)
        share REAL           -- 0.60, 0.40, or 1.00 (for audit/export)
    )
    """
)
conn.commit()

# ---- Time clock records (persistent worked hours from CSV) ----
conn.execute("""
CREATE TABLE IF NOT EXISTS time_clock_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,        -- MM-dd-YYYY
    tech TEXT,
    clock_in TEXT,    -- HH:MM (24h)
    clock_out TEXT,   -- HH:MM (24h)
    hours REAL
)
""")
conn.commit()



cur = conn.cursor()
count = cur.execute("SELECT COUNT(1) FROM technicians").fetchone()[0]
if count == 0:
    if os.path.exists(TECHS_FILE):
        try:
            with open(TECHS_FILE, "r", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
                if rows and rows[0] and rows[0][0].strip().lower() in {"tech_name", "name"}:
                    rows = rows[1:]
                for r in rows:
                    if not r:
                        continue
                    name = r[0].strip()
                    if name:
                        cur.execute("INSERT OR IGNORE INTO technicians(name) VALUES (?)", (name,))
        except Exception:
            cur.execute("INSERT OR IGNORE INTO technicians(name) VALUES ('Example Tech')")
    else:
        cur.execute("INSERT OR IGNORE INTO technicians(name) VALUES ('Example Tech')")
    conn.commit()

# ---- Inline migration to add split hours + per-role techs on records ----
def _col_exists(table, col):
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))

added = []
if not _col_exists("records", "body_hours"):
    conn.execute("ALTER TABLE records ADD COLUMN body_hours REAL DEFAULT 0")
    added.append("body_hours")
if not _col_exists("records", "paint_hours"):
    conn.execute("ALTER TABLE records ADD COLUMN paint_hours REAL DEFAULT 0")
    added.append("paint_hours")
if not _col_exists("records", "body_tech_name"):
    conn.execute("ALTER TABLE records ADD COLUMN body_tech_name TEXT")
    added.append("body_tech_name")
if not _col_exists("records", "painter_name"):
    conn.execute("ALTER TABLE records ADD COLUMN painter_name TEXT")
    added.append("painter_name")
if not _col_exists("records", "estimator_name"):
    conn.execute("ALTER TABLE records ADD COLUMN estimator_name TEXT")
    added.append("estimator_name")
if not _col_exists("records", "mechanic_name"):
    conn.execute("ALTER TABLE records ADD COLUMN mechanic_name TEXT")
    added.append("mechanic_name")

if added:
    conn.execute("""
                 UPDATE records
                 SET body_tech_name = COALESCE(body_tech_name, tech_name),
                     painter_name   = COALESCE(painter_name, NULL),
                     estimator_name = COALESCE(estimator_name, NULL),
                     mechanic_name  = COALESCE(mechanic_name, NULL)
                 """)

    conn.commit()

class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):  # disable accidental scroll changes
        event.ignore()

# ----------------------------
# Utility
# ----------------------------
def parse_date_str(date_str: str):
    try:
        return datetime.strptime(date_str, DATE_FMT_PY).date()
    except Exception:
        return None

# ----------------------------
# Tabs
# ----------------------------
class AddEntryTab(QWidget):
    UNASSIGNED = "Unassigned"

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())

        # Estimator (before body/painter)
        self.estimator_dropdown = NoWheelComboBox()
        # Per-role techs
        self.body_tech_dropdown = NoWheelComboBox()
        self.painter_dropdown = NoWheelComboBox()
        # Mechanic (after body/painter)
        self.mechanic_dropdown = NoWheelComboBox()
        self._load_techs()

        self.ro_number = QLineEdit()
        self.ro_hours = QLineEdit()

        self.status_dropdown = NoWheelComboBox()
        self._reload_statuses()

        layout.addWidget(QLabel("Date:")); layout.addWidget(self.date_input)

        layout.addWidget(QLabel("Estimator:")); layout.addWidget(self.estimator_dropdown)
        layout.addWidget(QLabel("Body Tech:")); layout.addWidget(self.body_tech_dropdown)
        layout.addWidget(QLabel("Painter:")); layout.addWidget(self.painter_dropdown)
        layout.addWidget(QLabel("Mechanic:")); layout.addWidget(self.mechanic_dropdown)

        layout.addWidget(QLabel("Repair Order # (required):")); layout.addWidget(self.ro_number)
        layout.addWidget(QLabel("RO Hours:")); layout.addWidget(self.ro_hours)

        layout.addWidget(QLabel("Status:")); layout.addWidget(self.status_dropdown)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Create Entry")
        save_btn.clicked.connect(self.save_entry)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)

        # Enter-to-save from line edits
        self.ro_number.returnPressed.connect(self.save_entry)
        self.ro_hours.returnPressed.connect(self.save_entry)

    def _reload_statuses(self):
        self.status_dropdown.clear()
        self.status_dropdown.addItems(STATUSES)

    def _load_techs(self):
        """Load technicians, ensure 'Unassigned' is first, and never duplicate it."""
        cur = conn.cursor()
        names = [row[0] for row in cur.execute("SELECT name FROM technicians ORDER BY name").fetchall()]
        # Remove any accidental/case-variant 'unassigned' from DB list
        names = [n for n in names if (n or "").strip().lower() != self.UNASSIGNED.lower()]
        # Prepend Unassigned
        all_opts = [self.UNASSIGNED] + names

        for cb in (self.estimator_dropdown, self.body_tech_dropdown, self.painter_dropdown, self.mechanic_dropdown):
            cb.clear()
            cb.addItems(all_opts)
            cb.setCurrentIndex(0)  # default to Unassigned
            cb.wheelEvent = lambda event: None  # disable accidental scroll

    def save_entry(self):
        ro_number = (self.ro_number.text() or "").strip()
        if not ro_number:
            QMessageBox.warning(self, "Missing RO#", "Repair Order # is required.")
            return

        # RO hours optional; validate if provided
        txt_total = (self.ro_hours.text() or "").strip()
        if txt_total == "":
            total_hours = 0.0
        else:
            try:
                total_hours = float(txt_total)
            except Exception:
                QMessageBox.warning(self, "Invalid Hours", "RO Hours must be a number, or leave blank.")
                return

        # Read dropdowns; convert Unassigned → ""
        def val(cb):
            t = (cb.currentText() or "").strip()
            return "" if t.lower() == self.UNASSIGNED.lower() else t

        estimator = val(self.estimator_dropdown)
        body_tech = val(self.body_tech_dropdown)
        painter   = val(self.painter_dropdown)
        mechanic  = val(self.mechanic_dropdown)

        date_str = self.date_input.date().toString(DATE_FMT_QT)
        # Default stage to "New Entry" (fallback to first stage if not present)
        stage = next((s for s in STAGES if s.lower() == "new entry"), (STAGES[0] if STAGES else "New Entry"))
        status = self.status_dropdown.currentText()

        cur = conn.cursor()
        exists = cur.execute("SELECT 1 FROM records WHERE ro_number=?", (ro_number,)).fetchone()
        if exists:
            QMessageBox.information(
                self,
                "RO Exists",
                "This RO already exists. Use the Records tab to edit existing entries."
            )
            return  # <-- add-only: do NOT update

        # Insert new record; hours_taken always 0.0
        cur.execute(
            """INSERT INTO records
               (date, estimator_name, body_tech_name, painter_name, mechanic_name,
                ro_number, ro_hours, hours_taken, stage, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date_str, estimator, body_tech, painter, mechanic,
             ro_number, total_hours, 0.0, stage, status),
        )

        # Ensure techs table includes chosen names (skip Unassigned/"")
        for n in (estimator, body_tech, painter, mechanic):
            if n:
                cur.execute("INSERT OR IGNORE INTO technicians(name) VALUES (?)", (n,))

        conn.commit()

        # Clear for next entry
        self.ro_number.clear()
        self.ro_hours.clear()
        for cb in (self.estimator_dropdown, self.body_tech_dropdown, self.painter_dropdown, self.mechanic_dropdown):
            cb.setCurrentIndex(0)  # back to Unassigned

class DashboardTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Stage Counts (active + on_hold)"))
        self.stage_table = QTableWidget()
        self.stage_table.setColumnCount(2)
        self.stage_table.setHorizontalHeaderLabels(["Stage", "Count"])
        self.stage_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.stage_table)

        refresh_btn = QPushButton("Refresh Dashboard")
        refresh_btn.clicked.connect(self.load_data)
        layout.addWidget(refresh_btn)

        self.setLayout(layout)
        self.load_data()

    def load_data(self):
        cur = conn.cursor()
        counts = {s: 0 for s in STAGES}
        for stage, cnt in cur.execute(
            "SELECT stage, COUNT(*) FROM records WHERE status IN ('active','on_hold') GROUP BY stage"
        ).fetchall():
            counts[stage] = cnt

        self.stage_table.setRowCount(len(STAGES))
        for i, s in enumerate(STAGES):
            self.stage_table.setItem(i, 0, QTableWidgetItem(s))
            self.stage_table.setItem(i, 1, QTableWidgetItem(str(counts.get(s, 0))))

class ViewRecordsTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)

        # --- Top controls: Refresh + Search + Delete ---
        controls = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_data)

        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self._delete_selected)

        controls.addWidget(refresh_btn)
        controls.addWidget(del_btn)
        controls.addStretch(1)
        controls.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("RO#, Body Tech, Painter, Stage, Status…")
        controls.addWidget(self.search_edit)
        root.addLayout(controls)

        # Debounce search
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self.search_edit.textChanged.connect(lambda _: self._search_timer.start())
        self._search_timer.timeout.connect(self.load_data)

        # --- Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "Date", "Body Tech", "Painter", "RO#", "RO Hours",
            "Hours Taken", "Hours Remaining", "Body Hours",
            "Refinish Hours", "Stage", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table)

        self._suppress_item_changed = False
        self.table.itemChanged.connect(self._on_item_changed)

        self.load_data()

    # ---------- Helpers ----------
    def _filters_sql_and_params(self):
        parts, params = [], []
        q = (self.search_edit.text() or "").strip()
        if q:
            like = f"%{q}%"
            cols = ["ro_number", "body_tech_name", "painter_name", "stage", "status"]
            parts.append("(" + " OR ".join(f"{c} LIKE ?" for c in cols) + ")")
            params.extend([like] * len(cols))
        where_sql = ("WHERE " + " AND ".join(parts)) if parts else ""
        return where_sql, params

    # ---------- Main loader ----------
    def load_data(self):
        self._suppress_item_changed = True
        where_sql, params = self._filters_sql_and_params()
        cur = conn.cursor()
        sql = f"""
            SELECT date, body_tech_name, painter_name, ro_number, ro_hours,
                   hours_taken, body_hours, paint_hours, stage, status
            FROM records
            {where_sql}
            ORDER BY date DESC, ro_number DESC
        """
        rows = cur.execute(sql, params).fetchall()
        self.table.setRowCount(len(rows))

        techs = [t[0] for t in cur.execute("SELECT name FROM technicians ORDER BY name").fetchall()]

        for r, row in enumerate(rows):
            # Date → calendar-editable
            date_val = row["date"] or QDate.currentDate().toString(DATE_FMT_QT)
            date_edit = QDateEdit(self.table)
            date_edit.setCalendarPopup(True)
            try:
                qd = QDate.fromString(date_val, DATE_FMT_QT)
                if qd.isValid():
                    date_edit.setDate(qd)
                else:
                    date_edit.setDate(QDate.currentDate())
            except Exception:
                date_edit.setDate(QDate.currentDate())
            date_edit.dateChanged.connect(
                partial(self._update_field, row["ro_number"], "date")
            )
            self.table.setCellWidget(r, 0, date_edit)

            # Body Tech dropdown
            body_cb = QComboBox(self.table); body_cb.addItems(techs)
            if row["body_tech_name"] in techs:
                body_cb.setCurrentText(row["body_tech_name"])
            body_cb.wheelEvent = lambda e: None
            body_cb.currentTextChanged.connect(
                partial(self._update_field, row["ro_number"], "body_tech_name")
            )
            self.table.setCellWidget(r, 1, body_cb)

            # Painter dropdown
            painter_cb = QComboBox(self.table); painter_cb.addItems(techs)
            if row["painter_name"] in techs:
                painter_cb.setCurrentText(row["painter_name"])
            painter_cb.wheelEvent = lambda e: None
            painter_cb.currentTextChanged.connect(
                partial(self._update_field, row["ro_number"], "painter_name")
            )
            self.table.setCellWidget(r, 2, painter_cb)

            # RO#
            self.table.setItem(r, 3, QTableWidgetItem(row["ro_number"] or ""))

            # RO Hours
            ro_hours = float(row["ro_hours"] or 0.0)
            self.table.setItem(r, 4, QTableWidgetItem(f"{ro_hours:.1f}"))

            # Hours Taken
            taken = float(row["hours_taken"] or 0.0)
            self.table.setItem(r, 5, QTableWidgetItem(f"{taken:.1f}"))

            # Remaining
            remaining = ro_hours - taken
            self.table.setItem(r, 6, QTableWidgetItem(f"{remaining:.1f}"))

            # Body Hours
            self.table.setItem(r, 7, QTableWidgetItem(f"{float(row['body_hours'] or 0.0):.1f}"))

            # Refinish Hours
            self.table.setItem(r, 8, QTableWidgetItem(f"{float(row['paint_hours'] or 0.0):.1f}"))

            # Stage dropdown
            stage_cb = NoWheelComboBox(self.table); stage_cb.addItems(STAGES)
            stage_cb.setCurrentText(row["stage"] if row["stage"] in STAGES else STAGES[0])
            stage_cb.currentTextChanged.connect(
                partial(self._update_field, row["ro_number"], "stage")
            )
            self.table.setCellWidget(r, 9, stage_cb)

            # Status dropdown
            status_cb = NoWheelComboBox(self.table); status_cb.addItems(STATUSES)
            status_cb.setCurrentText(row["status"] if row["status"] in STATUSES else STATUSES[0])
            status_cb.currentTextChanged.connect(
                partial(self._update_field, row["ro_number"], "status")
            )
            self.table.setCellWidget(r, 10, status_cb)

        self._suppress_item_changed = False

    # ---------- Delete ----------
    def _delete_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "No selection", "Select one or more rows to delete.")
            return
        if QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {len(rows)} selected record(s)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return

        cur = conn.cursor()
        for model_idx in rows:
            ro_item = self.table.item(model_idx.row(), 3)
            if not ro_item:
                continue
            ro_number = (ro_item.text() or "").strip()
            if ro_number:
                cur.execute("DELETE FROM records WHERE ro_number=?", (ro_number,))
        conn.commit()
        self.load_data()

    # ---------- Updates ----------
    def _on_item_changed(self, item: QTableWidgetItem):
        # Only numeric fields still handled here (hours)
        if self._suppress_item_changed:
            return
        row, col = item.row(), item.column()
        editable_map = {
            4: ("ro_hours", "float"),
            5: ("hours_taken", "float"),
            7: ("body_hours", "float"),
            8: ("paint_hours", "float"),
        }
        if col not in editable_map:
            return
        field, kind = editable_map[col]
        ro_item = self.table.item(row, 3)
        if not ro_item:
            return
        ro_number = (ro_item.text() or "").strip()
        new_text = (item.text() or "").strip()
        cur = conn.cursor()
        try:
            v = float(new_text) if new_text != "" else 0.0
        except Exception:
            QMessageBox.warning(self, "Invalid number", f"'{new_text}' is not a valid number.")
            self.load_data()
            return
        cur.execute(f"UPDATE records SET {field}=? WHERE ro_number=?", (v, ro_number))
        conn.commit()
        # update remaining
        if col in (4, 5):
            try:
                ro_hours = float(self.table.item(row, 4).text())
                taken = float(self.table.item(row, 5).text())
                remaining = ro_hours - taken
                self.table.setItem(row, 6, QTableWidgetItem(f"{remaining:.1f}"))
            except Exception:
                pass

    def _on_stage_changed(self, ro_number: str, new_stage: str):
        """When stage changes, log a transition and update the record."""
        cur = conn.cursor()
        row = cur.execute("SELECT stage FROM records WHERE ro_number=?", (ro_number,)).fetchone()
        old_stage = row["stage"] if row else None

        # If we don’t have an old stage or nothing actually changed, just update and bail.
        if not old_stage or old_stage == new_stage:
            cur.execute("UPDATE records SET stage=? WHERE ro_number=?", (new_stage, ro_number))
            conn.commit()
            return

        # Record the transition with today's date, then update the record
        today_str = QDate.currentDate().toString(DATE_FMT_QT)  # MM-dd-yyyy
        cur.execute(
            "INSERT INTO stage_transitions (ro_number, from_stage, to_stage, date) VALUES (?, ?, ?, ?)",
            (ro_number, old_stage, new_stage, today_str)
        )
        cur.execute("UPDATE records SET stage=? WHERE ro_number=?", (new_stage, ro_number))
        conn.commit()

    def _update_field(self, ro_number: str, field: str, value):
        cur = conn.cursor()
        if field == "date" and isinstance(value, QDate):
            val_str = value.toString(DATE_FMT_QT)
            cur.execute("UPDATE records SET date=? WHERE ro_number=?", (val_str, ro_number))
            conn.commit()
            return
        if field == "stage":
            # NEW: log transition + update
            self._on_stage_changed(ro_number, value)
            return
        if field in ("status", "body_tech_name", "painter_name"):
            cur.execute(f"UPDATE records SET {field}=? WHERE ro_number=?", (value, ro_number))
            conn.commit()
            return


class EfficiencyTab(QWidget):
    """
    Efficiency tab:
    - Date range pickers
    - Import Timeclock CSV (worked hours)  → persists into time_clock_records
    - Compute production credits from stage transitions (+ dynamic supplements & overrides)
    - Export Summary CSV

    New:
      • Delete Selected Worked (removes rows from time_clock_records)
      • Delete Selected Credit:
          - Removes matching credit_overrides rows (exact match on RO/from/to/note)
          - Removes matching credit_adjustments rows for "Supplement …" lines
          - Baseline credit rows (Body 60%, Body 40%, Refinish 100%) are not deletable
    """
    BODY_FIRST_SHARE = 0.60   # Body → Paint-or-later
    BODY_FINAL_SHARE = 0.40   # Reassembly → later
    PAINT_PAYOUT     = 1.00   # Paint → later

    def __init__(self):
        super().__init__()
        self._timeclock_rows = []   # kept for compatibility (no longer used for display)
        self._worked_rows = []      # derived from DB by date range

        root = QVBoxLayout(self)

        # --- Controls row ---
        controls = QHBoxLayout()
        controls.addWidget(QLabel("From:"))
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(QDate.currentDate())
        controls.addWidget(self.from_date)

        controls.addWidget(QLabel("To:"))
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(QDate.currentDate())
        controls.addWidget(self.to_date)

        controls.addStretch(1)

        self.btn_import = QPushButton("Import Timeclock CSV")
        self.btn_import.clicked.connect(self._import_timeclock_csv)
        controls.addWidget(self.btn_import)

        self.btn_recalc = QPushButton("Recalculate")
        self.btn_recalc.clicked.connect(self.load_data)
        controls.addWidget(self.btn_recalc)

        self.btn_export = QPushButton("Export CSV…")
        self.btn_export.clicked.connect(self._export_csv)
        controls.addWidget(self.btn_export)

        root.addLayout(controls)

        # --- Worked Hours header row + delete button ---
        worked_hdr = QHBoxLayout()
        worked_hdr.addWidget(QLabel("Worked Hours (from timeclock CSV)"))
        worked_hdr.addStretch(1)
        del_worked_btn = QPushButton("Delete Selected Worked")
        del_worked_btn.clicked.connect(self._delete_selected_worked)
        worked_hdr.addWidget(del_worked_btn)
        root.addLayout(worked_hdr)

        # --- Worked Hours table (from DB) ---
        self.worked_table = QTableWidget()
        self.worked_table.setColumnCount(5)
        self.worked_table.setHorizontalHeaderLabels(["Tech", "Work Date", "Clock In", "Clock Out", "Hours"])
        self.worked_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.worked_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.worked_table)

        # --- Credits header row + delete button ---
        credit_hdr = QHBoxLayout()
        credit_hdr.addWidget(QLabel("Production Credits (from stage transitions)"))
        credit_hdr.addStretch(1)
        del_credit_btn = QPushButton("Delete Selected Credit")
        del_credit_btn.clicked.connect(self._delete_selected_credit)
        credit_hdr.addWidget(del_credit_btn)
        root.addLayout(credit_hdr)

        # --- Production Credits table ---
        self.credit_table = QTableWidget()
        self.credit_table.setColumnCount(7)
        self.credit_table.setHorizontalHeaderLabels(["Date", "RO#", "From Stage", "To Stage", "Tech", "Credit Hours", "Credit Note"])
        self.credit_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.credit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.credit_table)
        self._suppress_credit_item_changed = False
        self.credit_table.itemChanged.connect(self._on_credit_item_changed)

        # --- Summary table ---
        root.addWidget(QLabel("Summary (per technician)"))
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(4)
        self.summary_table.setHorizontalHeaderLabels(["Tech", "Worked Hours", "Credited Hours", "Efficiency %"])
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.summary_table)

        self.load_data()

    # F5 calls this
    def load_data(self):
        self._refresh_worked_rows()                   # <- reads from DB by date range
        self._populate_worked_table(self._worked_rows)

        credits_rows, per_tech_credits = self._calc_credits()
        credits_rows = self._apply_overrides(credits_rows)

        # Re-aggregate credits per tech (post overrides)
        per_tech_credits = {}
        for r in credits_rows:
            t = r.get("tech") or ""
            per_tech_credits[t] = per_tech_credits.get(t, 0.0) + float(r.get("hours") or 0.0)

        self._populate_credit_table(credits_rows)
        self._apply_credit_totals_to_records(credits_rows)

        per_tech_worked = {}
        for r in self._worked_rows:
            per_tech_worked[r["tech"]] = per_tech_worked.get(r["tech"], 0.0) + r["hours"]

        all_techs = sorted(set(per_tech_worked) | set(per_tech_credits))
        summary = []
        for tech in all_techs:
            worked = round(per_tech_worked.get(tech, 0.0), 2)
            credited = round(per_tech_credits.get(tech, 0.0), 2)
            eff = round((credited / worked * 100.0), 1) if worked > 0 else 0.0
            summary.append((tech, worked, credited, eff))
        self._populate_summary_table(summary)

    def _on_credit_item_changed(self, item: QTableWidgetItem):
        if self._suppress_credit_item_changed:
            return
        row, col = item.row(), item.column()
        if col not in (0, 4, 5):  # only Date, Tech, Credit Hours are editable
            return

        ro_item = self.credit_table.item(row, 1)
        from_item = self.credit_table.item(row, 2)
        to_item = self.credit_table.item(row, 3)
        note_item = self.credit_table.item(row, 6)
        if not all([ro_item, from_item, to_item, note_item]):
            return

        ro = (ro_item.text() or "").strip()
        frm = (from_item.text() or "").strip()
        to = (to_item.text() or "").strip()
        note = (note_item.text() or "").strip()

        date_txt = (self.credit_table.item(row, 0).text() or "").strip()
        tech_txt = (self.credit_table.item(row, 4).text() or "").strip()
        hrs_txt = (self.credit_table.item(row, 5).text() or "").strip()

        # validate date / hours
        try:
            datetime.strptime(date_txt, "%m-%d-%Y")
        except Exception:
            QMessageBox.warning(self, "Invalid date", "Use MM-dd-yyyy (e.g., 03-15-2025).")
            self._suppress_credit_item_changed = True
            self.load_data()
            self._suppress_credit_item_changed = False
            return
        try:
            hrs_val = float(hrs_txt) if hrs_txt != "" else 0.0
        except Exception:
            QMessageBox.warning(self, "Invalid number", f"'{hrs_txt}' is not a valid number.")
            self._suppress_credit_item_changed = True
            self.load_data()
            self._suppress_credit_item_changed = False
            return

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO credit_overrides (ro_number, from_stage, to_stage, note, date, tech, hours)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ro_number, from_stage, to_stage, note) DO UPDATE SET
                date = excluded.date,
                tech = excluded.tech,
                hours = excluded.hours
        """, (ro, frm, to, note, date_txt, tech_txt, hrs_val))
        conn.commit()

        self.load_data()

    # ---------- Worked hours (from DB) ----------
    def _refresh_worked_rows(self):
        d_from = parse_date_str(self.from_date.date().toString(DATE_FMT_QT))
        d_to   = parse_date_str(self.to_date.date().toString(DATE_FMT_QT))
        params, clauses = [], []
        if d_from:
            clauses.append("date >= ?")
            params.append(d_from.strftime(DATE_FMT_PY))
        if d_to:
            clauses.append("date <= ?")
            params.append(d_to.strftime(DATE_FMT_PY))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        cur = conn.cursor()
        rows = cur.execute(f"""
            SELECT id, date, tech, clock_in, clock_out, hours
            FROM time_clock_records
            {where}
            ORDER BY date, tech, clock_in
        """, params).fetchall()

        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "tech": r["tech"] or "",
                "date_str": r["date"] or "",
                "in_str": r["clock_in"] or "",
                "out_str": r["clock_out"] or "",
                "hours": float(r["hours"] or 0.0),
            })
        self._worked_rows = out

    def _populate_worked_table(self, rows):
        self.worked_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.worked_table.setItem(i, 0, QTableWidgetItem(r["tech"]))
            self.worked_table.setItem(i, 1, QTableWidgetItem(r["date_str"]))
            self.worked_table.setItem(i, 2, QTableWidgetItem(r["in_str"]))
            self.worked_table.setItem(i, 3, QTableWidgetItem(r["out_str"]))
            self.worked_table.setItem(i, 4, QTableWidgetItem(f"{r['hours']:.2f}"))

    # ---------- Credits ----------
    def _stage_index(self, name: str) -> int:
        try:
            return [s.lower() for s in STAGES].index((name or "").lower())
        except ValueError:
            return -1

    def _is_at_or_after(self, stage_name: str, target_name: str) -> bool:
        return self._stage_index(stage_name) >= self._stage_index(target_name)

    def _is_after(self, stage_name: str, target_name: str) -> bool:
        return self._stage_index(stage_name) > self._stage_index(target_name)

    # Baselines / adjustments helpers unchanged from your current file:
    def _ensure_baseline(self, ro: str, milestone: str, base_hours: float):
        row = conn.execute("SELECT base_hours FROM credit_baseline WHERE ro_number=? AND milestone=?",
                           (ro, milestone)).fetchone()
        if row is None:
            conn.execute("INSERT INTO credit_baseline(ro_number, milestone, base_hours) VALUES (?,?,?)",
                         (ro, milestone, float(base_hours or 0.0)))
            conn.commit()

    def _get_baseline(self, ro: str, milestone: str) -> float:
        row = conn.execute("SELECT base_hours FROM credit_baseline WHERE ro_number=? AND milestone=?",
                           (ro, milestone)).fetchone()
        return float(row["base_hours"]) if row else 0.0

    def _sum_adjusted(self, ro: str, milestone: str) -> float:
        row = conn.execute(
            "SELECT COALESCE(SUM(delta_hours),0) AS s FROM credit_adjustments WHERE ro_number=? AND milestone=?",
            (ro, milestone)).fetchone()
        return float(row["s"] or 0.0)

    def _add_adjustment(self, ro: str, milestone: str, from_stage: str, to_stage: str,
                        tech: str, delta_hours: float, share: float, when_date: str | None = None):
        if abs(delta_hours) < 1e-6:
            return
        when_date = when_date or QDate.currentDate().toString(DATE_FMT_QT)
        conn.execute("""
            INSERT INTO credit_adjustments (ro_number, milestone, from_stage, to_stage, date, tech, delta_hours, share)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ro, milestone, from_stage, to_stage, when_date, tech, float(delta_hours), float(share)))
        conn.commit()

    def _calc_credits(self):
        d_from = parse_date_str(self.from_date.date().toString(DATE_FMT_QT))
        d_to   = parse_date_str(self.to_date.date().toString(DATE_FMT_QT))
        today = QDate.currentDate().toString(DATE_FMT_QT)
        cur = conn.cursor()

        trans = cur.execute("""
            SELECT ro_number, from_stage, to_stage, date
            FROM stage_transitions
            ORDER BY date ASC, id ASC
        """).fetchall()

        by_ro = {}
        for t in trans:
            dt = parse_date_str(t["date"] or "")
            if not dt:
                continue
            # (We evaluate milestones independent of range; we’ll filter via table display and summaries.)
            by_ro.setdefault(t["ro_number"], []).append(t)

        recs = cur.execute("""
            SELECT ro_number, body_hours, paint_hours, body_tech_name, painter_name
            FROM records
        """).fetchall()

        credits_rows = []
        per_tech = {}

        def first_transition_matching(trans_list, frm_name, to_at_least=None, to_after=None):
            for t in trans_list:
                if (t["from_stage"] or "").lower() != frm_name.lower():
                    continue
                to_name = t["to_stage"] or ""
                ok = True
                if to_at_least:
                    ok = ok and self._is_at_or_after(to_name, to_at_least)
                if to_after:
                    ok = ok and self._is_after(to_name, to_after)
                if ok:
                    return t
            return None

        for r in recs:
            ro = r["ro_number"]
            trans_list = by_ro.get(ro, [])
            body_h = float(r["body_hours"] or 0.0)
            paint_h = float(r["paint_hours"] or 0.0)
            bodytech = (r["body_tech_name"] or "").strip()
            painter  = (r["painter_name"] or "").strip()

            # Body 60%
            tA = first_transition_matching(trans_list, "Body", to_at_least="Paint")
            if tA and bodytech and body_h > 0:
                milestone = "body60"; share = self.BODY_FIRST_SHARE
                self._ensure_baseline(ro, milestone, body_h)
                base = self._get_baseline(ro, milestone)
                applied = self._sum_adjusted(ro, milestone)
                unapplied = body_h - (base + applied)
                if abs(unapplied) >= 1e-6:
                    self._add_adjustment(ro, milestone, tA["from_stage"], tA["to_stage"], bodytech, unapplied, share, today)
                base_credit = base * share
                credits_rows.append({
                    "date": tA["date"], "ro": ro,
                    "from": tA["from_stage"], "to": tA["to_stage"],
                    "tech": bodytech, "hours": base_credit,
                    "note": f"Body 60% of {base:.2f}h on Body→{tA['to_stage']}"
                })
                per_tech[bodytech] = per_tech.get(bodytech, 0.0) + base_credit
                for adj in cur.execute("""
                    SELECT date, tech, delta_hours, from_stage, to_stage, share
                    FROM credit_adjustments
                    WHERE ro_number=? AND milestone=?
                    ORDER BY id ASC
                """, (ro, milestone)).fetchall():
                    adj_credit = float(adj["delta_hours"]) * float(adj["share"])
                    sign = "+" if adj["delta_hours"] >= 0 else "-"
                    note = f"Supplement {sign}{abs(float(adj['delta_hours'])):.2f}h (Body 60%)"
                    credits_rows.append({
                        "date": adj["date"], "ro": ro,
                        "from": adj["from_stage"], "to": adj["to_stage"],
                        "tech": adj["tech"] or bodytech, "hours": adj_credit, "note": note
                    })
                    per_tech[adj["tech"] or bodytech] = per_tech.get(adj["tech"] or bodytech, 0.0) + adj_credit

            # Body 40%
            tB = first_transition_matching(trans_list, "Reassembly", to_after="Reassembly")
            if tB and bodytech and body_h > 0:
                milestone = "body40"; share = self.BODY_FINAL_SHARE
                self._ensure_baseline(ro, milestone, body_h)
                base = self._get_baseline(ro, milestone)
                applied = self._sum_adjusted(ro, milestone)
                unapplied = body_h - (base + applied)
                if abs(unapplied) >= 1e-6:
                    self._add_adjustment(ro, milestone, tB["from_stage"], tB["to_stage"], bodytech, unapplied, share, today)
                base_credit = base * share
                credits_rows.append({
                    "date": tB["date"], "ro": ro,
                    "from": tB["from_stage"], "to": tB["to_stage"],
                    "tech": bodytech, "hours": base_credit,
                    "note": f"Body 40% of {base:.2f}h on Reassembly→{tB['to_stage']}"
                })
                per_tech[bodytech] = per_tech.get(bodytech, 0.0) + base_credit
                for adj in cur.execute("""
                    SELECT date, tech, delta_hours, from_stage, to_stage, share
                    FROM credit_adjustments
                    WHERE ro_number=? AND milestone=?
                    ORDER BY id ASC
                """, (ro, milestone)).fetchall():
                    adj_credit = float(adj["delta_hours"]) * float(adj["share"])
                    sign = "+" if adj["delta_hours"] >= 0 else "-"
                    note = f"Supplement {sign}{abs(float(adj['delta_hours'])):.2f}h (Body 40%)"
                    credits_rows.append({
                        "date": adj["date"], "ro": ro,
                        "from": adj["from_stage"], "to": adj["to_stage"],
                        "tech": adj["tech"] or bodytech, "hours": adj_credit, "note": note
                    })
                    per_tech[adj["tech"] or bodytech] = per_tech.get(adj["tech"] or bodytech, 0.0) + adj_credit

            # Paint 100%
            tC = first_transition_matching(trans_list, "Paint", to_after="Paint")
            if tC and painter and paint_h > 0:
                milestone = "paint100"; share = self.PAINT_PAYOUT
                self._ensure_baseline(ro, milestone, paint_h)
                base = self._get_baseline(ro, milestone)
                applied = self._sum_adjusted(ro, milestone)
                unapplied = paint_h - (base + applied)
                if abs(unapplied) >= 1e-6:
                    self._add_adjustment(ro, milestone, tC["from_stage"], tC["to_stage"], painter, unapplied, share, today)
                base_credit = base * share
                credits_rows.append({
                    "date": tC["date"], "ro": ro,
                    "from": tC["from_stage"], "to": tC["to_stage"],
                    "tech": painter, "hours": base_credit,
                    "note": f"Refinish 100% of {base:.2f}h on Paint→{tC['to_stage']}"
                })
                per_tech[painter] = per_tech.get(painter, 0.0) + base_credit
                for adj in cur.execute("""
                    SELECT date, tech, delta_hours, from_stage, to_stage, share
                    FROM credit_adjustments
                    WHERE ro_number=? AND milestone=?
                    ORDER BY id ASC
                """, (ro, milestone)).fetchall():
                    adj_credit = float(adj["delta_hours"]) * float(adj["share"])
                    sign = "+" if adj["delta_hours"] >= 0 else "-"
                    note = f"Supplement {sign}{abs(float(adj['delta_hours'])):.2f}h (Refinish 100%)"
                    credits_rows.append({
                        "date": adj["date"], "ro": ro,
                        "from": adj["from_stage"], "to": adj["to_stage"],
                        "tech": adj["tech"] or painter, "hours": adj_credit, "note": note
                    })
                    per_tech[adj["tech"] or painter] = per_tech.get(adj["tech"] or painter, 0.0) + adj_credit

        credits_rows.sort(key=lambda x: (parse_date_str(x["date"]) or datetime.min.date(), x["ro"]))
        return credits_rows, per_tech

    def _on_stage_changed(self, ro_number: str, new_stage: str):
        """When stage changes, log a transition row and update the record."""
        cur = conn.cursor()
        row = cur.execute("SELECT stage FROM records WHERE ro_number=?", (ro_number,)).fetchone()
        old_stage = row["stage"] if row else None
        if not old_stage or old_stage == new_stage:
            return  # nothing to do

        # Date the transition as 'today' (MM-dd-yyyy)
        today_str = QDate.currentDate().toString(DATE_FMT_QT)
        cur.execute(
            "INSERT INTO stage_transitions (ro_number, from_stage, to_stage, date) VALUES (?, ?, ?, ?)",
            (ro_number, old_stage, new_stage, today_str),
        )

        # Update the record’s stage
        cur.execute("UPDATE records SET stage=? WHERE ro_number=?", (new_stage, ro_number))
        conn.commit()

    def _populate_credit_table(self, rows):
        self._suppress_credit_item_changed = True
        self.credit_table.setRowCount(len(rows))
        def make_item(text, editable=False):
            it = QTableWidgetItem(text)
            flags = it.flags()
            if not editable:
                it.setFlags(flags & ~Qt.ItemIsEditable)
            else:
                it.setFlags(flags | Qt.ItemIsEditable)
            return it
        for i, r in enumerate(rows):
            self.credit_table.setItem(i, 0, make_item(r["date"], editable=True))            # Date
            self.credit_table.setItem(i, 1, make_item(r["ro"]))                              # RO
            self.credit_table.setItem(i, 2, make_item(r["from"]))                            # From Stage
            self.credit_table.setItem(i, 3, make_item(r["to"]))                              # To Stage
            self.credit_table.setItem(i, 4, make_item(r["tech"], editable=True))            # Tech
            self.credit_table.setItem(i, 5, make_item(f"{r['hours']:.2f}", editable=True))  # Credit Hours
            self.credit_table.setItem(i, 6, make_item(r["note"]))                            # Note
        self._suppress_credit_item_changed = False

    def _populate_summary_table(self, rows):
        self.summary_table.setRowCount(len(rows))
        for i, (tech, worked, credited, eff) in enumerate(rows):
            self.summary_table.setItem(i, 0, QTableWidgetItem(tech))
            self.summary_table.setItem(i, 1, QTableWidgetItem(f"{worked:.2f}"))
            self.summary_table.setItem(i, 2, QTableWidgetItem(f"{credited:.2f}"))
            self.summary_table.setItem(i, 3, QTableWidgetItem(f"{eff:.1f}%"))

    def _apply_overrides(self, credits_rows):
        cur = conn.cursor()
        out = []
        for r in credits_rows:
            ro, frm, to, note = r["ro"], r["from"], r["to"], r["note"]
            ov = cur.execute("""
                SELECT date, tech, hours
                FROM credit_overrides
                WHERE ro_number=? AND from_stage=? AND to_stage=? AND note=?
            """, (ro, frm, to, note)).fetchone()
            if ov:
                r = dict(r)
                if ov["date"] is not None and str(ov["date"]).strip():
                    r["date"] = ov["date"]
                if ov["tech"] is not None and str(ov["tech"]).strip():
                    r["tech"] = ov["tech"]
                if ov["hours"] is not None:
                    r["hours"] = float(ov["hours"] or 0.0)
            out.append(r)
        return out

    def _apply_credit_totals_to_records(self, credits_rows):
        totals = {}
        for r in credits_rows:
            ro = r.get("ro") or ""
            h = float(r.get("hours") or 0.0)
            totals[ro] = totals.get(ro, 0.0) + h
        cur = conn.cursor()
        for ro, total in totals.items():
            cur.execute("UPDATE records SET hours_taken=? WHERE ro_number=?", (round(total, 2), ro))
        conn.commit()

    # ---------- Delete handlers ----------
    def _delete_selected_worked(self):
        rows = self.worked_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "No selection", "Select one or more worked rows to delete.")
            return
        if QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {len(rows)} worked time entry(ies)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return

        cur = conn.cursor()
        deleted = 0
        for model_idx in rows:
            r = model_idx.row()
            tech = (self.worked_table.item(r, 0).text() or "").strip()
            date_str = (self.worked_table.item(r, 1).text() or "").strip()
            clock_in = (self.worked_table.item(r, 2).text() or "").strip()
            clock_out = (self.worked_table.item(r, 3).text() or "").strip()

            # Delete exact matching row (first match)
            row_id = cur.execute("""
                SELECT id FROM time_clock_records
                WHERE date=? AND tech=? AND clock_in=? AND clock_out=?
                ORDER BY id LIMIT 1
            """, (date_str, tech, clock_in, clock_out)).fetchone()
            if row_id:
                cur.execute("DELETE FROM time_clock_records WHERE id=?", (row_id["id"],))
                deleted += 1
        conn.commit()
        self.load_data()
        QMessageBox.information(self, "Deleted", f"Removed {deleted} worked row(s).")

    def _delete_selected_credit(self):
        rows = self.credit_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "No selection", "Select one or more credit rows to delete.")
            return
        if QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {len(rows)} credit row(s)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return

        cur = conn.cursor()
        deleted = 0
        skipped_baseline = 0
        not_found = 0

        for model_idx in rows:
            r = model_idx.row()
            date_txt = (self.credit_table.item(r, 0).text() or "").strip()
            ro       = (self.credit_table.item(r, 1).text() or "").strip()
            frm      = (self.credit_table.item(r, 2).text() or "").strip()
            to       = (self.credit_table.item(r, 3).text() or "").strip()
            tech     = (self.credit_table.item(r, 4).text() or "").strip()
            hrs_txt  = (self.credit_table.item(r, 5).text() or "").strip()
            note     = (self.credit_table.item(r, 6).text() or "").strip()

            # 1) Baseline rows are not deletable
            if note.startswith("Body 60%") or note.startswith("Body 40%") or note.startswith("Refinish 100%"):
                skipped_baseline += 1
                continue

            # 2) "Supplement ±X.XXh (Milestone)" → delete matching credit_adjustments row
            if note.startswith("Supplement "):
                # Determine milestone & share
                if "(Body 60%)" in note:
                    milestone = "body60"; share = self.BODY_FIRST_SHARE
                elif "(Body 40%)" in note:
                    milestone = "body40"; share = self.BODY_FINAL_SHARE
                elif "(Refinish 100%)" in note:
                    milestone = "paint100"; share = self.PAINT_PAYOUT
                else:
                    milestone = None; share = None

                try:
                    hours_val = float(hrs_txt)
                except Exception:
                    hours_val = None

                deleted_adj = 0
                if milestone and share and hours_val is not None:
                    # delta_hours = credited / share (sign derived from note text)
                    # Note already encodes sign via the hours value we display (positive or negative after share).
                    # But our table shows positive hours; we need the original delta sign from "Supplement ±".
                    # We'll infer sign from the word after "Supplement ".
                    sign = -1.0 if "Supplement -" in note else 1.0
                    delta = (abs(hours_val) / share) * sign

                    deleted_adj = cur.execute("""
                        DELETE FROM credit_adjustments
                        WHERE ro_number=? AND milestone=? AND from_stage=? AND to_stage=? AND date=? AND
                              (tech=? OR (tech IS NULL AND ?='')) AND
                              ABS(delta_hours - ?) < 1e-5
                    """, (ro, milestone, frm, to, date_txt, tech, tech, float(delta))).rowcount
                    if deleted_adj:
                        deleted += deleted_adj
                        continue  # go next selected row

                # If we couldn't infer or didn't match, fall through and try override deletion

            # 3) Try override deletion (exact RO/from/to/note match)
            deleted_ov = cur.execute("""
                DELETE FROM credit_overrides
                WHERE ro_number=? AND from_stage=? AND to_stage=? AND note=?
            """, (ro, frm, to, note)).rowcount
            if deleted_ov:
                deleted += deleted_ov
            else:
                not_found += 1

        conn.commit()
        self.load_data()

        msg_parts = []
        if deleted:
            msg_parts.append(f"Removed {deleted} credit row(s).")
        if skipped_baseline:
            msg_parts.append(f"Skipped {skipped_baseline} baseline row(s) (cannot delete baseline credits).")
        if not_found:
            msg_parts.append(f"{not_found} row(s) did not match any deletable override/supplement.")
        QMessageBox.information(self, "Delete Credits", "\n".join(msg_parts) if msg_parts else "No changes.")

    # ---------- CSV Import / Export ----------
    def _import_timeclock_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Timeclock CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        try:
            with open(path, "r", newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                header_map = { (h or "").strip().lower(): h for h in (reader.fieldnames or []) }

                def pick(*cands):
                    for c in cands:
                        if c in header_map:
                            return header_map[c]
                    return None

                col_tech = pick("tech", "technician", "employee", "name")
                col_date = pick("date", "work date", "day")
                col_in   = pick("in", "clock in", "start", "time in", "punch in")
                col_out  = pick("out", "clock out", "end", "time out", "punch out")
                if not all([col_tech, col_date, col_in, col_out]):
                    QMessageBox.warning(self, "CSV Error",
                        "Missing required columns (tech/name, date, in, out).")
                    return

                cur = conn.cursor()
                inserted = 0
                for raw in reader:
                    tech = (raw.get(col_tech, "") or "").strip()
                    date_raw = (raw.get(col_date, "") or "").strip()
                    in_raw   = (raw.get(col_in, "") or "").strip()
                    out_raw  = (raw.get(col_out, "") or "").strip()

                    date_str = self._normalize_date(date_raw)
                    in_str   = self._normalize_time(in_raw)
                    out_str  = self._normalize_time(out_raw)
                    if not (date_str and in_str and out_str and tech):
                        continue

                    hours = self._hours_between(in_str, out_str)
                    cur.execute("""
                        INSERT INTO time_clock_records (date, tech, clock_in, clock_out, hours)
                        VALUES (?, ?, ?, ?, ?)
                    """, (date_str, tech, in_str, out_str, float(hours)))
                    inserted += 1

                conn.commit()
            QMessageBox.information(self, "Import Complete", f"Imported {inserted} time entry(ies).")
            self.load_data()
        except Exception as e:
            QMessageBox.warning(self, "Import Failed", f"{e}")

    def _export_csv(self):
        choice, ok = QInputDialog.getItem(
            self,
            "Export CSV",
            "Which section would you like to export?",
            ["Worked Hours", "Production Credits", "Summary", "All three"],
            0,
            False
        )
        if not ok or not choice:
            return

        def _headers_of(table):
            return [
                (table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else f"Column {c + 1}")
                for c in range(table.columnCount())
            ]

        def _write_table_to_csv(table, path):
            try:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(_headers_of(table))
                    for r in range(table.rowCount()):
                        row = []
                        for c in range(table.columnCount()):
                            item = table.item(r, c)
                            row.append(item.text() if item else "")
                        writer.writerow(row)
                return True, None
            except Exception as e:
                return False, str(e)

        if choice != "All three":
            default_name = {
                "Worked Hours": "efficiency_worked.csv",
                "Production Credits": "efficiency_credits.csv",
                "Summary": "efficiency_summary.csv",
            }.get(choice, "export.csv")

            path, _ = QFileDialog.getSaveFileName(
                self, f"Export {choice} CSV", default_name, "CSV Files (*.csv)"
            )
            if not path:
                return

            table = {
                "Worked Hours": self.worked_table,
                "Production Credits": self.credit_table,
                "Summary": self.summary_table,
            }[choice]

            ok, err = _write_table_to_csv(table, path)
            if ok:
                QMessageBox.information(self, "Exported", f"Saved: {path}")
            else:
                QMessageBox.warning(self, "Export Failed", err or "Unknown error")
            return

        folder = QFileDialog.getExistingDirectory(self, "Select Folder for CSV Exports")
        if not folder:
            return

        exports = [
            (self.worked_table, os.path.join(folder, "efficiency_worked.csv")),
            (self.credit_table, os.path.join(folder, "efficiency_credits.csv")),
            (self.summary_table, os.path.join(folder, "efficiency_summary.csv")),
        ]

        failures = []
        for table, out_path in exports:
            ok, err = _write_table_to_csv(table, out_path)
            if not ok:
                failures.append((out_path, err))

        if not failures:
            QMessageBox.information(
                self,
                "Exported",
                "Saved:\n- efficiency_worked.csv\n- efficiency_credits.csv\n- efficiency_summary.csv"
            )
        else:
            msg = "Some files failed:\n" + "\n".join([f"{p} → {e}" for p, e in failures])
            QMessageBox.warning(self, "Partial Export", msg)

    # ---------- Time parsing helpers ----------
    def _normalize_date(self, s: str) -> str | None:
        s = (s or "").strip()
        fmts = ["%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"]
        for fmt in fmts:
            try:
                return datetime.strptime(s, fmt).strftime(DATE_FMT_PY)
            except Exception:
                pass
        return None

    def _normalize_time(self, s: str) -> str | None:
        s = (s or "").strip().upper().replace(" ", "")
        fmts = ["%I:%M%p", "%I:%M:%S%p", "%H:%M", "%H:%M:%S"]
        for fmt in fmts:
            try:
                t = datetime.strptime(s, fmt).time()
                return t.strftime("%H:%M")
            except Exception:
                pass
        return None

    def _hours_between(self, in_str: str, out_str: str) -> float:
        t_in = datetime.strptime(in_str, "%H:%M")
        t_out = datetime.strptime(out_str, "%H:%M")
        if t_out < t_in:  # overnight shift support
            t_out = t_out.replace(day=t_out.day + 1)
        delta = (t_out - t_in)
        return max(0.0, round(delta.seconds / 3600.0, 2))

class SettingsTab(QWidget):
    settings_changed = Signal(dict)
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout()

        stage_col = QVBoxLayout()
        stage_col.addWidget(QLabel("Stages"))
        self.stage_list = QListWidget();
        self.stage_list.addItems(STAGES);
        stage_col.addWidget(self.stage_list)
        add_stage = QPushButton("Add Stage")
        rename_stage = QPushButton("Rename Selected")
        rem_stage = QPushButton("Remove Selected")
        save_stage = QPushButton("Save Stages")
        add_stage.clicked.connect(self._add_stage)
        rename_stage.clicked.connect(self._rename_stage)
        rem_stage.clicked.connect(lambda: [self.stage_list.takeItem(self.stage_list.row(i)) for i in self.stage_list.selectedItems()])
        save_stage.clicked.connect(self._save_stages)
        for b in (add_stage, rename_stage, rem_stage, save_stage):
            stage_col.addWidget(b)

        status_col = QVBoxLayout()
        status_col.addWidget(QLabel("Statuses"))
        self.status_list = QListWidget();
        self.status_list.addItems(STATUSES);
        status_col.addWidget(self.status_list)
        add_status = QPushButton("Add Status")
        rename_status = QPushButton("Rename Selected")
        rem_status = QPushButton("Remove Selected")
        save_status = QPushButton("Save Statuses")
        add_status.clicked.connect(self._add_status)
        rename_status.clicked.connect(self._rename_status)
        rem_status.clicked.connect(lambda: [self.status_list.takeItem(self.status_list.row(i)) for i in self.status_list.selectedItems()])
        save_status.clicked.connect(self._save_statuses)
        for b in (add_status, rename_status, rem_status, save_status):
            status_col.addWidget(b)

        tech_col = QVBoxLayout()
        tech_col.addWidget(QLabel("Technicians"))
        self.tech_list = QListWidget()
        self._load_techs_list()
        tech_col.addWidget(self.tech_list)

        add_tech = QPushButton("Add Tech")
        rename_tech = QPushButton("Rename Selected")
        rem_tech = QPushButton("Remove Selected")
        save_techs = QPushButton("Save Techs")

        add_tech.clicked.connect(self._add_tech)
        rename_tech.clicked.connect(self._rename_tech)
        rem_tech.clicked.connect(self._remove_selected_techs)
        save_techs.clicked.connect(self._save_techs)

        for b in (add_tech, rename_tech, rem_tech, save_techs):
            tech_col.addWidget(b)

        layout.addLayout(stage_col)
        layout.addSpacing(24)
        layout.addLayout(status_col)
        layout.addLayout(stage_col)
        layout.addSpacing(24)
        layout.addLayout(status_col)
        layout.addSpacing(24)
        layout.addLayout(tech_col)
        self.setLayout(layout)

    def _save_stages(self):
        global STAGES
        items = [self.stage_list.item(i).text().strip() for i in range(self.stage_list.count()) if
                 self.stage_list.item(i).text().strip()]
        save_list_to_file(STAGES_FILE, items)
        STAGES = items[:]  # update in-memory immediately
        QMessageBox.information(self, "Saved", "Stages saved and applied.")
        self.settings_changed.emit({"stages": STAGES})

    def _save_statuses(self):
        global STATUSES
        items = [self.status_list.item(i).text().strip() for i in range(self.status_list.count()) if
                 self.status_list.item(i).text().strip()]
        save_list_to_file(STATUSES_FILE, items)
        STATUSES = items[:]  # update in-memory immediately
        QMessageBox.information(self, "Saved", "Statuses saved and applied.")
        self.settings_changed.emit({"statuses": STATUSES})

    def _add_stage(self):
        text, ok = QInputDialog.getText(self, "Add Stage", "Enter stage name:")
        name = text.strip()
        if not ok or not name:
            return
        existing = {self.stage_list.item(i).text().strip().lower() for i in range(self.stage_list.count())}
        if name.lower() in existing:
            QMessageBox.information(self, "Duplicate", f"'{name}' already exists.")
            return
        self.stage_list.addItem(name)

    def _rename_stage(self):
        items = self.stage_list.selectedItems()
        if not items:
            QMessageBox.information(self, "No selection", "Select a stage to rename.")
            return
        current = items[0].text()
        text, ok = QInputDialog.getText(self, "Rename Stage", "New name:", text=current)
        name = text.strip()
        if not ok or not name:
            return
        existing = {self.stage_list.item(i).text().strip().lower() for i in range(self.stage_list.count())}
        existing.discard(current.strip().lower())  # allow unchanged
        if name.lower() in existing:
            QMessageBox.information(self, "Duplicate", f"'{name}' already exists.")
            return
        items[0].setText(name)

    def _add_status(self):
        text, ok = QInputDialog.getText(self, "Add Status", "Enter status name:")
        name = text.strip()
        if not ok or not name:
            return
        existing = {self.status_list.item(i).text().strip().lower() for i in range(self.status_list.count())}
        if name.lower() in existing:
            QMessageBox.information(self, "Duplicate", f"'{name}' already exists.")
            return
        self.status_list.addItem(name)

    def _rename_status(self):
        items = self.status_list.selectedItems()
        if not items:
            QMessageBox.information(self, "No selection", "Select a status to rename.")
            return
        current = items[0].text()
        text, ok = QInputDialog.getText(self, "Rename Status", "New name:", text=current)
        name = text.strip()
        if not ok or not name:
            return
        existing = {self.status_list.item(i).text().strip().lower() for i in range(self.status_list.count())}
        existing.discard(current.strip().lower())
        if name.lower() in existing:
            QMessageBox.information(self, "Duplicate", f"'{name}' already exists.")
            return
        items[0].setText(name)

    def _load_techs_list(self):
        self.tech_list.clear()
        cur = conn.cursor()
        for (name,) in cur.execute("SELECT name FROM technicians ORDER BY name").fetchall():
            self.tech_list.addItem(name)

    def _add_tech(self):
        text, ok = QInputDialog.getText(self, "Add Technician", "Enter tech name:")
        name = text.strip()
        if not ok or not name:
            return
        existing = {self.tech_list.item(i).text().strip().lower() for i in range(self.tech_list.count())}
        if name.lower() in existing:
            QMessageBox.information(self, "Duplicate", f"'{name}' already exists.")
            return
        self.tech_list.addItem(name)

    def _rename_tech(self):
        items = self.tech_list.selectedItems()
        if not items:
            QMessageBox.information(self, "No selection", "Select a tech to rename.")
            return
        current = items[0].text()
        text, ok = QInputDialog.getText(self, "Rename Technician", "New name:", text=current)
        name = text.strip()
        if not ok or not name:
            return
        existing = {self.tech_list.item(i).text().strip().lower() for i in range(self.tech_list.count())}
        existing.discard(current.strip().lower())  # allow unchanged
        if name.lower() in existing:
            QMessageBox.information(self, "Duplicate", f"'{name}' already exists.")
            return
        items[0].setText(name)

    def _remove_selected_techs(self):
        items = self.tech_list.selectedItems()
        if not items:
            return
        if QMessageBox.question(
                self, "Remove",
                f"Remove {len(items)} technician(s) from list? (Will apply on Save)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        for it in items:
            self.tech_list.takeItem(self.tech_list.row(it))

    def _save_techs(self):
        names = [
            self.tech_list.item(i).text().strip()
            for i in range(self.tech_list.count())
            if self.tech_list.item(i).text().strip()
        ]
        # Replace technicians table with current list
        cur = conn.cursor()
        cur.execute("DELETE FROM technicians")
        for n in names:
            cur.execute("INSERT OR IGNORE INTO technicians(name) VALUES (?)", (n,))
        conn.commit()
        QMessageBox.information(self, "Saved", "Technicians saved and applied.")
        self.settings_changed.emit({"techs": names})


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Production & Technician Work Tracker")
        self.resize(1150, 740)

        self.tabs = QTabWidget()
        self.dashboard = DashboardTab()
        self.add_entry = AddEntryTab()
        self.view_records = ViewRecordsTab()
        self.efficiency = EfficiencyTab()
        self.settings = SettingsTab()
        self.settings.settings_changed.connect(self._apply_live_settings)

        self.tabs.addTab(self.dashboard, "Dashboard")
        self.tabs.addTab(self.add_entry, "Add Entry")
        self.tabs.addTab(self.view_records, "View Records")
        self.tabs.addTab(self.efficiency, "Efficiency")
        self.tabs.addTab(self.settings, "Settings")
        self.setCentralWidget(self.tabs)

        # F5 = refresh current tab
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_current_tab)

    def _apply_live_settings(self, payload: dict):
        """
        payload may contain keys: 'stages', 'statuses', 'techs'
        We refresh the right places without restarting.
        """
        # If stages changed: dashboard counts, records stage dropdowns, and efficiency logic
        if "stages" in payload:
            # Rebuild all stage-dependent views
            if hasattr(self.dashboard, "load_data"): self.dashboard.load_data()
            if hasattr(self.view_records, "load_data"): self.view_records.load_data()
            if hasattr(self.efficiency, "load_data"): self.efficiency.load_data()

        # If statuses changed: Add Entry status dropdown and Records status dropdowns
        if "statuses" in payload:
            if hasattr(self.add_entry, "_reload_statuses"): self.add_entry._reload_statuses()
            if hasattr(self.view_records, "load_data"): self.view_records.load_data()

        # If techs changed: Add Entry tech dropdowns and Records tech dropdowns
        if "techs" in payload:
            if hasattr(self.add_entry, "_load_techs"): self.add_entry._load_techs()
            if hasattr(self.view_records, "load_data"): self.view_records.load_data()

    def refresh_current_tab(self):
        idx = self.tabs.currentIndex()
        widget = self.tabs.widget(idx)
        if hasattr(widget, "load_data"):
            widget.load_data()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
