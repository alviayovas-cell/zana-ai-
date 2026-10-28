"""Main application window."""

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from .. import startup as startup_module
from ..apps.discovery import find_candidates
from ..apps.closer import AppCloser
from ..apps.registry import AppCommandHandler, AppError, AppRegistry
from ..config import CONFIG, resource_path
from ..core.assistant import Assistant
from ..core.ollama_client import OllamaClient
from ..settings import UserSettings
from ..startup import StartupError
from ..storage.history import HistoryStore
from ..voice.engine import VoiceState
from . import theme
from .chat_panel import ChatPanel
from .fade_stack import FadeStack
from .pages.applications import ApplicationsPage
from .pages.home import HomePage
from .pages.memory import MemoryPage
from .pages.settings import SettingsPage
from .sidebar import PAGES, Sidebar
from .system_status import StatusPoller
from .tray import TrayController, tray_available
from .visualizer import VisualizerState
from .voice_bridge import VoiceBridge
from .workers import AppCommandWorker, AppTaskWorker, ChatWorker

_AUTO = object()


class _Backdrop(QWidget):
    """Near-black background with a faint emerald glow behind the orb and in one corner."""

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG))
        w, h = self.width(), self.height()
        for cx, cy, radius, alpha in ((w * 0.60, h * 0.42, max(w, h) * 0.55, 30),
                                      (w * 0.98, h * 1.02, max(w, h) * 0.45, 22)):
            g = QRadialGradient(cx, cy, radius)
            c0 = QColor(theme.GREEN); c0.setAlpha(alpha)
            c1 = QColor(theme.GREEN); c1.setAlpha(0)
            g.setColorAt(0, c0)
            g.setColorAt(1, c1)
            p.fillRect(QRectF(0, 0, w, h), QBrush(g))
        p.end()


