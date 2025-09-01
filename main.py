import sys
from PySide6.QtWidgets import QApplication
from database import initialize_db, migrate_db, migrate_dates
from mainwindow import MainWindow

def main():
    initialize_db()
    migrate_db()
    migrate_dates()

    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
