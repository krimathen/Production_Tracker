import csv
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget,
    QFileDialog, QInputDialog, QMessageBox, QDialog
)
from PySide6.QtCore import QDate
from openpyxl import Workbook

# Import your app modules
from bars_and_tabs.sidebar import Sidebar
from bars_and_tabs.dashboard import DashboardPage
from bars_and_tabs.repair_orders import RepairOrdersPage
from bars_and_tabs.reports import ReportsPage
from bars_and_tabs.settings import SettingsPage
from database import get_connection


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tech Efficiency Tracker")
        self.resize(1100, 700)

        # --- Central widget & layouts ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QHBoxLayout(central_widget)

        # Main stacked area
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=4)

        # --- Pages for the stack ---
        self.stack.addWidget(DashboardPage())      # index 0
        self.stack.addWidget(RepairOrdersPage())   # index 1
        self.stack.addWidget(ReportsPage())        # index 2
        self.stack.addWidget(SettingsPage())       # index 3

        # Sidebar (pass export callback)
        sidebar = Sidebar(self.stack, self.handle_export)
        layout.insertWidget(0, sidebar, stretch=1)

    # ---------------- Export Handler ----------------
    def handle_export(self):
        idx = self.stack.currentIndex()
        if idx == 1:   # Repair Orders
            self.export_repair_orders()
        elif idx == 2: # Reports
            self.export_reports()
        else:
            QMessageBox.information(self, "Export", "Export only works on ROs or Reports pages.")

    # ---------------- Repair Orders Export ----------------
    def export_repair_orders(self):
        choice, ok = QInputDialog.getItem(
            self, "Export ROs", "Choose export type:",
            ["All", "Open", "Closed", "Custom Date Range"], 0, False
        )
        if not ok:
            return

        query = "SELECT date, ro_number, estimator, tech, painter, mechanic, stage, status FROM repair_orders"
        params = []
        if choice == "Open":
            query += " WHERE status='Open'"
        elif choice == "Closed":
            query += " WHERE status='Closed'"
        elif choice == "Custom Date Range":
            from_date = QDate.currentDate().addDays(-90)
            to_date = QDate.currentDate()
            query += " WHERE date BETWEEN ? AND ?"
            params = [from_date.toString("yyyy-MM-dd"), to_date.toString("yyyy-MM-dd")]  # 🔥 ISO

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        file, _ = QFileDialog.getSaveFileName(self, "Save ROs CSV", "", "CSV Files (*.csv)")
        if not file:
            return

        with open(file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "RO#", "Estimator", "Tech", "Painter", "Mechanic", "Stage", "Status"])
            for row in rows:
                row = list(row)
                # Convert ISO date → MM/dd/yyyy
                row[0] = QDate.fromString(row[0], "yyyy-MM-dd").toString("MM/dd/yyyy")
                writer.writerow(row)

        QMessageBox.information(self, "Export", f"Repair Orders exported to {file}")

    # ---------------- Reports Export ----------------
    def export_reports(self):
        choice, ok = QInputDialog.getItem(
            self, "Export Reports", "Choose export type:",
            ["All", "Last 90 Days", "Custom Date Range"], 1, False
        )
        if not ok:
            return

        where = ""
        params = []

        if choice == "Last 90 Days":
            from_date = QDate.currentDate().addDays(-90).toString("yyyy-MM-dd")
            to_date = QDate.currentDate().toString("yyyy-MM-dd")
            where = "WHERE substr(date, 1, 10) BETWEEN ? AND ?"
            params = [from_date, to_date]

        elif choice == "Custom Date Range":
            from utilities.date_dialog import DatePickerDialog

            # Start date
            dlg1 = DatePickerDialog("Select Start Date", QDate.currentDate().addDays(-30), self)
            if dlg1.exec() != QDialog.Accepted:
                return
            from_date = dlg1.selected_date

            # End date
            dlg2 = DatePickerDialog("Select End Date", QDate.currentDate(), self)
            if dlg2.exec() != QDialog.Accepted:
                return
            to_date = dlg2.selected_date

            from_iso = from_date.toString("yyyy-MM-dd")
            to_iso = to_date.toString("yyyy-MM-dd")
            where = "WHERE substr(date, 1, 10) BETWEEN ? AND ?"
            params = [from_iso, to_iso]

        # Ask for output file
        file, _ = QFileDialog.getSaveFileName(self, "Save Reports", "", "Excel Files (*.xlsx)")
        if not file:
            return

        wb = Workbook()

        # --- Credited Hours ---
        ws1 = wb.active
        ws1.title = "Credited Hours"
        with get_connection() as conn:
            cur = conn.cursor()
            query = f"SELECT employee, SUM(hours) FROM credit_audit {where} GROUP BY employee"
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            rows = cur.fetchall()
        ws1.append(["Employee", "Credited Hours"])
        for emp, hrs in rows:
            ws1.append([emp, f"{hrs:.2f}"])

        # --- Efficiency ---
        ws2 = wb.create_sheet("Efficiency")
        with get_connection() as conn:
            cur = conn.cursor()
            query1 = f"SELECT employee, SUM(hours_worked) FROM employee_hours {where} GROUP BY employee"
            if params:
                cur.execute(query1, params)
            else:
                cur.execute(query1)
            worked_map = {emp: total or 0 for emp, total in cur.fetchall()}

            query2 = f"SELECT employee, SUM(hours) FROM credit_audit {where} GROUP BY employee"
            if params:
                cur.execute(query2, params)
            else:
                cur.execute(query2)
            credits_map = {emp: total or 0 for emp, total in cur.fetchall()}

        employees = set(worked_map.keys()) | set(credits_map.keys())
        ws2.append(["Employee", "Hours Worked", "Credited Hours", "Efficiency"])
        for emp in sorted(employees):
            worked = worked_map.get(emp, 0)
            produced = credits_map.get(emp, 0)
            eff = produced / worked if worked > 0 else 0
            ws2.append([emp, f"{worked:.2f}", f"{produced:.2f}", f"{eff:.2f}"])

        # --- Audit Log ---
        ws3 = wb.create_sheet("Audit Log")
        with get_connection() as conn:
            cur = conn.cursor()
            query3 = f"""
                SELECT date, ro_number, employee, hours, note
                FROM credit_audit
                {where}
                ORDER BY id DESC
            """
            if params:
                cur.execute(query3, params)
            else:
                cur.execute(query3)
            rows = cur.fetchall()
        ws3.append(["Date", "RO#", "Employee", "Hours", "Note"])
        for row in rows:
            row = list(row)
            if row[0]:
                iso_str = str(row[0]).split()[0]  # strip timestamp if present
                qdate = QDate.fromString(iso_str, "yyyy-MM-dd")
                if qdate.isValid():
                    row[0] = qdate.toString("MM/dd/yyyy")
                else:
                    row[0] = iso_str
            else:
                row[0] = ""
            ws3.append(row)

        # Save Excel file
        wb.save(file)
        QMessageBox.information(self, "Export", f"Reports exported to {file}")



