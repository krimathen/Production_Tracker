from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLineEdit, QLabel, QCheckBox, QMessageBox, QDialog,QTabWidget
)
from utilities.employees import Employee
from key_bindings import add_refresh_shortcut, add_enter_shortcut


class Employee_Settings(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # Employee list
        self.employee_list = QListWidget()
        self.employee_list.itemDoubleClicked.connect(self.open_role_editor)
        layout.addWidget(QLabel("Employees"))
        layout.addWidget(self.employee_list)

        # Input + buttons
        input_layout = QHBoxLayout()
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("Employee name")
        input_layout.addWidget(self.input_name)

        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self.add_employee)
        input_layout.addWidget(add_btn)

        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self.delete_employee)
        input_layout.addWidget(del_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_list)
        input_layout.addWidget(refresh_btn)

        layout.addLayout(input_layout)

        self.refresh_list()

        # adds keyboard shortcuts
        add_refresh_shortcut(self, self.refresh_list)
        add_enter_shortcut(self.input_name, self.add_employee)

    def refresh_list(self):
        self.employee_list.clear()
        for emp in Employee.all():
            roles_str = ", ".join(emp.roles) if emp.roles else "No Roles"
            self.employee_list.addItem(f"{emp.name} [{roles_str}]")

    def add_employee(self):
        name = self.input_name.text().strip()
        if not name:
            return
        Employee.add(name)
        self.input_name.clear()
        self.refresh_list()

    def delete_employee(self):
        item = self.employee_list.currentItem()
        if not item:
            return
        name = item.text().split(" [")[0]  # extract just the name
        emp = next((e for e in Employee.all() if e.name == name), None)
        if not emp:
            return
        reply = QMessageBox.question(self, "Confirm Delete", f"Delete {name}?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            Employee.delete(emp.id)
            self.refresh_list()

    def open_role_editor(self, item):
        # get selected employee by name
        text = item.text()
        name = text.split(" [")[0]
        emp = next((e for e in Employee.all() if e.name == name), None)
        if not emp:
            return

        dialog = RoleEditorDialog(emp.id, emp.name, emp.roles, self)
        if dialog.exec():
            self.refresh_list()


class RoleEditorDialog(QDialog):
    def __init__(self, emp_id, emp_name, current_roles, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Employee: {emp_name}")
        self.emp_id = emp_id

        layout = QVBoxLayout(self)

        # Editable name field
        self.name_field = QLineEdit()
        self.name_field.setText(emp_name)
        layout.addWidget(QLabel("Name:"))
        layout.addWidget(self.name_field)

        # Role checkboxes
        self.roles = {
            "Estimator": QCheckBox("Estimator"),
            "Tech": QCheckBox("Tech"),
            "Painter": QCheckBox("Painter"),
            "Mechanic": QCheckBox("Mechanic"),
        }
        for role, cb in self.roles.items():
            cb.setChecked(role in current_roles)
            layout.addWidget(cb)

        # Save button
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save)
        layout.addWidget(save_btn)

    def save(self):
        # Save updated name
        new_name = self.name_field.text().strip()
        if new_name:
            Employee.rename(self.emp_id, new_name)

        # Save updated roles
        selected_roles = [role for role, cb in self.roles.items() if cb.isChecked()]
        Employee.set_roles(self.emp_id, selected_roles)

        self.accept()

class Status_Settings(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.status_list = QListWidget()
        layout.addWidget(QLabel("Statuses"))
        layout.addWidget(self.status_list)

        # Input + buttons
        input_layout = QHBoxLayout()
        self.input_status = QLineEdit()
        self.input_status.setPlaceholderText("Status name")
        input_layout.addWidget(self.input_status)

        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self.add_status)
        input_layout.addWidget(add_btn)

        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self.delete_status)
        input_layout.addWidget(del_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_list)
        input_layout.addWidget(refresh_btn)

        layout.addLayout(input_layout)

        self.refresh_list()

        add_refresh_shortcut(self, self.refresh_list)
        add_enter_shortcut(self.input_status, self.add_status)

    def refresh_list(self):
        from database import get_connection
        self.status_list.clear()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM settings_statuses ORDER BY name")
        for (name,) in cursor.fetchall():
            self.status_list.addItem(name)
        conn.close()

    def add_status(self):
        from database import get_connection
        name = self.input_status.text().strip()
        if not name:
            return
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO settings_statuses(name) VALUES(?)", (name,))
        conn.commit()
        conn.close()
        self.input_status.clear()
        self.refresh_list()

    def delete_status(self):
        from database import get_connection
        item = self.status_list.currentItem()
        if not item:
            return
        name = item.text()
        reply = QMessageBox.question(self, "Confirm Delete", f"Delete status '{name}'?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings_statuses WHERE name=?", (name,))
            conn.commit()
            conn.close()
            self.refresh_list()


class SettingsPage(QTabWidget):
    def __init__(self):
        super().__init__()
        self.addTab(Employee_Settings(), "Employees")
        self.addTab(Status_Settings(), "Statuses")