class MainWindow(QMainWindow):
    ready_reported = Signal()

    def __init__(
        self,
        assistant: Assistant | None = None,
        voice: VoiceBridge | None = None,
        settings: UserSettings | None = None,
        settings_path=None,
        autostart_voice: bool = True,
        app_registry: AppRegistry | None = None,
        app_finder=None,
        app_closer=None,
        tray=_AUTO,
        startup_api=None,
        startup_retries: int = 5,
        startup_retry_ms: int = 5000,
        runtime_retries: int = 30,
        runtime_retry_ms: int = 10000,
        status_probe=None,
    ):
        super().__init__()
        self.assistant = assistant or Assistant(
            OllamaClient(CONFIG.ollama_url, CONFIG.ollama_model),
            HistoryStore(CONFIG.db_path),
        )
        self._settings_path = settings_path or CONFIG.settings_path
        self.settings = settings or UserSettings.load(self._settings_path)
        self.voice = voice or VoiceBridge()
        self.app_registry = app_registry or AppRegistry(CONFIG.apps_path)
        self.app_closer = app_closer if app_closer is not None else AppCloser()
        self.app_commands = AppCommandHandler(
            self.app_registry, finder=app_finder or (lambda q: find_candidates(q)),
            closer=self.app_closer)
        self.startup_api = startup_api or startup_module
        self.confirm_app = self._ask_app_approval  # replaced in tests
        self.choose_windows = self._ask_which_windows  # replaced in tests
        self.confirm_force = self._ask_force_close      # replaced in tests
        self._worker: ChatWorker | None = None
        self._app_worker: AppTaskWorker | None = None
        self._busy = False
        self._stream_label: QLabel | None = None
        self._stream_text = ""
        self._from_voice = False
        self._chat_failed = False
        self._quitting = False
        self._tray_hint_shown = False
        self.ready = False
        self.background_start = False
        self._startup_phase = bool(self.settings.wake_enabled and autostart_voice)
        self._startup_retries_left = startup_retries if self._startup_phase else 0
        self._startup_retry_ms = startup_retry_ms
        self._runtime_retries = runtime_retries
        self._runtime_retry_ms = runtime_retry_ms
        self._retry_delay_ms = startup_retry_ms
        self._listening_established = False   # the listener has worked at least once this session
        self.confirm_hands_free = self._ask_hands_free  # replaced in tests
        self.voice.set_follow_up_seconds(self.settings.follow_up_seconds)
        self.setWindowTitle(CONFIG.app_name)
        icon_file = resource_path("assets/zana.ico")
        if icon_file.exists():
            self.setWindowIcon(QIcon(str(icon_file)))
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)

        root = _Backdrop()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = Sidebar()
        outer.addWidget(self.sidebar)

        self.stack = FadeStack()
        outer.addWidget(self.stack, 1)

        self.home = HomePage()
        self.chat_page = self._build_chat_page()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.chat_page)
        self.apps_page = ApplicationsPage(self.app_registry, finder=app_finder or (lambda q: find_candidates(q)))
        self.stack.addWidget(self.apps_page)
        self.memory_page = MemoryPage(self.assistant.store)
        self.stack.addWidget(self.memory_page)
        self.settings_page = SettingsPage(
            self.settings.wake_enabled, self.settings.speak_replies,
            self.settings.launch_at_startup, self.settings.close_to_tray,
            self.settings.follow_up_seconds)
        self.stack.addWidget(self.settings_page)
        assert self.stack.count() == len(PAGES)

        self.sidebar.page_selected.connect(self._on_page_selected)
        self.home.mic_toggled.connect(self._on_mic_toggled)
        self.home.suggestion_clicked.connect(self._on_suggestion)
        # Home "system status" chips (Ollama / Whisper / Piper). Off unless a probe is given.
        self._status_poller = None
        if status_probe is not None:
            self._status_poller = StatusPoller(status_probe, self)
            self._status_poller.result.connect(self.home.system_status.update_from)
            self._status_timer = QTimer(self)
            self._status_timer.setInterval(30_000)
            self._status_timer.timeout.connect(self._status_poller.refresh)
            self._status_timer.start()
            QTimer.singleShot(0, self._status_poller.refresh)
        self.chat.mic_toggled.connect(self._on_mic_toggled)
        self.chat.message_submitted.connect(self._on_message)

        self.apps_page.close_requested.connect(self._on_close_requested)
        self.settings_page.wake_toggled.connect(self._on_wake_toggled)
        self.settings_page.speak_toggled.connect(self._on_speak_toggled)
        self.settings_page.startup_toggled.connect(self._on_startup_toggled)
        self.settings_page.tray_toggled.connect(self._on_tray_toggled)
        self.settings_page.follow_up_changed.connect(self._on_follow_up_changed)
        self.settings_page.hands_free_requested.connect(self.enable_hands_free)
        self.voice.state_changed.connect(self._on_voice_state)
        self.voice.command_heard.connect(self._on_voice_command)
        self.voice.level.connect(self._on_voice_level)
        self.voice.speech_finished.connect(self._on_speech_finished)
        self.voice.speech_failed.connect(lambda m: self.chat.add_message("system", f"⚠ {m}"))

        if tray is _AUTO:
            tray = TrayController(self.windowIcon()) if tray_available() else None
        self.tray = tray
        if self.tray is not None:
            self.tray.open_requested.connect(self.show_and_raise)
            self.tray.exit_requested.connect(self.quit_app)
            self.tray.pause_toggled.connect(self.toggle_pause)
            self.tray.show()

        self._on_voice_state(VoiceState.OFF.value, "Microphone off")
        if self.settings.wake_enabled and autostart_voice:
            QTimer.singleShot(0, lambda: self.voice.set_wake_enabled(True))
        else:
            QTimer.singleShot(0, lambda: self._mark_ready("Zana is ready."))

    # -- window / tray ------------------------------------------------------
    def show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        """Exit completely (tray menu); closing the window may only hide it."""
        self._quitting = True
        self.close()

    def closeEvent(self, event) -> None:
        if self.settings.close_to_tray and self.tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify("Zana is still running",
                                 "Use the tray icon to open Zana or exit completely.")
            return
        self._quitting = True  # from here on nothing may restart the listener
        for w in (self._worker, self._app_worker):
            if w is not None and w.isRunning():
                if hasattr(w, "cancel"):
                    w.cancel()
                w.wait(5000)
        self.voice.shutdown()
        if self.tray is not None:
            self.tray.hide()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _mark_ready(self, detail: str) -> None:
        """Only report ready once the window and (if enabled) the microphone are up."""
        if self.ready:
            return
        self.ready = True
        if self.tray is not None and self.background_start:
            self.tray.notify("Zana is ready", detail)
        self.ready_reported.emit()

    def _set_tray_status(self, text: str) -> None:
        if self.tray is not None:
            self.tray.set_status(text)

    def _build_chat_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        head = QHBoxLayout()
        title = QLabel("Chat")
        title.setObjectName("pageTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.new_chat_button = QPushButton("New chat")
        self.new_chat_button.setCursor(Qt.PointingHandCursor)
        self.new_chat_button.clicked.connect(self._new_chat)
        head.addWidget(self.new_chat_button)
        layout.addLayout(head)
        self.chat = ChatPanel()
        layout.addWidget(self.chat, 1)
        self.chat.add_message("system", f"Local model: {CONFIG.ollama_model}")
        return page

    # -- chat ---------------------------------------------------------------
    def _is_busy(self) -> bool:
        return self._busy

    def _begin_busy(self) -> None:
        self._busy = True
        self.chat.set_busy(True)
        self.new_chat_button.setEnabled(False)
        self.home.visualizer.set_state(VisualizerState.THINKING)
        self.home.set_status("Thinking")

    def _end_busy(self) -> None:
        self._busy = False
        self.chat.set_busy(False)
        self.new_chat_button.setEnabled(True)

    def _new_chat(self) -> None:
        if self._is_busy():
            return
        self.assistant.new_conversation()
        self.chat.clear()
        self.chat.add_message("system", f"Local model: {CONFIG.ollama_model}")

    def _on_page_selected(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if self.stack.currentWidget() is self.memory_page:
            self.memory_page.refresh()

    def _on_message(self, text: str) -> None:
        if self._is_busy():
            return
        self._chat_failed = False
        self.chat.add_message("user", text)
        self._begin_busy()
        if self.app_commands.is_launch_intent(text):
            # A crash here is reported, never handed to the language model to improvise around.
            self._run_app_task(text, lambda: self.app_commands.handle_ex(text))
            return
        self._start_chat(text)

    def _run_app_task(self, text: str, fn, fallback_on_error: bool = False) -> None:
        self._app_worker = AppTaskWorker(fn, fallback_on_error, self)
        self._app_worker.resolved.connect(lambda res, t=text: self._on_app_resolved(t, res))
        self._app_worker.start()

    def _start_chat(self, text: str) -> None:
        self._stream_label = self.chat.add_message("assistant", "…")
        self._stream_text = ""
        spoken = self._from_voice and self.settings.speak_replies
        self._worker = ChatWorker(self.assistant, text, spoken, self)
        self._worker.token.connect(self._on_token)
        self._worker.failed.connect(self._on_chat_failed)
        self._worker.finished.connect(self._on_chat_finished)
        self._worker.start()

    # -- opening apps -------------------------------------------------------
    def _on_app_resolved(self, text: str, res) -> None:
        if res is None:  # not an app command: ordinary conversation
            self._start_chat(text)
            return
        if res.choose is not None:
            self._ask_close_target(text, res.choose)
            return
        if res.force is not None:
            self._ask_force(text, res.force)
            return
        reply = res.reply
        if res.pending is not None:
            # Installed but not approved. Never launch or add without the user's say-so.
            self.show_and_raise()
            if self.tray is not None:
                self.tray.notify("Approval needed", f"Zana wants to open {res.pending.name}.")
            if self.confirm_app(res.pending):
                try:
                    entry = self.app_registry.add_entry(res.pending)
                    self.app_registry.launch(entry.id)
                    self.apps_page.refresh()
                    reply = f"Opening {entry.name}."
                except AppError as e:
                    reply = f"I couldn't open {res.pending.name}. {e}"
            else:
                reply = f"Okay, I won't add {res.pending.name}."
        self._finish_local_reply(text, reply)

    # -- closing apps -------------------------------------------------------
    def _ask_close_target(self, text: str, outcome) -> None:
        """The app has several windows: ask which to close."""
        entry = outcome.entry
        self.show_and_raise()
        if self.tray is not None:
            self.tray.notify("Which window?", f"{entry.name} has {len(outcome.windows)} windows open.")
        hwnds = self.choose_windows(entry, outcome.windows)
        if not hwnds:
            self._finish_local_reply(text, f"Okay, I left {entry.name} open.")
            return
        self._run_app_task(text, lambda: self.app_commands.close_selected(entry.id, hwnds))

    def _ask_force(self, text: str, outcome) -> None:
        """Graceful close did not finish: only a confirmed force-close may continue."""
        entry = outcome.entry
        self.show_and_raise()
        if self.tray is not None:
            self.tray.notify("Force-close?", f"{entry.name} didn't close normally.")
        if self.confirm_force(entry, outcome):
            self._run_app_task(text, lambda: self.app_commands.force_close(entry.id))
        else:
            self._finish_local_reply(text, f"Okay, I left {entry.name} running.")

    def _ask_which_windows(self, entry, windows) -> list | None:
        everything = f"Close all {len(windows)} windows"
        items = [everything] + [f"{i}. {w.title[:70] or '(untitled)'}" for i, w in enumerate(windows, 1)]
        choice, ok = QInputDialog.getItem(
            self, f"Close {entry.name}", f"{entry.name} has {len(windows)} windows. Which should I close?",
            items, 0, False)
        if not ok:
            return None
        if choice == everything:
            return [w.hwnd for w in windows]
        return [windows[items.index(choice) - 1].hwnd]

    def _ask_force_close(self, entry, outcome) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(f"Force-close {entry.name}?")
        box.setText(outcome.message)
        box.setInformativeText("Anything you haven't saved in it will be lost.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("Force close")
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def _on_close_requested(self, name: str) -> None:
        """Close button on the Applications page: same path as saying "close <app>"."""
        if self._is_busy():
            return
        self.sidebar.select(1)
        self.stack.setCurrentIndex(1)
        self._on_message(f"close {name}")

    def _ask_app_approval(self, entry) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Approve application?")
        box.setText(f"Allow Zana to open {entry.name}?")
        box.setInformativeText(
            "It will be added to your approved apps (you can remove it on the Applications page) "
            "and started with no arguments.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def _finish_local_reply(self, text: str, reply: str) -> None:
        """Answer without the model (opening an app)."""
        self.chat.add_message("assistant", reply)
        self.assistant.record_exchange(text, reply)
        self._end_busy()
        if self._from_voice:
            self._from_voice = False
            if self.settings.speak_replies:
                self.voice.speak(reply)
            else:
                self.voice.resume()
        else:
            self._apply_visual_state(self.voice.engine.state)

    def _on_token(self, chunk: str) -> None:
        self._stream_text += chunk
        if self._stream_label is not None:
            self.chat.render_text(self._stream_label, self._stream_text)

    def _on_chat_failed(self, message: str) -> None:
        self._chat_failed = True
        if self._stream_label is not None and not self._stream_text:
            self._stream_label.hide()
        self.chat.add_message("system", f"⚠ {message}")

    def _on_chat_finished(self) -> None:
        reply = self._stream_text.strip()
        self._stream_label = None
        self._end_busy()
        if not self._from_voice:
            self._apply_visual_state(self.voice.engine.state)
            return
        self._from_voice = False
        if not self.settings.speak_replies:
            self.voice.resume()
        elif reply and not self._chat_failed:
            self.voice.speak(reply)
        else:
            self.voice.speak("Sorry, I couldn't get an answer from the local model.")

    def wait_for_chat(self, timeout_ms: int = 60000) -> bool:
        """Block until in-flight work finishes (used by tests)."""
        ok = True
        for w in (self._app_worker, self._worker):
            if w is not None:
                ok = w.wait(timeout_ms) and ok
        return ok

    # -- settings -----------------------------------------------------------
    def _save_settings(self) -> None:
        try:
            self.settings.save(self._settings_path)
        except OSError:
            pass  # settings are a convenience; never crash on a read-only disk

    def _on_wake_toggled(self, on: bool) -> None:
        self._startup_phase = False
        self._startup_retries_left = 0
        self._listening_established = False
        self.settings.wake_enabled = on
        self._save_settings()
        self.voice.set_wake_enabled(on)
        self._update_tray_pause()

    def _on_speak_toggled(self, on: bool) -> None:
        self.settings.speak_replies = on
        self._save_settings()

    def _on_startup_toggled(self, on: bool) -> None:
        try:
            (self.startup_api.enable if on else self.startup_api.disable)()
        except StartupError as e:
            self.settings_page.set_startup_checked(not on, f"⚠ {e}")
            return
        self.settings.launch_at_startup = on
        self._save_settings()
        self.settings_page.set_startup_checked(
            on, "Zana will start in the tray when you sign in to Windows." if on
            else "Zana will no longer start automatically.")

    def _on_tray_toggled(self, on: bool) -> None:
        self.settings.close_to_tray = on
        self._save_settings()
        msg = ""
        if on and self.tray is None:
            msg = "⚠ The system tray isn't available on this PC, so closing the window will still exit."
        self.settings_page.background_message.setText(msg)

    # -- voice --------------------------------------------------------------
    def _on_mic_toggled(self, on: bool) -> None:
        """Mic button = push-to-talk: capture one command without the wake phrase."""
        if on:
            self.voice.push_to_talk()
        else:
            self.voice.cancel_command()

    def _on_voice_command(self, text: str) -> None:
        if self._is_busy():
            self.voice.resume()
            return
        self._from_voice = True
        self._on_message(text)

    def _on_speech_finished(self) -> None:
        self.voice.resume()

    def _on_voice_level(self, level: float) -> None:
        if not self.home.visualizer.simulate_levels:
            self.home.visualizer.set_level(min(1.0, level * 25))

    def _retry_voice(self) -> None:
        """Reopen the microphone after a temporary failure (never while paused or switched off)."""
        if (self.settings.wake_enabled and not self.voice.user_paused and not self._quitting
                and not self.voice.engine.running):
            self.voice.set_wake_enabled(True)

    def _on_voice_state(self, state_value: str, detail: str) -> None:
        state = VoiceState(state_value)
        if state is VoiceState.ERROR and self._startup_retries_left > 0 and not self.voice.user_paused:
            # At sign-in the audio service may not be ready, or a device was unplugged
            # mid-session: retry quietly instead of giving up.
            self._startup_retries_left -= 1
            self.sidebar.status_pill.set_state(VoiceState.STARTING, detail)
            self.settings_page.set_status(VoiceState.STARTING, f"Waiting for the microphone... {detail}")
            self._set_tray_status("Waiting for the microphone…")
            self._apply_visual_state(VoiceState.STARTING, "Waiting for the microphone")
            QTimer.singleShot(self._retry_delay_ms, self._retry_voice)
            return
        self.sidebar.status_pill.set_state(state, detail)
        self.settings_page.set_status(state, detail)
        self._set_tray_status(self.sidebar.status_pill.text())
        if state is VoiceState.WAITING:
            self._startup_phase = False
            self._listening_established = True
            # From now on a lost microphone is recovered with longer, patient retries.
            self._startup_retries_left = self._runtime_retries
            self._retry_delay_ms = self._runtime_retry_ms
            self._mark_ready('Say "Hey Zana".')
        elif state is VoiceState.ERROR:
            self.settings_page.set_wake_checked(False)
            if self._startup_phase or self._listening_established:
                # It worked before / couldn't start at launch: keep the user's choice so the
                # next launch (or a manual re-enable) tries again.
                if self.tray is not None:
                    self.tray.notify("Microphone unavailable", detail)
            else:
                self.settings.wake_enabled = False  # the user just switched it on and it failed
                self._save_settings()
            self._startup_phase = False
            self._mark_ready("Zana is running without the microphone.")
        self._update_tray_pause()
        self._apply_visual_state(state, detail)

    # -- pause / hands-free helpers -------------------------------------------
    def _update_tray_pause(self) -> None:
        if self.tray is not None:
            self.tray.set_pause_state(self.settings.wake_enabled, self.voice.user_paused)

    def toggle_pause(self) -> None:
        """Tray: pause the listener (microphone closed) or resume it."""
        if not self.settings.wake_enabled:
            return
        if self.voice.user_paused:
            self.voice.resume_listening()
        else:
            self.voice.pause_listening()
        self._update_tray_pause()

    def _on_follow_up_changed(self, seconds: int) -> None:
        self.settings.follow_up_seconds = seconds
        self._save_settings()
        self.voice.set_follow_up_seconds(seconds)

    def enable_hands_free(self) -> None:
        """One click: listen for the wake phrase, start with Windows, stay in the tray."""
        page = self.settings_page
        for box in (page.wake_check, page.startup_check, page.tray_check):
            if not box.isChecked():
                box.setChecked(True)  # fires the normal handlers (and shows any error)
        self.settings.onboarding_done = True
        self._save_settings()

    def _ask_hands_free(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Make Zana hands-free?")
        box.setText("Turn on fully hands-free mode?")
        box.setInformativeText(
            "Zana will listen for “Hey Zana” in the background (your microphone stays on while "
            "Zana runs; audio is never saved or sent anywhere), start automatically when you sign in "
            "to Windows, and keep running in the system tray when you close the window.\n\n"
            "You can change any of this later in Settings.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.No).setText("Not now")
        return box.exec() == QMessageBox.Yes

    def maybe_offer_hands_free(self) -> None:
        """Ask once (first launch) so hands-free needs a single click, then never nag."""
        s = self.settings
        if s.onboarding_done:
            return
        if s.wake_enabled and s.launch_at_startup and s.close_to_tray:
            s.onboarding_done = True
            self._save_settings()
            return
        if self.confirm_hands_free():
            self.enable_hands_free()
        else:
            s.onboarding_done = True
            self._save_settings()

    def _apply_visual_state(self, state: VoiceState, detail: str = "") -> None:
        listening = state is VoiceState.LISTENING
        for btn in (self.home.mic, self.chat.mic):
            btn.blockSignals(True)
            btn.setChecked(listening)
            btn.blockSignals(False)
            btn.update()
        viz = self.home.visualizer
        viz.simulate_levels = state not in (VoiceState.WAITING, VoiceState.LISTENING)
        viz.set_state({
            VoiceState.LISTENING: VisualizerState.LISTENING,
            VoiceState.TRANSCRIBING: VisualizerState.THINKING,
            VoiceState.BUSY: VisualizerState.THINKING,
            VoiceState.SPEAKING: VisualizerState.SPEAKING,
            VoiceState.PAUSED: VisualizerState.PAUSED,
        }.get(state, VisualizerState.IDLE))
        if self._is_busy():
            viz.set_state(VisualizerState.THINKING)
        text = detail or state.value
        self.home.set_status(
            "Microphone error — see Settings" if state is VoiceState.ERROR else text)
        level, mic_text = {
            VoiceState.WAITING: ("ok", "Listening"), VoiceState.LISTENING: ("ok", "Hearing you"),
            VoiceState.TRANSCRIBING: ("ok", "Processing"), VoiceState.BUSY: ("ok", "Processing"),
            VoiceState.SPEAKING: ("ok", "Speaking"), VoiceState.PAUSED: ("warn", "Paused"),
            VoiceState.STARTING: ("warn", "Starting"), VoiceState.ERROR: ("error", "Problem"),
        }.get(state, ("off", "Off"))
        self.home.set_mic_indicator(level, "Microphone " + mic_text.lower())
        self.home.system_status.set_item("microphone", level, mic_text)

    def _on_suggestion(self, command: str) -> None:
        """A suggestion card on Home: run it exactly as if typed in Chat."""
        if self._is_busy():
            return
        self.sidebar.select(1)
        self._on_page_selected(1)
        self._on_message(command)
