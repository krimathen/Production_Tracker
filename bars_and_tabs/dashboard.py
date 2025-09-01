from collections import defaultdict
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHBoxLayout
from database import get_connection


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)  # side by side

        # --- Left: ROs per stage ---
        stage_layout = QVBoxLayout()
        stage_layout.addWidget(QLabel("Repair Orders by Stage"))
        self.stage_table = QTableWidget()
        self.stage_table.setColumnCount(2)
        self.stage_table.setHorizontalHeaderLabels(["Stage", "Count"])
        stage_layout.addWidget(self.stage_table)

        # --- Right: Hours assigned per employee ---
        emp_layout = QVBoxLayout()
        emp_layout.addWidget(QLabel("Assigned Hours by Employee"))
        self.emp_table = QTableWidget()
        self.emp_table.setColumnCount(3)
        self.emp_table.setHorizontalHeaderLabels(["Employee", "Role", "Assigned Hours"])
        emp_layout.addWidget(self.emp_table)

        layout.addLayout(stage_layout, stretch=1)
        layout.addLayout(emp_layout, stretch=2)

        # Enable F5 refresh
        from key_bindings import add_refresh_shortcut
        add_refresh_shortcut(self, self.load_data)

        self.load_data()

    def load_data(self):
        with get_connection() as conn:
            cursor = conn.cursor()

            # --- Stage counts ---
            STAGES = [
                "Scheduled", "Intake", "Disassembly", "Body", "Refinish",
                "Reassembly", "Mechanical", "Detail", "QC", "Delivered"
            ]
            cursor.execute("SELECT stage, COUNT(*) FROM repair_orders WHERE status != 'Closed' GROUP BY stage")
            raw_counts = dict(cursor.fetchall())

            self.stage_table.setRowCount(len(STAGES))
            for r, stage in enumerate(STAGES):
                count = raw_counts.get(stage, 0)
                self.stage_table.setItem(r, 0, QTableWidgetItem(stage))
                self.stage_table.setItem(r, 1, QTableWidgetItem(str(count)))

            # --- Hours assigned per employee (from allocations) ---
            cursor.execute("""
                           SELECT e.full_name, e.nickname, a.role, SUM(r.hours_total * a.percent / 100.0)
                           FROM ro_hours_allocation a
                                    JOIN repair_orders r ON a.ro_id = r.id
                                    JOIN employees e ON a.employee_id = e.id
                           WHERE r.status != 'Closed'
                           GROUP BY e.id, a.role
                           """)
            rows = cursor.fetchall()

            self.emp_table.setRowCount(len(rows))
            for r, (full_name, nickname, role, hours) in enumerate(rows):
                display_name = nickname or full_name
                self.emp_table.setItem(r, 0, QTableWidgetItem(display_name))
                self.emp_table.setItem(r, 1, QTableWidgetItem(role))
                self.emp_table.setItem(r, 2, QTableWidgetItem(f"{hours:.2f}"))
