from database import get_connection

class Employee:
    def __init__(self, emp_id, name, roles=None, nickname=None):
        self.id = emp_id
        self.name = name           # full name (canonical)
        self.nickname = nickname   # optional short name
        self.roles = roles if roles else []

    @staticmethod
    def all():
        """Load all employees and their roles."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, nickname FROM employees ORDER BY name")
            employees = []
            for emp_id, name, nickname in cursor.fetchall():
                cursor.execute("SELECT role FROM employee_roles WHERE employee_id=?", (emp_id,))
                roles = [r[0] for r in cursor.fetchall()]
                employees.append(Employee(emp_id, name, roles, nickname))
        return employees

    @staticmethod
    def by_role(role):
        """Return employees who have the given role."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT e.id, e.name, e.nickname
                FROM employees e
                JOIN employee_roles r ON e.id = r.employee_id
                WHERE r.role=? ORDER BY e.name
                """,
                (role,),
            )
            employees = [Employee(emp_id, name, [role], nickname) for emp_id, name, nickname in cursor.fetchall()]
        return employees

    @staticmethod
    def add(name):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO employees(name) VALUES(?)", (name,))

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
            for role in roles:
                cursor.execute("INSERT INTO employee_roles(employee_id, role) VALUES(?, ?)", (emp_id, role))

    @staticmethod
    def rename(emp_id, new_name):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE employees SET name=? WHERE id=?", (new_name, emp_id))

    @staticmethod
    def set_nickname(emp_id, nickname):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE employees SET nickname=? WHERE id=?", (nickname, emp_id))
