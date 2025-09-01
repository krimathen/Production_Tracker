from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QDateEdit,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QDialog, QFormLayout, QLineEdit, QMessageBox, QAbstractItemView, QSizePolicy
)
from PySide6.QtCore import QDate, QDateTime
from database import get_connection
from key_bindings import add_refresh_shortcut
from utilities.safe_combobox import SafeComboBox
from utilities.employees import Employee


def log_stage_change(ro_id, stage):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ro_stage_history (ro_id, stage, date) VALUES (?, ?, ?)",
            (ro_id, stage, QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm AP"))
        )


def resolve_full(role, chosen_display):
    """Match nickname/full_name against chosen display name for a role."""
    for e in Employee.by_role(role):
        if (e.nickname or e.full_name) == chosen_display:
            return e.full_name
    return chosen_display  # fallback if no match


class RepairOrdersPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # --- Row 1: buttons + search ---
        top_layout = QHBoxLayout()
        self.new_ro_btn = QPushButton("New RO")
        self.new_ro_btn.clicked.connect(self.open_new_ro_dialog)
        top_layout.addWidget(self.new_ro_btn)

        self.delete_ro_btn = QPushButton("Delete RO")
        self.delete_ro_btn.clicked.connect(self.delete_selected_ro)
        top_layout.addWidget(self.delete_ro_btn)

        top_layout.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("RO#, Estimator, Stage, Status")
        self.search_box.textChanged.connect(self.load_data)
        top_layout.addWidget(self.search_box, stretch=1)

        self.show_all_btn = QPushButton("Show All")
        self.show_all_btn.clicked.connect(self.show_all)
        top_layout.addWidget(self.show_all_btn)

        layout.addLayout(top_layout)

        # --- Row 2: Filters ---
        filter_layout = QHBoxLayout()
        today = QDate.currentDate()
        ninety_days_ago = today.addDays(-90)

        filter_layout.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setDisplayFormat("MM/dd/yyyy")
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(ninety_days_ago)
        filter_layout.addWidget(self.date_from)

        filter_layout.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setDisplayFormat("MM/dd/yyyy")
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(today)
        filter_layout.addWidget(self.date_to)

        self.apply_filter_btn = QPushButton("Apply Filter")
        self.apply_filter_btn.clicked.connect(self.apply_filter)
        filter_layout.addWidget(self.apply_filter_btn)

        self.show_closed_cb = QCheckBox("Show Closed")
        self.show_closed_cb.stateChanged.connect(self.load_data)
        filter_layout.addWidget(self.show_closed_cb)

        layout.addLayout(filter_layout)
        self.date_filter_enabled = True

        # --- Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Date", "RO#", "Estimator", "Stage", "Status"]
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
        self.search_box.clear()
        self.date_filter_enabled = False
        self.load_data()

    def apply_filter(self):
        self.date_filter_enabled = True
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
        ids = [int(self.table.verticalHeaderItem(idx.row()).text()) for idx in selected_rows]
        if not ids:
            QMessageBox.warning(self, "No Selection", "Please select at least one RO to delete.")
            return

        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {len(ids)} RO(s) and all their linked credits?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        with get_connection() as conn:
            cursor = conn.cursor()
            for rid in ids:
                cursor.execute("DELETE FROM credit_audit WHERE ro_id=?", (rid,))
                cursor.execute("DELETE FROM ro_hours_allocation WHERE ro_id=?", (rid,))
                cursor.execute("DELETE FROM repair_orders WHERE id=?", (rid,))

        QMessageBox.information(self, "Deleted", f"Deleted {len(ids)} RO(s).")
        self.load_data()

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            query = """SELECT r.id, r.date, r.ro_number, r.estimator_id, r.stage, r.status,
                              e.full_name, e.nickname
                       FROM repair_orders r
                       LEFT JOIN employees e ON r.estimator_id = e.id
                       WHERE 1=1"""
            params = []

            if not self.show_closed_cb.isChecked():
                query += " AND r.status != ?"
                params.append("Closed")

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

            if self.date_filter_enabled:
                from_date = self.date_from.date()
                to_date = self.date_to.date()
                query += " AND r.date BETWEEN ? AND ?"
                params.append(from_date.toString("yyyy-MM-dd"))
                params.append(to_date.toString("yyyy-MM-dd"))

            query += " ORDER BY r.ro_number"
            cursor.execute(query, params)
            rows = cursor.fetchall()

        self.table.setRowCount(len(rows))
        statuses = self.load_statuses()
        stages = self.load_stages()

        for r, (ro_id, date, ro_number, estimator_id, stage, status, full_name, nickname) in enumerate(rows):
            date_str = QDate.fromString(date, "yyyy-MM-dd").toString("MM/dd/yyyy")
            estimator_display = nickname or full_name or "Unassigned"

            self.table.setItem(r, 0, QTableWidgetItem(date_str))
            self.table.setItem(r, 1, QTableWidgetItem(str(ro_number)))
            self.table.setItem(r, 2, QTableWidgetItem(estimator_display))

            stage_cb = SafeComboBox()
            stage_cb.addItems(stages)
            stage_cb.setCurrentText(stage or "Intake")
            self.table.setCellWidget(r, 3, stage_cb)
            stage_cb.currentTextChanged.connect(
                lambda value, rid=ro_id: (
                    self.update_field(rid, "stage", value),
                    log_stage_change(rid, value),
                    update_ro_hours(rid)
                )
            )

            status_cb = SafeComboBox()
            status_cb.addItems(statuses)
            status_cb.setCurrentText(status or "Open")
            self.table.setCellWidget(r, 4, status_cb)
            status_cb.currentTextChanged.connect(
                lambda value, rid=ro_id: (
                    self.update_field(rid, "status", value),
                    apply_uncredited_hours(rid) if value == "Closed" else None
                )
            )

            self.table.setVerticalHeaderItem(r, QTableWidgetItem(str(ro_id)))


class NewRODialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Repair Order")

        layout = QFormLayout(self)

        # --- Core fields ---
        self.date_field = QDateEdit()
        self.date_field.setDisplayFormat("MM/dd/yyyy")
        self.date_field.setCalendarPopup(True)
        self.date_field.setDate(QDate.currentDate())

        self.ro_number_field = QLineEdit()

        self.estimator_field = SafeComboBox()
        estimators = [e.nickname or e.full_name for e in Employee.by_role("Estimator")]
        self.estimator_field.addItems(estimators)

        self.ro_hours_field = QLineEdit()
        self.body_hours_field = QLineEdit()
        self.refinish_hours_field = QLineEdit()
        self.mechanical_hours_field = QLineEdit()

        layout.addRow("Date:", self.date_field)
        layout.addRow("RO Number:*", self.ro_number_field)
        layout.addRow("Estimator:*", self.estimator_field)
        layout.addRow("Total Hours:", self.ro_hours_field)
        layout.addRow("Body Hours:", self.body_hours_field)
        layout.addRow("Refinish Hours:", self.refinish_hours_field)
        layout.addRow("Mechanical Hours:", self.mechanical_hours_field)

        # --- Allocations subtable ---
        self.alloc_table = QTableWidget()
        self.alloc_table.setColumnCount(3)
        self.alloc_table.setHorizontalHeaderLabels(["Employee", "Role", "Percent"])
        self.alloc_table.setAlternatingRowColors(True)
        self.alloc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.alloc_table.setSelectionMode(QAbstractItemView.SingleSelection)
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
        save_btn.clicked.connect(self.save)
        layout.addRow(save_btn)

    def add_allocation_row(self, emp_name=None, role=None, percent=0.0):
        r = self.alloc_table.rowCount()
        self.alloc_table.insertRow(r)

        # Employee dropdown
        emp_cb = SafeComboBox()
        for e in Employee.all():
            emp_cb.addItem(e.nickname or e.full_name, e.id)
        if emp_name:
            emp_cb.setCurrentText(emp_name)
        self.alloc_table.setCellWidget(r, 0, emp_cb)

        # Role dropdown
        role_cb = SafeComboBox()
        roles = ["Tech", "Painter", "Prepper", "Estimator", "Mechanic", "Other"]
        role_cb.addItems(roles)
        if role:
            role_cb.setCurrentText(role)
        self.alloc_table.setCellWidget(r, 1, role_cb)

        # Percent
        self.alloc_table.setItem(r, 2, QTableWidgetItem(f"{percent:.1f}"))

    def remove_selected_allocation(self):
        selected = self.alloc_table.selectionModel().selectedRows()
        if not selected:
            row = self.alloc_table.currentRow()
            if row >= 0:
                self.alloc_table.removeRow(row)
        else:
            for idx in sorted(selected, reverse=True):
                self.alloc_table.removeRow(idx.row())

    def save(self):
        if not self.ro_number_field.text():
            QMessageBox.warning(self, "Error", "RO Number is required.")
            return
        if not self.estimator_field.currentText():
            QMessageBox.warning(self, "Error", "Estimator is required.")
            return

        est_full = resolve_full("Estimator", self.estimator_field.currentText())

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO repair_orders
                (date, ro_number, estimator_id, hours_total, hours_body,
                 hours_refinish, hours_mechanical, hours_taken, hours_remaining,
                 status, stage)
                VALUES (?, ?, (SELECT id FROM employees WHERE full_name=? OR nickname=?),
                        ?, ?, ?, ?, 0.0, 0.0, 'Open', 'Intake')
            """, (
                self.date_field.date().toString("yyyy-MM-dd"),
                int(self.ro_number_field.text()),
                est_full, est_full,
                float(self.ro_hours_field.text() or 0),
                float(self.body_hours_field.text() or 0),
                float(self.refinish_hours_field.text() or 0),
                float(self.mechanical_hours_field.text() or 0),
            ))

            ro_id = cursor.lastrowid

            # Save allocations
            for r in range(self.alloc_table.rowCount()):
                emp_cb = self.alloc_table.cellWidget(r, 0)
                role_cb = self.alloc_table.cellWidget(r, 1)
                percent_item = self.alloc_table.item(r, 2)

                if not emp_cb or not role_cb or not percent_item:
                    continue

                emp_id = emp_cb.currentData()
                role = role_cb.currentText()
                try:
                    percent = float(percent_item.text())
                except:
                    percent = 0.0

                if not emp_id:
                    continue

                cursor.execute("""
                    INSERT INTO ro_hours_allocation (ro_id, employee_id, role, percent)
                    VALUES (?, ?, ?, ?)
                """, (ro_id, emp_id, role, percent))

        QMessageBox.information(self, "Success", "Repair order created.")
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
        estimators = [e.nickname or e.full_name for e in Employee.by_role("Estimator")]
        self.estimator_field.addItems(estimators)

        self.stage_field = SafeComboBox()
        self.status_field = SafeComboBox()

        self.ro_hours_field = QLineEdit()
        self.body_hours_field = QLineEdit()
        self.refinish_hours_field = QLineEdit()
        self.mechanical_hours_field = QLineEdit()

        self.hours_taken_field = QLineEdit()
        self.hours_taken_field.setReadOnly(True)
        self.hours_remaining_field = QLineEdit()
        self.hours_remaining_field.setReadOnly(True)

        self.stage_field.addItems([
            "Scheduled", "Intake", "Disassembly", "Body", "Refinish",
            "Reassembly", "Mechanical", "Detail", "QC", "Delivered"
        ])
        self.status_field.addItems(["Open", "On Hold", "Closed"])

        layout.addRow("Date:", self.date_field)
        layout.addRow("RO Number:", self.ro_number_field)
        layout.addRow("Estimator:", self.estimator_field)
        layout.addRow("Total Hours:", self.ro_hours_field)
        layout.addRow("Body Hours:", self.body_hours_field)
        layout.addRow("Refinish Hours:", self.refinish_hours_field)
        layout.addRow("Mechanical Hours:", self.mechanical_hours_field)
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

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT date, ro_number, estimator_id, hours_total,
                       hours_body, hours_refinish, hours_mechanical,
                       hours_taken, hours_remaining, stage, status
                FROM repair_orders WHERE id = ?
            """, (self.ro_id,))
            row = cursor.fetchone()

        if row:
            (date, ro_number, estimator_id, hours_total,
             hours_body, hours_refinish, hours_mechanical,
             hours_taken, hours_remaining, stage, status) = row

            self.date_field.setDate(QDate.fromString(date, "yyyy-MM-dd"))
            self.ro_number_field.setText(str(ro_number))

            if estimator_id:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT full_name, nickname FROM employees WHERE id=?", (estimator_id,))
                    emp = cur.fetchone()
                    if emp:
                        self.estimator_field.setCurrentText(emp[1] or emp[0])

            self.ro_hours_field.setText(f"{hours_total:.1f}")
            self.body_hours_field.setText(f"{hours_body:.1f}")
            self.refinish_hours_field.setText(f"{hours_refinish:.1f}")
            self.mechanical_hours_field.setText(f"{hours_mechanical:.1f}")
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

        self.alloc_table.setRowCount(0)
        for full_name, nickname, role, percent in rows:
            display = nickname or full_name
            self.add_allocation_row(display, role, percent)

    def add_allocation_row(self, emp_name=None, role=None, percent=0.0):
        r = self.alloc_table.rowCount()
        self.alloc_table.insertRow(r)

        # Employee dropdown
        emp_cb = SafeComboBox()
        employees = Employee.all()
        for e in employees:
            emp_cb.addItem(e.nickname or e.full_name, e.id)
        if emp_name:
            emp_cb.setCurrentText(emp_name)
        self.alloc_table.setCellWidget(r, 0, emp_cb)

        # Role dropdown
        role_cb = SafeComboBox()
        roles = ["Tech", "Painter", "Prepper", "Estimator", "Mechanic", "Other"]
        role_cb.addItems(roles)
        if role:
            role_cb.setCurrentText(role)
        self.alloc_table.setCellWidget(r, 1, role_cb)

        # Percent
        self.alloc_table.setItem(r, 2, QTableWidgetItem(f"{percent:.1f}"))

    def remove_selected_allocation(self):
        selected = self.alloc_table.selectionModel().selectedRows()
        if not selected:
            row = self.alloc_table.currentRow()
            if row >= 0:
                self.alloc_table.removeRow(row)
        else:
            for idx in sorted(selected, reverse=True):
                self.alloc_table.removeRow(idx.row())

    def save_changes(self):
        with get_connection() as conn:
            cursor = conn.cursor()

            est_name = self.estimator_field.currentText()
            cursor.execute("SELECT id FROM employees WHERE full_name=? OR nickname=?", (est_name, est_name))
            est_match = cursor.fetchone()
            estimator_id = est_match[0] if est_match else None

            cursor.execute("""
                UPDATE repair_orders
                SET date=?, ro_number=?, estimator_id=?, hours_total=?,
                    hours_body=?, hours_refinish=?, hours_mechanical=?,
                    stage=?, status=?
                WHERE id=?
            """, (
                self.date_field.date().toString("yyyy-MM-dd"),
                int(self.ro_number_field.text()),
                estimator_id,
                float(self.ro_hours_field.text() or 0),
                float(self.body_hours_field.text() or 0),
                float(self.refinish_hours_field.text() or 0),
                float(self.mechanical_hours_field.text() or 0),
                self.stage_field.currentText(),
                self.status_field.currentText(),
                self.ro_id,
            ))

            # Rewrite allocations
            cursor.execute("DELETE FROM ro_hours_allocation WHERE ro_id=?", (self.ro_id,))
            for r in range(self.alloc_table.rowCount()):
                emp_cb = self.alloc_table.cellWidget(r, 0)
                role_cb = self.alloc_table.cellWidget(r, 1)
                percent_item = self.alloc_table.item(r, 2)

                if not emp_cb or not role_cb or not percent_item:
                    continue

                emp_id = emp_cb.currentData()
                role = role_cb.currentText()
                try:
                    percent = float(percent_item.text())
                except:
                    percent = 0.0

                if not emp_id:
                    continue

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
def log_credit(ro_id, employee_id, hours, note):
    """Log credited or supplemental hours by employee_id (uses ro_id FK)."""
    if not employee_id or hours == 0:
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM repair_orders WHERE id=?", (ro_id,))
        if not cursor.fetchone():
            return  # skip if RO doesn't exist

        cursor.execute("""
            INSERT INTO credit_audit (date, ro_id, employee_id, hours, note)
            VALUES (?, ?, ?, ?, ?)
        """, (
            QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm AP"),
            ro_id,
            employee_id,
            hours,
            note
        ))


