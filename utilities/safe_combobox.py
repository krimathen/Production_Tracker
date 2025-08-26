from PySide6.QtWidgets import QComboBox

class SafeComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events to prevent accidental changes."""
    def wheelEvent(self, event):
        event.ignore()
