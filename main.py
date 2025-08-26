import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QStackedWidget, QLabel
)

from bars_and_tabs.sidebar import Sidebar
from bars_and_tabs.dashboard import DashboardPage
from bars_and_tabs.repair_orders import RepairOrdersPage
from bars_and_tabs.reports import ReportsPage
from bars_and_tabs.settings import SettingsPage
from database import initialize_db, migrate_db

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
        self.stack.addWidget(DashboardPage())
        self.stack.addWidget(RepairOrdersPage())
        self.stack.addWidget(ReportsPage())
        self.stack.addWidget(SettingsPage())   # instead of just Employee_Settings()


        # Sidebar (pass in stack so buttons can control it)
        sidebar = Sidebar(self.stack)
        layout.insertWidget(0, sidebar, stretch=1)

def main():
    initialize_db()  # make sure DB and tables exist
    migrate_db()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

#creates the main window
if __name__ == "__main__":
    main()