def safe_log_credit(ro_id, employee_id, hours, note):
    """Insert credit only if it doesn't already exist for this RO/employee/note."""
    if not employee_id or hours == 0:
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 1 FROM credit_audit
            WHERE ro_id=? AND employee_id=? AND note=?
        """, (ro_id, employee_id, note))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO credit_audit (date, ro_id, employee_id, hours, note)
                VALUES (?, ?, ?, ?, ?)
            """, (
                QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm AP"),
                ro_id, employee_id, hours, note
            ))


def update_ro_hours(ro_id):
    """Recalculate and credit hours based on allocations + stage history."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT hours_total, hours_body, hours_refinish, hours_mechanical
            FROM repair_orders WHERE id=?
        """, (ro_id,))
        row = cursor.fetchone()
        if not row:
            return
        hours_total, hours_body, hours_refinish, hours_mechanical = row

        # Stage history → furthest stage reached
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

        # Role → (stage, bucket)
        # Note: no entries for Detail or QC → they won't credit hours
        role_map = {
            "Tech": ("Body", hours_body),
            "Painter": ("Refinish", hours_refinish),
            "Prepper": ("Refinish", hours_refinish),
            "Mechanic": ("Mechanical", hours_mechanical),
            "Estimator": ("Intake", hours_total),
        }

        # Allocations
        cursor.execute("SELECT employee_id, role, percent FROM ro_hours_allocation WHERE ro_id=?", (ro_id,))
        allocations = cursor.fetchall()

        taken = 0.0
        for emp_id, role, percent in allocations:
            if role not in role_map:
                continue
            stage, bucket = role_map[role]
            if bucket <= 0:
                continue
            if furthest_idx > stage_order[stage]:
                credit_hours = bucket * (percent / 100.0)
                taken += credit_hours
                safe_log_credit(ro_id, emp_id, credit_hours, f"{role} credited at {stage}")

        remaining = max(hours_total - taken, 0.0)
        cursor.execute(
            "UPDATE repair_orders SET hours_taken=?, hours_remaining=? WHERE id=?",
            (taken, remaining, ro_id),
        )


