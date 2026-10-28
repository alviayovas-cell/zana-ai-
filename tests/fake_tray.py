from PySide6.QtCore import QObject, Signal


class FakeTray(QObject):
    open_requested = Signal()
    exit_requested = Signal()
    pause_toggled = Signal()

    def __init__(self):
        super().__init__()
        self.shown, self.status, self.notes = False, "", []
        self.pause_available, self.paused = False, False

    def set_pause_state(self, available, paused):
        self.pause_available, self.paused = available, paused

    def show(self):
        self.shown = True

    def hide(self):
        self.shown = False

    def set_status(self, text):
        self.status = text

    def notify(self, title, message):
        self.notes.append((title, message))
