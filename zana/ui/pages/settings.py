"""Settings page: wake-word toggle, spoken replies, microphone checks."""

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ...voice.engine import VoiceState
from ...voice.mic import MIC_PRIVACY_HINT, MicError, measure_input_level
from ..status_pill import StatusPill
from ..toggle import ToggleSwitch


class _MicTestWorker(QThread):
    result = Signal(str, bool)  # message, ok

    def run(self) -> None:
        try:
            rms, all_zero = measure_input_level(1.5)
        except MicError as e:
            self.result.emit(str(e), False)
            return
        if all_zero:
            self.result.emit("The microphone returned only silence - it may be muted or "
                             "blocked. " + MIC_PRIVACY_HINT, False)
        else:
            self.result.emit(f"Microphone works (input level {rms:.4f}). "
                             "Speak while testing to see a higher value.", True)


class SettingsPage(QWidget):
    wake_toggled = Signal(bool)
    speak_toggled = Signal(bool)
    startup_toggled = Signal(bool)
    tray_toggled = Signal(bool)
    follow_up_changed = Signal(int)
    hands_free_requested = Signal()

    def __init__(self, wake_enabled: bool, speak_replies: bool,
                 launch_at_startup: bool = False, close_to_tray: bool = False,
                 follow_up_seconds: int = 8, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)       # the page scrolls, so nothing is squashed in small windows
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("chatScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 28, 40, 28)
        layout.setSpacing(16)
        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(10)

        heading = QLabel("Hands-free voice")
        heading.setObjectName("cardTitle")
        box.addWidget(heading)

        # Always-visible answer to "is Zana listening right now?"
        banner = QFrame()
        banner.setObjectName("banner")
        banner.setMinimumHeight(54)
        brow = QHBoxLayout(banner)
        brow.setContentsMargins(16, 12, 16, 12)
        self.listen_pill = StatusPill(large=True)
        brow.addWidget(self.listen_pill, 1)
        box.addWidget(banner)

        self.hands_free_button = QPushButton("Turn on everything for fully hands-free use")
        self.hands_free_button.setObjectName("sendButton")
        self.hands_free_button.setCursor(Qt.PointingHandCursor)
        self.hands_free_button.setMinimumHeight(44)
        self.hands_free_button.setToolTip(
            "Listen for “Hey Zana”, start with Windows, and keep running in the tray.")
        self.hands_free_button.clicked.connect(self.hands_free_requested)
        hf_row = QHBoxLayout()
        hf_row.addWidget(self.hands_free_button)
        hf_row.addStretch(1)
        box.addLayout(hf_row)

        self.wake_check = ToggleSwitch("Listen for “Hey Zana” in the background")
        self.wake_check.setChecked(wake_enabled)
        self.wake_check.toggled.connect(self.wake_toggled)
        box.addWidget(self.wake_check)
        note = QLabel("Uses your microphone while Zana is open, including when minimized. "
                      "Audio is processed on this PC and is not saved or sent anywhere.")
        note.setObjectName("pageSub")
        note.setWordWrap(True)
        box.addWidget(note)

        self.speak_check = ToggleSwitch("Speak replies aloud after voice commands")
        self.speak_check.setChecked(speak_replies)
        self.speak_check.toggled.connect(self.speak_toggled)
        box.addWidget(self.speak_check)

        fu_row = QHBoxLayout()
        fu_label = QLabel("Keep the conversation open after a reply for")
        self.follow_up_spin = QSpinBox()
        self.follow_up_spin.setRange(0, 60)
        self.follow_up_spin.setSuffix(" seconds")
        self.follow_up_spin.setSpecialValueText("Off (say “Hey Zana” every time)")
        self.follow_up_spin.setValue(follow_up_seconds)
        self.follow_up_spin.valueChanged.connect(self.follow_up_changed)
        fu_row.addWidget(fu_label)
        fu_row.addWidget(self.follow_up_spin)
        fu_row.addStretch(1)
        box.addLayout(fu_row)
        fu_note = QLabel("During this time you can keep talking without repeating “Hey Zana”. "
                         "Say “thanks” or “stop” to end it early.")
        fu_note.setObjectName("pageSub")
        fu_note.setWordWrap(True)
        box.addWidget(fu_note)

        self.status_label = QLabel("Microphone off")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        box.addWidget(self.status_label)

        row = QHBoxLayout()
        self.test_button = QPushButton("Test microphone")
        self.privacy_button = QPushButton("Open Windows microphone settings")
        for b in (self.test_button, self.privacy_button):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        row.addStretch(1)
        box.addLayout(row)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        self.test_result.setObjectName("pageSub")
        box.addWidget(self.test_result)

        layout.addWidget(card)

        card2 = QFrame()
        card2.setObjectName("card")
        box2 = QVBoxLayout(card2)
        box2.setContentsMargins(22, 20, 22, 20)
        box2.setSpacing(10)
        h2 = QLabel("Background & startup")
        h2.setObjectName("cardTitle")
        box2.addWidget(h2)
        self.startup_check = ToggleSwitch("Launch Zana at Windows startup")
        self.startup_check.setChecked(launch_at_startup)
        self.startup_check.toggled.connect(self.startup_toggled)
        box2.addWidget(self.startup_check)
        n2 = QLabel("Starts Zana in the tray after you sign in to Windows (it cannot run before sign-in). "
                    "You can also manage this in Task Manager > Startup apps.")
        n2.setObjectName("pageSub")
        n2.setWordWrap(True)
        box2.addWidget(n2)
        self.tray_check = ToggleSwitch("Keep running in the system tray when I close the window")
        self.tray_check.setChecked(close_to_tray)
        self.tray_check.toggled.connect(self.tray_toggled)
        box2.addWidget(self.tray_check)
        n3 = QLabel("Use the tray icon to open Zana or exit completely.")
        n3.setObjectName("pageSub")
        box2.addWidget(n3)
        self.background_message = QLabel("")
        self.background_message.setObjectName("pageSub")
        self.background_message.setWordWrap(True)
        box2.addWidget(self.background_message)
        layout.addWidget(card2)
        layout.addStretch(1)

        self.test_button.clicked.connect(self._run_test)
        self.privacy_button.clicked.connect(self._open_privacy)
        self._worker = None

    def set_startup_checked(self, on: bool, message: str = "") -> None:
        self.startup_check.blockSignals(True)
        self.startup_check.setChecked(on)
        self.startup_check.blockSignals(False)
        self.background_message.setText(message)

    def set_wake_checked(self, on: bool) -> None:
        self.wake_check.blockSignals(True)
        self.wake_check.setChecked(on)
        self.wake_check.blockSignals(False)

    def set_status(self, state: VoiceState, detail: str) -> None:
        self.listen_pill.set_state(state, detail)
        text = detail or state.value
        # The banner above says what Zana is doing; this line only explains problems.
        self.status_label.setText(f"Problem: {detail}" if state is VoiceState.ERROR
                                  else f"Status: {text}")
        self.status_label.setVisible(state in (VoiceState.ERROR, VoiceState.STARTING))

    def _run_test(self) -> None:
        self.test_button.setEnabled(False)
        self.test_result.setText("Testing…")
        self._worker = _MicTestWorker(self)
        self._worker.result.connect(self._show_test)
        self._worker.start()

    def _show_test(self, message: str, ok: bool) -> None:
        self.test_result.setText(("✔ " if ok else "⚠ ") + message)
        self.test_button.setEnabled(True)

    def _open_privacy(self) -> None:
        os.startfile("ms-settings:privacy-microphone")
