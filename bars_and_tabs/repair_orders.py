from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QDateEdit,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QDialog, QFormLayout, QLineEdit, QMessageBox, QAbstractItemView, QSizePolicy
)
from PySide6.QtCore import QDate, QDateTime
from database import get_connection
from key_bindings import add_refresh_shortcut
from utilities.delete_button import delete_with_confirmation
from utilities.safe_combobox import SafeComboBox
from utilities.employees import Employee


def log_stage_change(ro_id, stage):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ro_stage_history (ro_id, stage, date) VALUES (?, ?, ?)",
            (ro_id, stage, QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm AP"))
        )


# resolve full name function
def resolve_full(role, chosen_display):
    for e in Employee.by_role(role):
        if (e.nickname or e.name) == chosen_display:
            return e.name
    return chosen_display  # fallback if no match


class RepairOrdersPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # --- Row 1: Top buttons + search ---
        top_layout = QHBoxLayout()
        self.new_ro_btn = QPushButton("New RO")
        self.new_ro_btn.clicked.connect(self.open_new_ro_dialog)
        top_layout.addWidget(self.new_ro_btn)

        self.delete_ro_btn = QPushButton("Delete RO")
        self.delete_ro_btn.clicked.connect(self.delete_selected_ro)
        top_layout.addWidget(self.delete_ro_btn)

        top_layout.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("RO#, Estimator, Tech, Painter, Mechanic")
        self.search_box.textChanged.connect(self.load_data)
        top_layout.addWidget(self.search_box, stretch=1)

        self.show_all_btn = QPushButton("Show All")
        self.show_all_btn.clicked.connect(self.show_all)
        top_layout.addWidget(self.show_all_btn)

        layout.addLayout(top_layout)

        # --- Row 2: Filters ---
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(4)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        today = QDate.currentDate()
        ninety_days_ago = today.addDays(-90)

        # From label + date
        from_label = QLabel("From:")
        from_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        filter_layout.addWidget(from_label)

        self.date_from = QDateEdit()
        self.date_from.setDisplayFormat("MM/dd/yyyy")
        self.date_from.setCalendarPopup(True)
        self.date_from.setDateRange(QDate(1900, 1, 1), QDate(2100, 12, 31))
        self.date_from.setDate(ninety_days_ago)
        self.date_from.setSpecialValueText("")
        filter_layout.addWidget(self.date_from)

        # To label + date
        to_label = QLabel("To:")
        to_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        filter_layout.addWidget(to_label)

        self.date_to = QDateEdit()
        self.date_to.setDisplayFormat("MM/dd/yyyy")
        self.date_to.setCalendarPopup(True)
        self.date_to.setDateRange(QDate(1900, 1, 1), QDate(2100, 12, 31))
        self.date_to.setDate(today)
        self.date_to.setSpecialValueText("")
        filter_layout.addWidget(self.date_to)

        # Apply Filter button
        self.apply_filter_btn = QPushButton("Apply Filter")
        self.apply_filter_btn.clicked.connect(self.apply_filter)
        filter_layout.addWidget(self.apply_filter_btn)

        # Show Closed checkbox
        self.show_closed_cb = QCheckBox("Show Closed")
        self.show_closed_cb.stateChanged.connect(self.load_data)
        filter_layout.addWidget(self.show_closed_cb)

        layout.addLayout(filter_layout)
        self.date_filter_enabled = True

        # --- Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Date", "RO#", "Estimator", "Tech", "Painter", "Mechanic", "Stage", "Status"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.open_ro_detail_dialog)
        self.table.verticalHeader().setVisible(False)

        layout.addWidget(self.table)

        self.load_data()
        add_refresh_shortcut(self, self.load_data)

    def load_statuses(self):
        return ["Open", "On Hold", "Closed"]

    def load_stages(self):
        return [
            "Scheduled", "Intake", "Disassembly", "Body", "Refinish",
            "Reassembly", "Mechanical", "Detail", "QC", "Delivered"
        ]

    def update_field(self, ro_id, field, value):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE repair_orders SET {field}=? WHERE id=?", (value, ro_id))

    def show_all(self):
        """Clear search + remove date limits (respect Show Closed)."""
        self.search_box.clear()
        self.date_filter_enabled = False
        self.load_data()

    def apply_filter(self):
        """Apply the current from/to date range."""
        self.date_filter_enabled = True
        self.load_data()

    def clear_date_filter(self):
        today = QDate.currentDate()
        ninety_days_ago = today.addDays(-90)
        self.date_from.setDate(ninety_days_ago)
        self.date_to.setDate(today)
        self.load_data()

    def open_new_ro_dialog(self):
        dialog = NewRODialog(self)
        if dialog.exec():
            self.load_data()

    def open_ro_detail_dialog(self, row, column):
        header_item = self.table.verticalHeaderItem(row)
        if not header_item:
            return
        ro_id = int(header_item.text())
        dialog = RODetailDialog(ro_id, self)
        dialog.exec()
        self.load_data()

    def delete_selected_ro(self):
        selected_rows = self.table.selectionModel().selectedRows()
        ids = []
        for idx in selected_rows:
            header_item = self.table.verticalHeaderItem(idx.row())
            if header_item:
                ids.append(int(header_item.text()))

        if not ids:
            QMessageBox.warning(self, "No Selection", "Please select at least one RO to delete.")
            return

        # Confirmation
        if len(ids) == 1:
            msg = f"Are you sure you want to delete RO ID {ids[0]} and all its linked credits?"
        else:
            msg = f"Are you sure you want to delete {len(ids)} ROs and all their linked credits?"

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            msg,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Delete ROs and their credits
        with get_connection() as conn:
            cursor = conn.cursor()
            for rid in ids:
                cursor.execute("SELECT ro_number FROM repair_orders WHERE id=?", (rid,))
                row = cursor.fetchone()
                if row:
                    (ro_number,) = row
                    cursor.execute("DELETE FROM credit_audit WHERE ro_number=?", (ro_number,))
                cursor.execute("DELETE FROM repair_orders WHERE id=?", (rid,))

        QMessageBox.information(
            self,
            "Deleted",
            f"Deleted {len(ids)} RO(s) and associated credits."
        )

        # Refresh UI
        self.load_data()

        # 🔑 Ensure reports tabs update too
        try:
            from reports import ReportsPage
            # If you already have an instance of ReportsPage in your app, trigger refresh
            # This depends on how you're instantiating pages; a direct reference to that
            # tab widget can call .load_data() on its children
        except ImportError:
            pass

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            query = """SELECT r.id, \
                              r.date, \
                              r.ro_number, \
                              r.estimator_id, \
                              r.stage, \
                              r.status,
                              e.full_name, \
                              e.nickname
                       FROM repair_orders r
                                LEFT JOIN employees e ON r.estimator_id = e.id
                       WHERE 1 = 1"""
            params = []

            # --- Status filter ---
            if not self.show_closed_cb.isChecked():
                query += " AND r.status != ?"
                params.append("Closed")

            # --- Text search filter ---
            text = self.search_box.text().strip()
            if text:
                like = f"%{text}%"
                query += """ AND (
                    CAST(r.ro_number AS TEXT) LIKE ?
                    OR e.full_name LIKE ?
                    OR e.nickname LIKE ?
                    OR r.status LIKE ?
                    OR r.stage LIKE ?
                )"""
                params.extend([like] * 5)

            # --- Date range filter ---
            if self.date_filter_enabled:
                from_date = self.date_from.date()
                to_date = self.date_to.date()
                if from_date.isValid() and to_date.isValid():
                    query += " AND r.date >= ? AND r.date <= ?"
                    params.append(from_date.toString("yyyy-MM-dd"))
                    params.append(to_date.toString("yyyy-MM-dd"))

            # --- Order ---
            query += " ORDER BY r.ro_number"
            cursor.execute(query, params)
            rows = cursor.fetchall()

        # --- Populate table ---
        self.table.setRowCount(len(rows))
        statuses = self.load_statuses()
        stages = self.load_stages()

        for row_index, (ro_id, date, ro_number, estimator_id, stage, status, full_name, nickname) in enumerate(rows):
            date_str = QDate.fromString(date, "yyyy-MM-dd").toString("MM/dd/yyyy")
            estimator_display = nickname or full_name or "Unassigned"

            self.table.setItem(row_index, 0, QTableWidgetItem(date_str))
            self.table.setItem(row_index, 1, QTableWidgetItem(str(ro_number)))
            self.table.setItem(row_index, 2, QTableWidgetItem(estimator_display))

            # Placeholder for allocations summary (instead of Tech/Painter/Mech cols)
            self.table.setItem(row_index, 3, QTableWidgetItem("See Allocations"))

            # Stage combobox
            stage_cb = SafeComboBox()
            stage_cb.addItems(stages)
            if stage:
                stage_cb.setCurrentText(stage)
            self.table.setCellWidget(row_index, 6, stage_cb)
            stage_cb.currentTextChanged.connect(
                lambda value, rid=ro_id: (
                    self.update_field(rid, "stage", value),
                    log_stage_change(rid, value),
                    update_ro_hours(rid)
                )
            )

            # Status combobox
            status_cb = SafeComboBox()
            status_cb.addItems(statuses)
            if status:
                status_cb.setCurrentText(status)
            self.table.setCellWidget(row_index, 7, status_cb)
            status_cb.currentTextChanged.connect(
                lambda value, rid=ro_id: (
                    self.update_field(rid, "status", value),
                    apply_uncredited_hours(rid) if value == "Closed" else None
                )
            )

            self.table.setVerticalHeaderItem(row_index, QTableWidgetItem(str(ro_id)))


class NewRODialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Repair Order")

        layout = QFormLayout(self)

        # Date as dropdown calendar
        self.date_field = QDateEdit()
        self.date_field.setDisplayFormat("MM/dd/yyyy")
        self.date_field.setCalendarPopup(True)
        self.date_field.setDate(QDate.currentDate())

        # Dropdowns for people
        self.estimator_field = SafeComboBox()
        self.tech_field = SafeComboBox()
        self.painter_field = SafeComboBox()
        self.mechanic_field = SafeComboBox()

        # Load employees dynamically by role
        estimators = [e.nickname or e.name for e in Employee.by_role("Estimator")]
        techs = [e.nickname or e.name for e in Employee.by_role("Tech")]
        painters = [e.nickname or e.name for e in Employee.by_role("Painter")]
        mechanics = [e.nickname or e.name for e in Employee.by_role("Mechanic")]

        self.estimator_field.addItems(estimators)

        self.tech_field.addItem("Unassigned")
        self.tech_field.addItems(techs)

        self.painter_field.addItem("Unassigned")
        self.painter_field.addItems(painters)

        self.mechanic_field.addItem("Unassigned")
        self.mechanic_field.addItems(mechanics)

        # Other editable fields
        self.ro_number_field = QLineEdit()
        self.ro_hours_field = QLineEdit()
        self.body_hours_field = QLineEdit()
        self.refinish_hours_field = QLineEdit()
        self.mechanical_hours_field = QLineEdit()

        # Add to layout
        layout.addRow("Date:", self.date_field)
        layout.addRow("RO Number:*", self.ro_number_field)
        layout.addRow("Estimator:*", self.estimator_field)
        layout.addRow("Tech:", self.tech_field)
        layout.addRow("Painter:", self.painter_field)
        layout.addRow("Mechanic:", self.mechanic_field)
        layout.addRow("RO Hours:", self.ro_hours_field)
        layout.addRow("Body Hours:", self.body_hours_field)
        layout.addRow("Refinish Hours:", self.refinish_hours_field)
        layout.addRow("Mechanical Hours:", self.mechanical_hours_field)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save)
        layout.addRow(save_btn)

    def save(self):
        if not self.ro_number_field.text():
            QMessageBox.warning(self, "Error", "RO Number is required.")
            return
        if not self.estimator_field.currentText():
            QMessageBox.warning(self, "Error", "Estimator is required.")
            return

        estimator_full = resolve_full("Estimator", self.estimator_field.currentText())
        tech_full = resolve_full("Tech", self.tech_field.currentText())
        painter_full = resolve_full("Painter", self.painter_field.currentText())
        mech_full = resolve_full("Mechanic", self.mechanic_field.currentText())

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO repair_orders
                (date, ro_number, estimator, tech, painter, mechanic,
                ro_hours, body_hours, refinish_hours, mechanical_hours,
                hours_taken, hours_remaining, status, stage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.date_field.date().toString("yyyy-MM-dd"),
                    int(self.ro_number_field.text()),
                    estimator_full,
                    tech_full or "Unassigned",
                    painter_full or "Unassigned",
                    mech_full or "Unassigned",
                    float(self.ro_hours_field.text() or 0),
                    float(self.body_hours_field.text() or 0),
                    float(self.refinish_hours_field.text() or 0),
                    float(self.mechanical_hours_field.text() or 0),
                    0.0,  # hours_taken
                    0.0,  # hours_remaining
                    "Open",  # default status
                    "Intake"  # default stage
                ),
            )

        QMessageBox.information(self, "Success", "Repair order added.")
        self.accept()

