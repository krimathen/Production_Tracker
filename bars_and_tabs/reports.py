
import csv
from collections import defaultdict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QTableWidget, QLabel, QTabWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QHBoxLayout, QAbstractItemView
)
from PySide6.QtCore import Qt
from datetime import datetime
from database import get_connection
from key_bindings import add_refresh_shortcut


class EmployeeHoursTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # --- Top buttons ---
        btn_layout = QHBoxLayout()
        self.import_btn = QPushButton("Import CSV")
        self.save_btn = QPushButton("Save Changes")
        self.delete_btn = QPushButton("Delete Selected")
        btn_layout.addWidget(self.import_btn)
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
                        employee = row["Name"].strip()
                        start = row["Start"].strip()
                        end = row["End"].strip()
                        try:
                            t1 = datetime.strptime(start, "%I:%M %p")
                            t2 = datetime.strptime(end, "%I:%M %p")
                            hours = (t2 - t1).seconds / 3600.0
                        except Exception:
                            hours = 0.0
                        cursor.execute(
                            "INSERT INTO employee_hours (date, employee, start_time, end_time, hours_worked) VALUES (?, ?, ?, ?, ?)",
                            (date, employee, start, end, hours),
                        )

            QMessageBox.information(self, "Import Successful", "CSV data imported successfully.")
            self.load_data()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to import CSV:\n{e}")

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, date, employee, start_time, end_time, hours_worked FROM employee_hours ORDER BY date")
            rows = cursor.fetchall()

        self.table.setRowCount(len(rows))
        self.ids = []
        for r, (row_id, date, employee, start, end, hours) in enumerate(rows):
            self.ids.append(row_id)
            self.table.setItem(r, 0, QTableWidgetItem(date))
            self.table.setItem(r, 1, QTableWidgetItem(employee))
            self.table.setItem(r, 2, QTableWidgetItem(start))
            self.table.setItem(r, 3, QTableWidgetItem(end))
            self.table.setItem(r, 4, QTableWidgetItem(f"{hours:.2f}"))

    def save_changes(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            for r, row_id in enumerate(self.ids):
                date = self.table.item(r, 0).text()
                employee = self.table.item(r, 1).text()
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
                cursor.execute(
                    "UPDATE employee_hours SET date=?, employee=?, start_time=?, end_time=?, hours_worked=? WHERE id=?",
                    (date, employee, start, end, hours, row_id),
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
            cursor.execute("SELECT employee, SUM(hours) FROM credit_audit GROUP BY employee")
            rows = cursor.fetchall()

        self.table.setRowCount(len(rows))
        for r, (emp, hrs) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(emp))
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
            cursor.execute("SELECT employee, SUM(hours_worked) FROM employee_hours GROUP BY employee")
            worked_map = {emp: total or 0 for emp, total in cursor.fetchall()}

            cursor.execute("SELECT employee, SUM(hours) FROM credit_audit GROUP BY employee")
            credits_map = {emp: total or 0 for emp, total in cursor.fetchall()}

        employees = set(worked_map.keys()) | set(credits_map.keys())
        self.table.setRowCount(len(employees))

        for r, emp in enumerate(sorted(employees)):
            worked = worked_map.get(emp, 0)
            produced = credits_map.get(emp, 0)
            efficiency = produced / worked if worked > 0 else 0.0

            self.table.setItem(r, 0, QTableWidgetItem(emp))
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

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "RO #", "Employee", "Hours", "Note"])
        layout.addWidget(self.table)

        # F5 key to refresh tab
        from key_bindings import add_refresh_shortcut
        add_refresh_shortcut(self, self.load_data)

        self.load_data()

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT date, ro_number, employee, hours, note
                FROM credit_audit
                ORDER BY id DESC
            """)
            rows = cursor.fetchall()

        self.table.setRowCount(len(rows))
        for r, (date, ro_number, emp, hrs, note) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(date))
            self.table.setItem(r, 1, QTableWidgetItem(str(ro_number)))
            self.table.setItem(r, 2, QTableWidgetItem(emp))
            self.table.setItem(r, 3, QTableWidgetItem(f"{hrs:.2f}"))
            self.table.setItem(r, 4, QTableWidgetItem(note or ""))

class ReportsPage(QTabWidget):
    def __init__(self):
        super().__init__()
        self.addTab(EmployeeHoursTab(), "Employee Hours")
        self.addTab(CreditedHoursTab(), "Credited Hours")
        self.addTab(CreditAuditLogTab(), "Credit Audit Log")
        self.addTab(EfficiencyTab(), "Efficiency")