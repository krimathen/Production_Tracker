from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton


class Sidebar(QWidget):
    def __init__(self, stack):
        super().__init__()
        self.stack = stack

        layout = QVBoxLayout(self)

        # Create buttons
        btn_dashboard = QPushButton("Dashboard")
        btn_repair_orders = QPushButton("ROs")
        btn_reports = QPushButton("Reports")
        btn_settings = QPushButton("Settings")

        # Add buttons
        layout.addWidget(btn_dashboard)
        layout.addWidget(btn_repair_orders)
        layout.addWidget(btn_reports)
        layout.addWidget(btn_settings)
        layout.addStretch()

        # Connect buttons to stack pages
        btn_dashboard.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        btn_repair_orders.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        btn_reports.clicked.connect(lambda: self.stack.setCurrentIndex(2))
        btn_settings.clicked.connect(lambda: self.stack.setCurrentIndex(3))
