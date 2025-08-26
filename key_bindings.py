from PySide6.QtGui import QShortcut, QKeySequence


def add_refresh_shortcut(widget, refresh_callable):
    """
    Attach F5 to a widget so that pressing it calls refresh_callable().
    Works on any QWidget (tab/page).
    """
    shortcut = QShortcut(QKeySequence("F5"), widget)
    shortcut.activated.connect(refresh_callable)
    return shortcut

def add_enter_shortcut(widget, enter_callable):
    """
    Attach Enter/Return key to a widget so pressing it calls enter_callable().
    Useful for input fields like QLineEdit.
    """
    shortcut = QShortcut(QKeySequence("Return"), widget)
    shortcut.activated.connect(enter_callable)
    return shortcut