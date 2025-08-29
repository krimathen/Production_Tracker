from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDateEdit, QPushButton
from PySide6.QtCore import QDate

class DatePickerDialog(QDialog):
    def __init__(self, title="Select Date", default_date=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.selected_date = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(title))

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(default_date or QDate.currentDate())
        layout.addWidget(self.date_edit)

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        layout.addWidget(ok_btn)

    def accept(self):
        self.selected_date = self.date_edit.date()
        super().accept()
