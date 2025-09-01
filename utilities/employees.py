from database import get_connection

class Employee:
    def __init__(self, emp_id, full_name, roles=None, nickname=None):
        self.id = emp_id
        self.full_name = full_name     # canonical full name
        self.nickname = nickname       # optional short name
        # stored as list for compatibility with old code, but schema v2 only has one role
        self.roles = roles if roles else []

    @staticmethod
    def all():
        """Load all employees (v2 schema has one role column per employee)."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, full_name, nickname, role FROM employees ORDER BY full_name")
            employees = []
            for emp_id, full_name, nickname, role in cursor.fetchall():
                roles = [role] if role else []
                employees.append(Employee(emp_id, full_name, roles, nickname))
        return employees

    @staticmethod
    def by_role(role):
        """Return employees who have the given role (single role in v2 schema)."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, full_name, nickname, role
                FROM employees
                WHERE role=?
                ORDER BY full_name
                """,
                (role,),
            )
            return [Employee(emp_id, full_name, [role], nickname)
                    for emp_id, full_name, nickname, role in cursor.fetchall()]

    @staticmethod
    def add(full_name, nickname=None, role=None):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO employees(full_name, nickname, role) VALUES(?, ?, ?)",
                (full_name, nickname, role),
            )

    @staticmethod
    def delete(emp_id):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM employees WHERE id=?", (emp_id,))

    @staticmethod
    def set_role(emp_id, role):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE employees SET role=? WHERE id=?", (role, emp_id))

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
