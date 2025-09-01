import csv
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QTableWidget, QLabel, QTabWidget, QDateEdit,
    QTableWidgetItem, QFileDialog, QMessageBox, QHBoxLayout, QAbstractItemView
)
from PySide6.QtCore import Qt, QDate
from datetime import datetime
from database import get_connection
from key_bindings import add_refresh_shortcut


class SafeDateEdit(QDateEdit):
    """QDateEdit that ignores mouse wheel events to prevent accidental changes."""
    def wheelEvent(self, event):
        event.ignore()


class EmployeeHoursTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # --- Top buttons ---
        btn_layout = QHBoxLayout()
        self.import_btn = QPushButton("Import CSV")
        self.import_pdf_btn = QPushButton("Import PDF")
        self.save_btn = QPushButton("Save Changes")
        self.delete_btn = QPushButton("Delete Selected")
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.import_pdf_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.delete_btn)
        layout.addLayout(btn_layout)

        # --- Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "Employee", "Start", "End", "Hours Worked"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.table)

        add_refresh_shortcut(self, self.load_data)

        # Signals
        self.import_btn.clicked.connect(self.import_csv)
        self.import_pdf_btn.clicked.connect(self.import_pdf)
        self.save_btn.clicked.connect(self.save_changes)
        self.delete_btn.clicked.connect(self.delete_selected)

        self.ids = []  # track row IDs
        self.load_data()

    # --- CSV Import ---
    def import_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV Files (*.csv)")
        if not file_path:
            return
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                with open(file_path, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        date = row["Date"].strip()
                        emp_name = row["Name"].strip()
                        start = row["Start"].strip()
                        end = row["End"].strip()
                        try:
                            t1 = datetime.strptime(start, "%I:%M %p")
                            t2 = datetime.strptime(end, "%I:%M %p")
                            hours = (t2 - t1).seconds / 3600.0
                        except Exception:
                            hours = 0.0
                        # Resolve employee_id
                        cursor.execute("SELECT id FROM employees WHERE full_name=? OR nickname=?", (emp_name, emp_name))
                        match = cursor.fetchone()
                        if not match:
                            continue
                        (emp_id,) = match
                        cursor.execute(
                            "INSERT INTO employee_hours (employee_id, date, start_time, end_time, hours_worked) VALUES (?, ?, ?, ?, ?)",
                            (emp_id, date, start, end, hours),
                        )

            QMessageBox.information(self, "Import Successful", "CSV data imported successfully.")
            self.load_data()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to import CSV:\n{e}")

    def import_pdf(self):
        from utilities.pdf_to_csv import pdf_to_csv
        pdf_path, _ = QFileDialog.getOpenFileName(self, "Import PDF", "", "PDF Files (*.pdf)")
        if not pdf_path:
            return
        csv_path = pdf_path.replace(".pdf", ".csv")
        pdf_to_csv(pdf_path, csv_path)
        QMessageBox.information(self, "Converted", f"PDF converted to {csv_path}. Now import it via Import CSV.")


    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT h.id, h.date, e.full_name, e.nickname, h.start_time, h.end_time, h.hours_worked
                FROM employee_hours h
                JOIN employees e ON h.employee_id = e.id
                ORDER BY h.date
            """)
            rows = cursor.fetchall()

        self.table.setRowCount(len(rows))
        self.ids = []
        for r, (row_id, date, full_name, nickname, start, end, hours) in enumerate(rows):
            self.ids.append(row_id)
            display_name = nickname or full_name
            self.table.setItem(r, 0, QTableWidgetItem(date))
            self.table.setItem(r, 1, QTableWidgetItem(display_name))
            self.table.setItem(r, 2, QTableWidgetItem(start or ""))
            self.table.setItem(r, 3, QTableWidgetItem(end or ""))
            self.table.setItem(r, 4, QTableWidgetItem(f"{hours:.2f}"))

    def save_changes(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            for r, row_id in enumerate(self.ids):
                date = self.table.item(r, 0).text()
                emp_name = self.table.item(r, 1).text()
                start = self.table.item(r, 2).text()
                end = self.table.item(r, 3).text()
                try:
                    t1 = datetime.strptime(start, "%I:%M %p")
                    t2 = datetime.strptime(end, "%I:%M %p")
                    hours = (t2 - t1).seconds / 3600.0
                except Exception:
                    try:
                        hours = float(self.table.item(r, 4).text())
                    except Exception:
                        hours = 0.0
                # Resolve employee_id
                cursor.execute("SELECT id FROM employees WHERE full_name=? OR nickname=?", (emp_name, emp_name))
                match = cursor.fetchone()
                if not match:
                    continue
                (emp_id,) = match
                cursor.execute(
                    "UPDATE employee_hours SET date=?, employee_id=?, start_time=?, end_time=?, hours_worked=? WHERE id=?",
                    (date, emp_id, start, end, hours, row_id),
                )

        QMessageBox.information(self, "Saved", "Changes saved to database.")
        self.load_data()

    def delete_selected(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select at least one row to delete.")
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {len(selected)} selected record(s)?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        ids_to_delete = [self.ids[idx.row()] for idx in selected]
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("DELETE FROM employee_hours WHERE id=?", [(i,) for i in ids_to_delete])

        self.load_data()
        QMessageBox.information(self, "Deleted", f"Deleted {len(ids_to_delete)} record(s).")


class CreditedHoursTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Credited Hours"))

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Employee", "Credited Hours"])
        layout.addWidget(self.table)

        add_refresh_shortcut(self, self.load_data)
        self.load_data()

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT e.full_name, e.nickname, SUM(c.hours)
                FROM credit_audit c
                JOIN employees e ON c.employee_id = e.id
                GROUP BY e.id
            """)
            rows = cursor.fetchall()

        self.table.setRowCount(len(rows))
        for r, (full_name, nickname, hrs) in enumerate(rows):
            display_name = nickname or full_name
            self.table.setItem(r, 0, QTableWidgetItem(display_name))
            self.table.setItem(r, 1, QTableWidgetItem(f"{hrs:.2f}"))


class EfficiencyTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Efficiency Report"))

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Employee", "Hours Worked", "Credited Hours", "Efficiency"]
        )
        layout.addWidget(self.table)

        add_refresh_shortcut(self, self.load_data)
        self.load_data()

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()

            # Worked
            cursor.execute("""
                SELECT e.full_name, e.nickname, SUM(h.hours_worked)
                FROM employee_hours h
                JOIN employees e ON h.employee_id = e.id
                GROUP BY e.id
            """)
            worked_map = {full_name: (nickname, total or 0) for full_name, nickname, total in cursor.fetchall()}

            # Credited
            cursor.execute("""
                SELECT e.full_name, e.nickname, SUM(c.hours)
                FROM credit_audit c
                JOIN employees e ON c.employee_id = e.id
                GROUP BY e.id
            """)
            credits_map = {full_name: (nickname, total or 0) for full_name, nickname, total in cursor.fetchall()}

        employees = set(worked_map.keys()) | set(credits_map.keys())
        self.table.setRowCount(len(employees))

        for r, full_name in enumerate(sorted(employees)):
            nickname, worked = worked_map.get(full_name, (None, 0))
            nickname_c, produced = credits_map.get(full_name, (None, 0))
            display_name = nickname or nickname_c or full_name
            efficiency = produced / worked if worked > 0 else 0.0

            self.table.setItem(r, 0, QTableWidgetItem(display_name))
            self.table.setItem(r, 1, QTableWidgetItem(f"{worked:.2f}"))
            self.table.setItem(r, 2, QTableWidgetItem(f"{produced:.2f}"))
            eff_item = QTableWidgetItem(f"{efficiency:.2f}")
            eff_item.setBackground(Qt.green if efficiency >= 1.5 else Qt.red)
            self.table.setItem(r, 3, eff_item)


class CreditAuditLogTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Credit Audit Log"))

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Changes")
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)
        self.save_btn.clicked.connect(self.save_changes)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "RO #", "Employee", "Hours", "Note"])
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        layout.addWidget(self.table)

        add_refresh_shortcut(self, self.load_data)
        self.load_data()

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                           SELECT c.id, c.date, r.ro_number, e.full_name, e.nickname, c.hours, c.note
                           FROM credit_audit c
                                    JOIN employees e ON c.employee_id = e.id
                                    JOIN repair_orders r ON c.ro_id = r.id
                           ORDER BY c.id DESC
                           """)
            rows = cursor.fetchall()

        self.table.setRowCount(len(rows))
        self.ids = []
        for r, (row_id, date, ro_number, full_name, nickname, hrs, note) in enumerate(rows):
            self.ids.append(row_id)
            display_name = nickname or full_name

            date_edit = SafeDateEdit()
            date_edit.setDisplayFormat("MM/dd/yyyy")
            date_edit.setCalendarPopup(True)
            iso_str = date.split()[0]
            qdate = QDate.fromString(iso_str, "yyyy-MM-dd")
            if qdate.isValid():
                date_edit.setDate(qdate)
            else:
                date_edit.setDate(QDate.currentDate())
            self.table.setCellWidget(r, 0, date_edit)

            self.table.setItem(r, 1, QTableWidgetItem(str(ro_number)))
            self.table.setItem(r, 2, QTableWidgetItem(display_name))
            self.table.setItem(r, 3, QTableWidgetItem(f"{hrs:.2f}"))
            self.table.setItem(r, 4, QTableWidgetItem(note or ""))

            for c in range(1, 5):
                item = self.table.item(r, c)
                if item:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def save_changes(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            for r, row_id in enumerate(self.ids):
                date_widget = self.table.cellWidget(r, 0)
                new_date = date_widget.date().toString("yyyy-MM-dd")
                cursor.execute("UPDATE credit_audit SET date=? WHERE id=?", (new_date, row_id))
        QMessageBox.information(self, "Saved", "Audit log dates updated.")
        self.load_data()


class ReportsPage(QTabWidget):
    def __init__(self):
        super().__init__()
        self.addTab(EmployeeHoursTab(), "Employee Hours")
        self.addTab(CreditedHoursTab(), "Credited Hours")
        self.addTab(CreditAuditLogTab(), "Credit Audit Log")
        self.addTab(EfficiencyTab(), "Efficiency")