# --- Open RO details window ---
class RODetailDialog(QDialog):
    def __init__(self, ro_id, parent=None):
        super().__init__(parent)
        self.ro_id = ro_id
        self.setWindowTitle(f"Repair Order Details (ID {ro_id})")

        layout = QFormLayout(self)

        # --- Core fields ---
        self.date_field = QDateEdit()
        self.date_field.setDisplayFormat("MM/dd/yyyy")
        self.date_field.setCalendarPopup(True)

        self.ro_number_field = QLineEdit()

        self.estimator_field = SafeComboBox()
        self.stage_field = SafeComboBox()
        self.status_field = SafeComboBox()

        self.ro_hours_field = QLineEdit()
        self.hours_taken_field = QLineEdit()
        self.hours_taken_field.setReadOnly(True)
        self.hours_remaining_field = QLineEdit()
        self.hours_remaining_field.setReadOnly(True)

        # Fill dropdowns
        estimators = [e.nickname or e.name for e in Employee.by_role("Estimator")]
        self.estimator_field.addItems(estimators)
        self.stage_field.addItems([
            "Scheduled", "Intake", "Disassembly", "Body", "Refinish",
            "Reassembly", "Mechanical", "Detail", "QC", "Delivered"
        ])
        self.status_field.addItems(["Open", "On Hold", "Closed"])

        # Layout
        layout.addRow("Date:", self.date_field)
        layout.addRow("RO Number:", self.ro_number_field)
        layout.addRow("Estimator:", self.estimator_field)
        layout.addRow("RO Hours:", self.ro_hours_field)
        layout.addRow("Hours Taken:", self.hours_taken_field)
        layout.addRow("Hours Remaining:", self.hours_remaining_field)
        layout.addRow("Stage:", self.stage_field)
        layout.addRow("Status:", self.status_field)

        # --- Allocations subtable ---
        self.alloc_table = QTableWidget()
        self.alloc_table.setColumnCount(3)
        self.alloc_table.setHorizontalHeaderLabels(["Employee", "Role", "Percent"])
        self.alloc_table.setAlternatingRowColors(True)
        layout.addRow(QLabel("Allocations:"), self.alloc_table)

        alloc_btns = QHBoxLayout()
        self.add_alloc_btn = QPushButton("Add Allocation")
        self.del_alloc_btn = QPushButton("Remove Allocation")
        alloc_btns.addWidget(self.add_alloc_btn)
        alloc_btns.addWidget(self.del_alloc_btn)
        layout.addRow(alloc_btns)

        self.add_alloc_btn.clicked.connect(self.add_allocation_row)
        self.del_alloc_btn.clicked.connect(self.remove_selected_allocation)

        # Save button
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_changes)
        layout.addRow(save_btn)

        self.setLayout(layout)
        self.load_data()
        self.load_allocations()

    # --- Data loaders ---
    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT date, ro_number, estimator_id, ro_hours,
                       hours_taken, hours_remaining, stage, status
                FROM repair_orders WHERE id = ?
            """, (self.ro_id,))
            row = cursor.fetchone()

        if row:
            date, ro_number, estimator_id, ro_hours, hours_taken, hours_remaining, stage, status = row
            self.date_field.setDate(QDate.fromString(date, "yyyy-MM-dd"))
            self.ro_number_field.setText(str(ro_number))
            if estimator_id:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT full_name, nickname FROM employees WHERE id=?", (estimator_id,))
                    emp = cur.fetchone()
                    if emp:
                        self.estimator_field.setCurrentText(emp[1] or emp[0])
            self.ro_hours_field.setText(f"{ro_hours:.1f}")
            self.hours_taken_field.setText(f"{hours_taken:.1f}")
            self.hours_remaining_field.setText(f"{hours_remaining:.1f}")
            self.stage_field.setCurrentText(stage)
            self.status_field.setCurrentText(status)

    def load_allocations(self):
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT e.full_name, e.nickname, a.role, a.percent
                FROM ro_hours_allocation a
                JOIN employees e ON a.employee_id = e.id
                WHERE a.ro_id=?
            """, (self.ro_id,))
            rows = cur.fetchall()

        self.alloc_table.setRowCount(len(rows))
        for r, (full_name, nickname, role, percent) in enumerate(rows):
            display = nickname or full_name
            self.alloc_table.setItem(r, 0, QTableWidgetItem(display))
            self.alloc_table.setItem(r, 1, QTableWidgetItem(role))
            self.alloc_table.setItem(r, 2, QTableWidgetItem(f"{percent:.1f}"))

    # --- Allocation controls ---
    def add_allocation_row(self):
        r = self.alloc_table.rowCount()
        self.alloc_table.insertRow(r)
        self.alloc_table.setItem(r, 0, QTableWidgetItem("Select Employee"))
        self.alloc_table.setItem(r, 1, QTableWidgetItem("Role"))
        self.alloc_table.setItem(r, 2, QTableWidgetItem("0"))

    def remove_selected_allocation(self):
        selected = self.alloc_table.selectionModel().selectedRows()
        for idx in sorted(selected, reverse=True):
            self.alloc_table.removeRow(idx.row())

    # --- Save changes ---
    def save_changes(self):
        with get_connection() as conn:
            cursor = conn.cursor()

            # Update RO
            est_name = self.estimator_field.currentText()
            cursor.execute("SELECT id FROM employees WHERE full_name=? OR nickname=?", (est_name, est_name))
            est_match = cursor.fetchone()
            estimator_id = est_match[0] if est_match else None

            cursor.execute("""
                UPDATE repair_orders
                SET date=?, ro_number=?, estimator_id=?, ro_hours=?,
                    stage=?, status=?
                WHERE id=?
            """, (
                self.date_field.date().toString("yyyy-MM-dd"),
                int(self.ro_number_field.text()),
                estimator_id,
                float(self.ro_hours_field.text() or 0),
                self.stage_field.currentText(),
                self.status_field.currentText(),
                self.ro_id,
            ))

            # Update allocations
            cursor.execute("DELETE FROM ro_hours_allocation WHERE ro_id=?", (self.ro_id,))
            for r in range(self.alloc_table.rowCount()):
                emp_name = self.alloc_table.item(r, 0).text().strip()
                role = self.alloc_table.item(r, 1).text().strip()
                percent = float(self.alloc_table.item(r, 2).text() or 0)

                cur2 = conn.cursor()
                cur2.execute("SELECT id FROM employees WHERE full_name=? OR nickname=?", (emp_name, emp_name))
                match = cur2.fetchone()
                if not match:
                    continue
                (emp_id,) = match

                cursor.execute("""
                    INSERT INTO ro_hours_allocation (ro_id, employee_id, role, percent)
                    VALUES (?, ?, ?, ?)
                """, (self.ro_id, emp_id, role, percent))

        log_stage_change(self.ro_id, self.stage_field.currentText())
        update_ro_hours(self.ro_id)
        QMessageBox.information(self, "Success", "Repair order updated successfully.")
        self.accept()


