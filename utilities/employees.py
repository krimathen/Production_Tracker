from database import get_connection

class Employee:
    def __init__(self, emp_id, full_name, roles=None, nickname=None):
        self.id = emp_id
        self.full_name = full_name
        self.nickname = nickname
        self.roles = roles if roles else []

    @staticmethod
    def all():
        """Load all employees with their roles."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, full_name, nickname FROM employees ORDER BY full_name")
            employees = []
            for emp_id, full_name, nickname in cursor.fetchall():
                cursor.execute("SELECT role FROM employee_roles WHERE employee_id=?", (emp_id,))
                roles = [r[0] for r in cursor.fetchall()]
                employees.append(Employee(emp_id, full_name, roles, nickname))
        return employees

    @staticmethod
    def by_role(role):
        """Return employees who have the given role."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT e.id, e.full_name, e.nickname
                FROM employees e
                JOIN employee_roles r ON e.id = r.employee_id
                WHERE r.role=?
                ORDER BY e.full_name
            """, (role,))
            employees = []
            for emp_id, full_name, nickname in cursor.fetchall():
                cursor.execute("SELECT role FROM employee_roles WHERE employee_id=?", (emp_id,))
                roles = [r[0] for r in cursor.fetchall()]
                employees.append(Employee(emp_id, full_name, roles, nickname))
        return employees

    @staticmethod
    def add(full_name, nickname=None, roles=None):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO employees(full_name, nickname) VALUES(?, ?)", (full_name, nickname))
            emp_id = cursor.lastrowid
            if roles:
                cursor.executemany(
                    "INSERT INTO employee_roles(employee_id, role) VALUES(?, ?)",
                    [(emp_id, role) for role in roles]
                )

    @staticmethod
    def delete(emp_id):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM employees WHERE id=?", (emp_id,))

    @staticmethod
    def set_roles(emp_id, roles):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM employee_roles WHERE employee_id=?", (emp_id,))
            cursor.executemany(
                "INSERT INTO employee_roles(employee_id, role) VALUES(?, ?)",
                [(emp_id, role) for role in roles]
            )

    @staticmethod
    def rename(emp_id, new_name):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE employees SET full_name=? WHERE id=?", (new_name, emp_id))

    @staticmethod
    def set_nickname(emp_id, nickname):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE employees SET nickname=? WHERE id=?", (nickname, emp_id))
