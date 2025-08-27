from PySide6.QtWidgets import QMessageBox
from database import get_connection


def delete_with_confirmation(parent, table_name: str, id_column: str, ids: list[int], refresh_callback=None):
    """
    Generic delete utility with confirmation dialog.
    - parent: QWidget to anchor QMessageBox
    - table_name: name of the table (e.g. 'repair_orders')
    - id_column: name of the primary key column (e.g. 'id')
    - ids: list of IDs to delete
    - refresh_callback: optional function to call after delete (e.g. page.load_data)
    """
    if not ids:
        QMessageBox.warning(parent, "No Selection", "Please select a record to delete.")
        return

    if len(ids) == 1:
        msg = f"Are you sure you want to delete RO ID {ids[0]}?"
    else:
        msg = "Are you sure you want to delete multiple ROs?"

    reply = QMessageBox.question(
        parent,
        "Confirm Delete",
        msg,
        QMessageBox.Yes | QMessageBox.No,
    )

    if reply == QMessageBox.Yes:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                f"DELETE FROM {table_name} WHERE {id_column} = ?",
                [(i,) for i in ids],
            )

        if len(ids) == 1:
            QMessageBox.information(parent, "Deleted", f"Deleted RO ID {ids[0]}.")
        else:
            QMessageBox.information(parent, "Deleted", f"Deleted {len(ids)} ROs.")

        if refresh_callback:
            refresh_callback()
