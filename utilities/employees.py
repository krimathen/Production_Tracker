from database import get_connection

class Employee:
    def __init__(self, emp_id, name, roles=None):
        self.id = emp_id
        self.name = name
        self.roles = roles if roles else []

    @staticmethod
    def all():
        """Load all employees and their roles."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM employees ORDER BY name")
        employees = []
        for emp_id, name in cursor.fetchall():
            cursor.execute("SELECT role FROM employee_roles WHERE employee_id=?", (emp_id,))
            roles = [r[0] for r in cursor.fetchall()]
            employees.append(Employee(emp_id, name, roles))
        conn.close()
        return employees

    @staticmethod
    def by_role(role):
        """Return employees who have the given role."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.id, e.name FROM employees e
            JOIN employee_roles r ON e.id = r.employee_id
            WHERE r.role=? ORDER BY e.name
            """,
            (role,),
        )
        employees = [Employee(emp_id, name, [role]) for emp_id, name in cursor.fetchall()]
        conn.close()
        return employees

    @staticmethod
    def add(name):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO employees(name) VALUES(?)", (name,))
        conn.commit()
        conn.close()

    @staticmethod
    def delete(emp_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM employees WHERE id=?", (emp_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def set_roles(emp_id, roles):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM employee_roles WHERE employee_id=?", (emp_id,))
        for role in roles:
            cursor.execute("INSERT INTO employee_roles(employee_id, role) VALUES(?, ?)", (emp_id, role))
        conn.commit()
        conn.close()

    @staticmethod
    def rename(emp_id, new_name):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE employees SET name=? WHERE id=?", (new_name, emp_id))
        conn.commit()
        conn.close()