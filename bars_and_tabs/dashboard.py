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
        conn = get_connection()
        cursor = conn.cursor()

        # --- Stage counts in workflow order ---
        STAGES = [
            "Scheduled",
            "Intake",
            "Disassembly",
            "Body",
            "Refinish",
            "Reassembly",
            "Mechanical",
            "Detail",
            "QC",
            "Delivered",
        ]

        cursor.execute("SELECT stage, COUNT(*) FROM repair_orders WHERE status != 'Closed' GROUP BY stage")
        raw_counts = dict(cursor.fetchall())

        self.stage_table.setRowCount(len(STAGES))
        for r, stage in enumerate(STAGES):
            count = raw_counts.get(stage, 0)
            self.stage_table.setItem(r, 0, QTableWidgetItem(stage))
            self.stage_table.setItem(r, 1, QTableWidgetItem(str(count)))

        # --- Hours assigned per employee ---
        assigned = defaultdict(lambda: defaultdict(float))
        cursor.execute("SELECT tech, painter, mechanic, body_hours, refinish_hours, mechanical_hours FROM repair_orders WHERE status != 'Closed'")
        for tech, painter, mech, body, refinish, mech_hours in cursor.fetchall():
            if tech and tech != "Unassigned":
                assigned[tech]["Tech"] += body
            if painter and painter != "Unassigned":
                assigned[painter]["Painter"] += refinish
            if mech and mech != "Unassigned":
                assigned[mech]["Mechanic"] += mech_hours

        conn.close()

        # Flatten & sort by role order (Tech → Painter → Mechanic)
        ROLE_ORDER = {"Tech": 0, "Painter": 1, "Mechanic": 2}
        flat_rows = []
        for emp, roles in assigned.items():
            for role, hours in roles.items():
                flat_rows.append((emp, role, hours))

        flat_rows.sort(key=lambda x: (ROLE_ORDER.get(x[1], 99), x[0].lower()))

        self.emp_table.setRowCount(len(flat_rows))
        for r, (emp, role, hours) in enumerate(flat_rows):
            self.emp_table.setItem(r, 0, QTableWidgetItem(emp))
            self.emp_table.setItem(r, 1, QTableWidgetItem(role))
            self.emp_table.setItem(r, 2, QTableWidgetItem(f"{hours:.2f}"))