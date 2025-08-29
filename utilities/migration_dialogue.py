from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton

class NameMigrationDialog(QDialog):
    def __init__(self, short_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Employee Name")
        self.full_name = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Current short name: {short_name}"))
        layout.addWidget(QLabel("Enter full name:"))

        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save)
        layout.addWidget(save_btn)

    def save(self):
        self.full_name = self.name_field.text().strip()
        if self.full_name:
            self.accept()
        else:
            self.reject()