# ---------- Helpers ------------
# --- Credit helpers ---
def log_credit(ro_number, employee_id, hours, note):
    """Log credited or supplemental hours by employee_id."""
    if not employee_id or hours == 0:
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        # ✅ Ensure the RO still exists before logging credit
        cursor.execute("SELECT 1 FROM repair_orders WHERE ro_number=?", (ro_number,))
        if not cursor.fetchone():
            return  # skip if RO doesn't exist

        cursor.execute("""
            INSERT INTO credit_audit (date, ro_number, employee_id, hours, note)
            VALUES (?, ?, ?, ?, ?)
        """, (
            QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm AP"),
            ro_number,
            employee_id,
            hours,
            note
        ))


def safe_log_credit(ro_number, employee_id, hours, note):
    """Insert credit only if it doesn't already exist for this RO/employee/note."""
    if not employee_id or hours == 0:
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 1 FROM credit_audit
            WHERE ro_number=? AND employee_id=? AND note=?
        """, (ro_number, employee_id, note))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO credit_audit (date, ro_number, employee_id, hours, note)
                VALUES (?, ?, ?, ?, ?)
            """, (
                QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm AP"),
                ro_number, employee_id, hours, note
            ))


def update_ro_hours(ro_id):
    """Recalculate and credit hours based on allocations + stage history."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # RO basics
        cursor.execute("SELECT ro_number, ro_hours FROM repair_orders WHERE id=?", (ro_id,))
        row = cursor.fetchone()
        if not row:
            return
        ro_number, ro_hours = row

        # Stage history → find furthest stage
        cursor.execute("SELECT stage FROM ro_stage_history WHERE ro_id=? ORDER BY id", (ro_id,))
        stages = [s[0] for s in cursor.fetchall()]
        if not stages:
            return

        STAGES = [
            "Scheduled", "Intake", "Disassembly", "Body", "Refinish",
            "Reassembly", "Mechanical", "Detail", "QC", "Delivered"
        ]
        stage_order = {name: idx for idx, name in enumerate(STAGES)}
        furthest_idx = max(stage_order[s] for s in stages if s in stage_order)

        # Allocations for this RO
        cursor.execute("""
            SELECT employee_id, phase, fraction, hours
            FROM ro_hours_allocation
            WHERE ro_id=?
        """, (ro_id,))
        allocations = cursor.fetchall()

        taken = 0.0
        for emp_id, phase, fraction, hours in allocations:
            if phase not in stage_order:
                continue
            if furthest_idx > stage_order[phase]:
                credit_hours = hours if hours else ro_hours * fraction
                taken += credit_hours
                safe_log_credit(ro_number, emp_id, credit_hours, f"{phase} phase completed")

        remaining = max(ro_hours - taken, 0.0)
        cursor.execute("UPDATE repair_orders SET hours_taken=?, hours_remaining=? WHERE id=?",
                       (taken, remaining, ro_id))


def apply_uncredited_hours(ro_id):
    """On RO close, reconcile credits with allocation totals."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ro_number, ro_hours FROM repair_orders WHERE id=?", (ro_id,))
        row = cursor.fetchone()
        if not row:
            return
        ro_number, ro_hours = row

        # Expected allocations
        cursor.execute("""
            SELECT employee_id, SUM(COALESCE(hours, ro_hours * fraction))
            FROM ro_hours_allocation
            WHERE ro_id=?
            GROUP BY employee_id
        """, (ro_id,))
        expected = {emp: hrs for emp, hrs in cursor.fetchall()}

        # Already credited
        cursor.execute("""
            SELECT employee_id, SUM(hours) FROM credit_audit
            WHERE ro_number=?
            GROUP BY employee_id
        """, (ro_number,))
        credited = {emp: hrs for emp, hrs in cursor.fetchall()}

        # Reconcile
        for emp_id, exp_total in expected.items():
            credited_total = credited.get(emp_id, 0)
            diff = exp_total - credited_total
            if abs(diff) > 0.01:  # tolerance for float math
                log_credit(ro_number, emp_id, diff, "Adjustment on close (recalc)")


