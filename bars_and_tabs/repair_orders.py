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


def log_credit(ro_number, employee, hours, note):
    """Log credited or supplemental hours using RO number."""
    if not employee or employee == "Unassigned" or hours == 0:
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        # ✅ Ensure the RO still exists before logging credit
        cursor.execute("SELECT 1 FROM repair_orders WHERE ro_number=?", (ro_number,))
        if not cursor.fetchone():
            conn.close()
            return  # skip if RO doesn't exist

        cursor.execute("""
            INSERT INTO credit_audit (date, ro_number, employee, hours, note)
            VALUES (?, ?, ?, ?, ?)
        """, (
            QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm AP"),
            ro_number,
            employee,
            hours,
            note
        ))


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
            query = """SELECT id, date, ro_number, estimator, tech, painter, mechanic, stage, status
                       FROM repair_orders
                       WHERE 1=1"""
            params = []

            # --- Status filter ---
            if not self.show_closed_cb.isChecked():
                query += " AND status != ?"
                params.append("Closed")

            # --- Text search filter ---
            text = self.search_box.text().strip()
            if text:
                like = f"%{text}%"
                query += """ AND (
                    CAST(ro_number AS TEXT) LIKE ?
                    OR estimator LIKE ?
                    OR tech LIKE ?
                    OR painter LIKE ?
                    OR mechanic LIKE ?
                    OR status LIKE ?
                    OR stage LIKE ?
                )"""
                params.extend([like] * 7)

            # --- Date range filter ---
            if self.date_filter_enabled:
                from_date = self.date_from.date()
                to_date = self.date_to.date()
                if from_date.isValid() and to_date.isValid():
                    query += " AND date >= ? AND date <= ?"
                    params.append(from_date.toString("yyyy-MM-dd"))
                    params.append(to_date.toString("yyyy-MM-dd"))

            # --- Order ---
            query += " ORDER BY ro_number"
            cursor.execute(query, params)
            rows = cursor.fetchall()

        # --- Populate table ---
        self.table.setRowCount(len(rows))
        statuses = self.load_statuses()
        stages = self.load_stages()

        for row_index, row in enumerate(rows):
            ro_id, date, ro_number, estimator, tech, painter, mechanic, stage, status = row
            date_str = QDate.fromString(date, "yyyy-MM-dd").toString("MM/dd/yyyy")
            self.table.setItem(row_index, 0, QTableWidgetItem(date))
            self.table.setItem(row_index, 1, QTableWidgetItem(str(ro_number)))
            self.table.setItem(row_index, 2, QTableWidgetItem(estimator))
            self.table.setItem(row_index, 3, QTableWidgetItem(tech))
            self.table.setItem(row_index, 4, QTableWidgetItem(painter))
            self.table.setItem(row_index, 5, QTableWidgetItem(mechanic))

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
        estimators = [e.name for e in Employee.by_role("Estimator")]
        techs = [e.name for e in Employee.by_role("Tech")]
        painters = [e.name for e in Employee.by_role("Painter")]
        mechanics = [e.name for e in Employee.by_role("Mechanic")]

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
                    self.estimator_field.currentText(),
                    self.tech_field.currentText() or "Unassigned",
                    self.painter_field.currentText() or "Unassigned",
                    self.mechanic_field.currentText() or "Unassigned",
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

        # Date as calendar
        self.date_field = QDateEdit()
        self.date_field.setDisplayFormat("MM/dd/yyyy")
        self.date_field.setCalendarPopup(True)

        # Dropdowns
        self.estimator_field = SafeComboBox()
        self.tech_field = SafeComboBox()
        self.painter_field = SafeComboBox()
        self.mechanic_field = SafeComboBox()

        # Load employees dynamically by role
        estimators = [e.name for e in Employee.by_role("Estimator")]
        techs = [e.name for e in Employee.by_role("Tech")]
        painters = [e.name for e in Employee.by_role("Painter")]
        mechanics = [e.name for e in Employee.by_role("Mechanic")]

        # Fill dropdowns
        self.estimator_field.addItems(estimators)

        self.tech_field.addItem("Unassigned")
        self.tech_field.addItems(techs)

        self.painter_field.addItem("Unassigned")
        self.painter_field.addItems(painters)

        self.mechanic_field.addItem("Unassigned")
        self.mechanic_field.addItems(mechanics)

        # Editable fields
        self.ro_number_field = QLineEdit()
        self.ro_hours_field = QLineEdit()
        self.body_hours_field = QLineEdit()
        self.refinish_hours_field = QLineEdit()
        self.mechanical_hours_field = QLineEdit()

        # Read-only fields
        self.hours_taken_field = QLineEdit()
        self.hours_taken_field.setReadOnly(True)
        self.hours_remaining_field = QLineEdit()
        self.hours_remaining_field.setReadOnly(True)

        self.stage_field = SafeComboBox()
        self.status_field = SafeComboBox()
        self.stage_field.addItems(["Intake", "In Progress", "Completed"])
        self.status_field.addItems(["Open", "On Hold", "Closed"])

        # Add to layout
        layout.addRow("Date:", self.date_field)
        layout.addRow("RO Number:", self.ro_number_field)
        layout.addRow("Estimator:", self.estimator_field)
        layout.addRow("Tech:", self.tech_field)
        layout.addRow("Painter:", self.painter_field)
        layout.addRow("Mechanic:", self.mechanic_field)
        layout.addRow("RO Hours:", self.ro_hours_field)
        layout.addRow("Body Hours:", self.body_hours_field)
        layout.addRow("Refinish Hours:", self.refinish_hours_field)
        layout.addRow("Mechanical Hours:", self.mechanical_hours_field)
        layout.addRow("Hours Taken:", self.hours_taken_field)
        layout.addRow("Hours Remaining:", self.hours_remaining_field)
        layout.addRow("Stage:", self.stage_field)
        layout.addRow("Status:", self.status_field)

        # Save button
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_changes)
        layout.addRow(save_btn)

        self.setLayout(layout)
        self.load_data()

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT date, ro_number, estimator, tech, painter, mechanic,
                             ro_hours, body_hours, refinish_hours, mechanical_hours,
                             hours_taken, hours_remaining, stage, status
                FROM repair_orders WHERE id = ?
                """,
                (self.ro_id,),
            )
            row = cursor.fetchone()

        if row:
            (
                date, ro_number, estimator, tech, painter, mechanic,
                ro_hours, body_hours, refinish_hours, mechanical_hours,
                hours_taken, hours_remaining, stage, status
            ) = row

            self.date_field.setDate(QDate.fromString(date, "yyyy-MM-dd"))
            self.ro_number_field.setText(str(ro_number))
            self.estimator_field.setCurrentText(estimator)
            self.tech_field.setCurrentText(tech)
            self.painter_field.setCurrentText(painter)
            self.mechanic_field.setCurrentText(mechanic)
            self.ro_hours_field.setText(str(ro_hours))
            self.body_hours_field.setText(str(body_hours))
            self.refinish_hours_field.setText(str(refinish_hours))
            self.mechanical_hours_field.setText(str(mechanical_hours))
            self.hours_taken_field.setText(str(hours_taken))
            self.hours_remaining_field.setText(str(hours_remaining))
            self.stage_field.setCurrentText(stage)
            self.status_field.setCurrentText(status)

    def save_changes(self):
        with get_connection() as conn:
            cursor = conn.cursor()

            # --- Get current hours + stage before update ---
            cursor.execute(
                "SELECT body_hours, refinish_hours, mechanical_hours, stage FROM repair_orders WHERE id=?",
                (self.ro_id,))
            old_body, old_refinish, old_mech, current_stage = cursor.fetchone()

            new_body = float(self.body_hours_field.text() or 0)
            new_refinish = float(self.refinish_hours_field.text() or 0)
            new_mech = float(self.mechanical_hours_field.text() or 0)

            # --- Fetch ro_number for credit logging ---
            cursor.execute("SELECT ro_number FROM repair_orders WHERE id=?", (self.ro_id,))
            (ro_number,) = cursor.fetchone()

            # --- Stage gating rules (only allow beyond Intake/Scheduled) ---
            if current_stage not in ("Scheduled", "Intake"):
                # Body hours
                if new_body != old_body:
                    if old_body > 0:  # only supplemental if baseline already exists
                        log_credit(ro_number, self.tech_field.currentText(),
                                   new_body - old_body,
                                   f"Body hours adjusted {old_body} → {new_body}")

                # Refinish hours
                if new_refinish != old_refinish:
                    if old_refinish > 0:  # supplemental only
                        log_credit(ro_number, self.painter_field.currentText(),
                                   new_refinish - old_refinish,
                                   f"Refinish hours adjusted {old_refinish} → {new_refinish}")

                # Mechanical hours
                if new_mech != old_mech:
                    if old_mech > 0:  # supplemental only
                        log_credit(ro_number, self.mechanic_field.currentText(),
                                   new_mech - old_mech,
                                   f"Mechanical hours adjusted {old_mech} → {new_mech}")

            # --- Update repair order record ---
            cursor.execute(
                """
                UPDATE repair_orders
                SET date=?,
                    ro_number=?,
                    estimator=?,
                    tech=?,
                    painter=?,
                    mechanic=?,
                    ro_hours=?,
                    body_hours=?,
                    refinish_hours=?,
                    mechanical_hours=?,
                    stage=?,
                    status=?
                WHERE id = ?
                """,
                (
                    self.date_field.date().toString("yyyy-MM-dd"),
                    int(self.ro_number_field.text()),
                    self.estimator_field.currentText(),
                    self.tech_field.currentText(),
                    self.painter_field.currentText(),
                    self.mechanic_field.currentText(),
                    float(self.ro_hours_field.text() or 0),
                    new_body,
                    new_refinish,
                    new_mech,
                    self.stage_field.currentText(),
                    self.status_field.currentText(),
                    self.ro_id,
                ),
            )


        log_stage_change(self.ro_id, self.stage_field.currentText())
        update_ro_hours(self.ro_id)
        QMessageBox.information(self, "Success", "Repair order updated successfully.")
        self.accept()


# ---------- Helpers ------------
def safe_log_credit(ro_number, employee, hours, note):
    """Insert credit only if it doesn't already exist for this RO/employee/note."""
    if not employee or employee == "Unassigned" or hours == 0:
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 1 FROM credit_audit
            WHERE ro_number=? AND employee=? AND note=?
        """, (ro_number, employee, note))
        exists = cursor.fetchone()
        if not exists:
            cursor.execute("""
                INSERT INTO credit_audit (date, ro_number, employee, hours, note)
                VALUES (?, ?, ?, ?, ?)
            """, (
                QDateTime.currentDateTime().toString("MM/dd/yyyy hh:mm AP"),
                ro_number, employee, hours, note
            ))


def update_ro_hours(ro_id):
    """Recalculate and credit hours as RO moves through phases, idempotently."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT ro_number, tech, painter, mechanic, ro_hours, body_hours, refinish_hours, mechanical_hours FROM repair_orders WHERE id=?",
            (ro_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return

        ro_number, tech, painter, mech, ro_hours, body, refinish, mechanical = row

        # Get stage history
        cursor.execute("SELECT stage FROM ro_stage_history WHERE ro_id=? ORDER BY id", (ro_id,))
        stages = [s[0] for s in cursor.fetchall()]

        STAGES = [
            "Scheduled", "Intake", "Disassembly", "Body", "Refinish",
            "Reassembly", "Mechanical", "Detail", "QC", "Delivered"
        ]
        stage_order = {name: idx for idx, name in enumerate(STAGES)}
        indices = [stage_order[s] for s in stages if s in stage_order]

        taken = 0.0
        if indices:
            furthest_idx = max(indices)

            # --- Tech credits ---
            if furthest_idx > stage_order["Body"] and body > 0:
                if tech and tech != "Unassigned":
                    hours = body * 0.6
                    taken += hours
                    safe_log_credit(ro_number, tech, hours, "Body phase completed (60%)")

            if furthest_idx > stage_order["Reassembly"] and body > 0:
                if tech and tech != "Unassigned":
                    hours = body * 0.4
                    taken += hours
                    safe_log_credit(ro_number, tech, hours, "Reassembly phase completed (40%)")

            # --- Painter credits ---
            if furthest_idx > stage_order["Refinish"] and refinish > 0:
                if painter and painter != "Unassigned":
                    hours = refinish
                    taken += hours
                    safe_log_credit(ro_number, painter, hours, "Refinish phase completed")

            # --- Mechanic credits ---
            if furthest_idx > stage_order["Mechanical"] and mechanical > 0:
                if mech and mech != "Unassigned":
                    hours = mechanical
                    taken += hours
                    safe_log_credit(ro_number, mech, hours, "Mechanical phase completed")

        remaining = max(ro_hours - taken, 0.0)

        # Update RO record
        cursor.execute(
            "UPDATE repair_orders SET hours_taken=?, hours_remaining=? WHERE id=?",
            (taken, remaining, ro_id)
        )


def apply_uncredited_hours(ro_id):
    """When closing an RO, reconcile credits so totals reflect any adjustments (adds or subtracts)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ro_number, body_hours, refinish_hours, mechanical_hours,
                   tech, painter, mechanic
            FROM repair_orders WHERE id=?
        """, (ro_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return

        (ro_number, body, refinish, mechanical,
         tech, painter, mech) = row

        # Expected totals per role
        expected = {}
        if tech and tech != "Unassigned":
            expected[tech] = expected.get(tech, 0) + body
        if painter and painter != "Unassigned":
            expected[painter] = expected.get(painter, 0) + refinish
        if mech and mech != "Unassigned":
            expected[mech] = expected.get(mech, 0) + mechanical

        # Already credited totals per role (for this RO only)
        cursor.execute("""
            SELECT employee, SUM(hours) FROM credit_audit
            WHERE ro_number=?
            GROUP BY employee
        """, (ro_number,))
        credited_map = {emp: hrs for emp, hrs in cursor.fetchall()}

        # Reconcile for each role
        for emp, exp_total in expected.items():
            credited = credited_map.get(emp, 0)
            diff = exp_total - credited
            if diff != 0:
                # diff can be positive (add hours) or negative (reduce hours)
                note = "Adjustment on close (recalc)"
                log_credit(ro_number, emp, diff, note)