def apply_uncredited_hours(ro_id):
    """On RO close, reconcile credits with allocation totals, using role-specific buckets."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT hours_total, hours_body, hours_refinish, hours_mechanical
            FROM repair_orders WHERE id=?
        """, (ro_id,))
        row = cursor.fetchone()
        if not row:
            return
        hours_total, hours_body, hours_refinish, hours_mechanical = row

        # Buckets by role (no Detail/QC)
        role_buckets = {
            "Tech": hours_body,
            "Painter": hours_refinish,
            "Prepper": hours_refinish,
            "Mechanic": hours_mechanical,
            "Estimator": hours_total,
        }

        # Expected allocations
        cursor.execute("SELECT employee_id, role, percent FROM ro_hours_allocation WHERE ro_id=?", (ro_id,))
        allocations = cursor.fetchall()
        expected = {}
        for emp_id, role, percent in allocations:
            bucket = role_buckets.get(role, 0)
            if bucket > 0:
                expected.setdefault(emp_id, 0)
                expected[emp_id] += bucket * (percent / 100.0)

        # Already credited
        cursor.execute("""
            SELECT employee_id, SUM(hours) FROM credit_audit
            WHERE ro_id=?
            GROUP BY employee_id
        """, (ro_id,))
        credited = {emp: hrs for emp, hrs in cursor.fetchall()}

        for emp_id, exp_total in expected.items():
            credited_total = credited.get(emp_id, 0)
            diff = exp_total - credited_total
            if abs(diff) > 0.01:
                log_credit(ro_id, emp_id, diff, "Adjustment on close (recalc)")

