"""Emerald redesign: palette, orb states, toggles, chat formatting, home screen, status checks."""

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor

from tests.fake_tray import FakeTray
from tests.fakes import wait_until
from tests.test_gui_smoke import app, build  # noqa: F401 (fixture import)
from zana.core.ollama_client import OllamaError
from zana.settings import UserSettings
from zana.ui import icons, theme
from zana.ui.chat_panel import ChatPanel, format_reply
from zana.ui.fade_stack import FadeStack
from zana.ui.status_pill import StatusPill
from zana.ui.system_status import StatusPoller, SystemStatus, probe_system
from zana.ui.toggle import ToggleSwitch
from zana.ui.visualizer import VisualizerState, VoiceVisualizer
from zana.voice.engine import VoiceState


# -- palette -----------------------------------------------------------------------
def test_palette_matches_the_spec():
    assert (theme.BG, theme.BG2, theme.CARD) == ("#050807", "#0B100E", "#101714")
    assert (theme.GREEN, theme.GLOW, theme.MINT) == ("#00F5A0", "#00FF88", "#B9FFD9")
    assert (theme.TEXT, theme.MUTED, theme.BORDER, theme.HOVER) == ("#F4FFF8", "#83968B", "#20382D", "#153B2B")


def test_no_old_blue_purple_colours_remain():
    old = re.compile(r"#(4da3ff|9b6bff|06070d|0b0d1a|11142a|222753|e8eaff|8a90bd|6a46d6|2a5fd8)", re.I)
    root = Path(__file__).resolve().parent.parent / "zana" / "ui"
    offenders = [f"{p.name}: {m.group(0)}" for p in root.rglob("*.py")
                 for m in old.finditer(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_stylesheet_uses_the_emerald_tokens():
    for token in (theme.GREEN, theme.BORDER, theme.HOVER, theme.CARD, theme.BG2):
        assert token in theme.STYLESHEET
    assert theme.rgba("#00F5A0", 0.5) == "rgba(0,245,160,127)"


def test_icons_render_for_every_navigation_item(app):
    for name in ("home", "chat", "apps", "memory", "settings", "mic"):
        px = icons.pixmap(name, theme.GREEN)
        assert not px.isNull()
        img = px.toImage()
        assert any(img.pixelColor(x, y).alpha() > 0 for x in range(0, img.width(), 3) for y in range(0, img.height(), 3))


# -- orb ------------------------------------------------------------------------------
def test_orb_renders_every_state_and_pause_is_dimmer(app):
    viz = VoiceVisualizer()
    viz.resize(420, 420)
    viz.show()
    levels = {}
    for state in VisualizerState:
        viz.set_state(state)
        for _ in range(40):          # let the smoothed look settle
            viz._last_ms -= 33
            viz._tick()
        assert not viz.grab().isNull()
        levels[state] = (viz._bright, viz._speed)
    assert levels[VisualizerState.PAUSED][0] < levels[VisualizerState.IDLE][0] < levels[VisualizerState.LISTENING][0]
    assert levels[VisualizerState.THINKING][1] > 2 * levels[VisualizerState.IDLE][1]   # faster rings
    assert levels[VisualizerState.PAUSED][1] < levels[VisualizerState.IDLE][1]
    viz.hide()


def test_orb_follows_real_audio_level_when_not_simulating(app):
    viz = VoiceVisualizer()
    viz.show()
    viz.simulate_levels = False
    viz.set_state(VisualizerState.SPEAKING)
    viz.set_level(0.9)
    for _ in range(30):
        viz._last_ms -= 33
        viz._tick()
    assert viz._level > 0.7
    viz.set_level(0.0)
    for _ in range(40):
        viz._last_ms -= 33
        viz._tick()
    assert viz._level < 0.1
    viz.hide()


def test_orb_animation_only_runs_while_visible(app):
    viz = VoiceVisualizer()
    viz.show()
    assert viz._timer.isActive()
    viz.hide()
    assert not viz._timer.isActive()
    viz.show()
    assert viz._timer.isActive()
    viz.hide()


# -- toggle switch -------------------------------------------------------------------
def test_toggle_switch_is_a_drop_in_checkbox(app):
    t = ToggleSwitch("Listen")
    t.show()
    seen = []
    t.toggled.connect(seen.append)
    assert not t.isChecked()
    t.click()
    assert t.isChecked() and seen == [True]
    t.blockSignals(True)
    t.setChecked(False)           # programmatic change with signals blocked still updates the knob
    t.blockSignals(False)
    assert not t.isChecked() and seen == [True]
    assert wait_until(lambda: t._anim.state() != t._anim.State.Running, app=app)
    t.setChecked(True)
    assert t._knob in (0.0, 1.0) or t._anim.state() == t._anim.State.Running
    assert not t.grab().isNull()
    t.close()


def test_settings_page_uses_toggle_switches_and_banner(app, tmp_path):
    w = build(app, tmp_path, tray=FakeTray())
    try:
        page = w.settings_page
        for name in ("wake_check", "speak_check", "startup_check", "tray_check"):
            assert isinstance(getattr(page, name), ToggleSwitch)
        page.set_status(VoiceState.WAITING, "")
        assert "Hey Zana" in page.listen_pill.text()
        assert page.status_label.isHidden()            # nothing wrong, so no extra status line
        page.set_status(VoiceState.ERROR, "no microphone")
        assert page.listen_pill.state is VoiceState.ERROR
        assert not page.status_label.isHidden() and "no microphone" in page.status_label.text()
        page.set_status(VoiceState.PAUSED, "")
        assert page.listen_pill.text() == "Paused"
    finally:
        w.quit_app()


# -- chat -----------------------------------------------------------------------------
def test_reply_formatting_highlights_but_never_injects_html():
    out = format_reply("Use **bold** and `calc`\nnext <b>line</b> & <script>x</script>")
    assert theme.MINT in out and theme.GREEN in out and "<br>" in out
    assert "<script>" not in out and "&lt;script&gt;" in out and "&amp;" in out
    assert format_reply("**unfinished") == "**unfinished"   # partial streaming text is left alone


def test_chat_bubbles_have_roles_and_fade_in(app):
    panel = ChatPanel()
    panel.resize(700, 500)
    panel.show()
    user = panel.add_message("user", "hello <b>")
    bot = panel.add_message("assistant", "Sure, **done**")
    note = panel.add_message("system", "note")
    assert (user.objectName(), bot.objectName(), note.objectName()) == (
        "bubbleUser", "bubbleAssistant", "bubbleSystem")
    assert user.text() == "hello <b>"                      # user text is shown literally
    assert "done" in bot.text() and "<b" in bot.text()    # assistant text gets emerald highlights
    assert user.graphicsEffect() is not None               # fading in...
    assert wait_until(lambda: user.graphicsEffect() is None and bot.graphicsEffect() is None, app=app)
    assert panel.message_count() == 3
    panel.close()


def test_streaming_updates_render_formatted_text(app, tmp_path):
    w = build(app, tmp_path)
    try:
        label = w.chat.add_message("assistant", "…")
        w._stream_label, w._stream_text = label, ""
        w._on_token("Hello **wor")
        w._on_token("ld**")
        assert theme.MINT in label.text() and "world" in label.text()
    finally:
        w.quit_app()


# -- screens ----------------------------------------------------------------------------
def test_page_switch_is_instant_logically_and_fades_visually(app):
    from PySide6.QtWidgets import QLabel
    stack = FadeStack()
    for i in range(3):
        stack.addWidget(QLabel(str(i)))
    stack.show()
    stack.setCurrentIndex(2)
    assert stack.currentIndex() == 2
    assert stack.currentWidget().graphicsEffect() is not None
    assert wait_until(lambda: stack.currentWidget().graphicsEffect() is None, app=app)
    stack.setCurrentIndex(2)                                # same page: nothing to animate
    assert stack.currentWidget().graphicsEffect() is None
    stack.close()


def test_home_has_greeting_status_mic_suggestions_and_system_status(app, tmp_path):
    w = build(app, tmp_path, tray=FakeTray())
    try:
        home = w.home
        assert home.greeting.text() == "What can I do for you today?"
        assert len(home.suggestion_buttons) == 3 and home.mic is not None
        assert set(home.system_status._chips) == {"ollama", "microphone", "whisper", "piper"}
        w._apply_visual_state(VoiceState.PAUSED)
        assert home.visualizer.state is VisualizerState.PAUSED
        assert home.system_status.item_text("microphone") == "Paused"
        w._apply_visual_state(VoiceState.WAITING, 'Listening for "Hey Zana"')
        assert home.status.text() == 'Listening for "Hey Zana"'
        assert "listening" in home._ind_text.text().lower()
        assert home.system_status.item_text("microphone") == "Listening"
    finally:
        w.quit_app()


def test_clicking_a_suggestion_runs_it_like_typed_chat(app, tmp_path):
    w = build(app, tmp_path)
    try:
        w.home.suggestion_buttons[1].click()           # "Ask anything"
        assert wait_until(lambda: not w._busy, app=app)
        assert w.fake.prompts == ["tell me a fun fact"]
        assert w.stack.currentIndex() == 1             # taken to the Chat screen
        msgs = w.assistant.store.get_messages(w.assistant.conversation_id)
        assert [m["content"] for m in msgs] == ["tell me a fun fact", "Hi friend"]
    finally:
        w.quit_app()


def test_pausing_dims_the_orb_and_shows_paused_everywhere(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, tray=tray, settings=UserSettings(wake_enabled=True, follow_up_seconds=0))
    try:
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        tray.pause_toggled.emit()
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.PAUSED, app=app)
        assert w.home.visualizer.state is VisualizerState.PAUSED
        assert w.home.system_status.item_text("microphone") == "Paused"
        assert w.sidebar.status_pill.text() == "Paused"
    finally:
        w.quit_app()


# -- system status ------------------------------------------------------------------------
class _Client:
    def __init__(self, models=None, error=None, model="qwen3.5:4b"):
        self.model, self._models, self._error = model, models or [], error

    def list_models(self):
        if self._error:
            raise self._error
        return self._models


def test_probe_reports_real_state(tmp_path):
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "model.bin").write_bytes(b"x")
    voice = tmp_path / "v.onnx"
    voice.write_bytes(b"x")
    ok = probe_system(_Client(["qwen3.5:4b"]), tmp_path / "w", voice)
    assert ok == {"ollama": ("ok", "Ready"), "whisper": ("ok", "Ready"), "piper": ("ok", "Ready")}
    bad = probe_system(_Client([], OllamaError("down")), tmp_path / "nope", tmp_path / "none.onnx")
    assert bad["ollama"] == ("error", "Not running")
    assert bad["whisper"] == ("error", "Model missing") and bad["piper"] == ("error", "Voice missing")
    assert probe_system(_Client(["other:1"]), tmp_path / "w", voice)["ollama"][0] == "warn"


def test_status_panel_updates_from_a_background_probe(app, tmp_path):
    panel = SystemStatus()
    poller = StatusPoller(lambda: {"ollama": ("ok", "Ready"), "piper": ("error", "Voice missing")})
    poller.result.connect(panel.update_from)
    poller.refresh()
    assert wait_until(lambda: panel.item_text("ollama") == "Ready", app=app)
    assert panel.item_text("piper") == "Voice missing"
    broken = StatusPoller(lambda: 1 / 0)       # a crashing probe must not break the UI
    broken.result.connect(panel.update_from)
    broken.refresh()
    assert wait_until(lambda: not broken._busy, app=app)


def test_window_polls_system_status_when_a_probe_is_given(app, tmp_path):
    w = build(app, tmp_path, status_probe=lambda: {"ollama": ("warn", "Model not pulled"),
                                                    "whisper": ("ok", "Ready"), "piper": ("ok", "Ready")})
    try:
        assert wait_until(lambda: w.home.system_status.item_text("ollama") == "Model not pulled", app=app)
    finally:
        w.quit_app()


def test_status_pill_colours_and_texts(app):
    pill = StatusPill()
    for state, word in ((VoiceState.WAITING, "Listening"), (VoiceState.TRANSCRIBING, "Processing"),
                        (VoiceState.SPEAKING, "Speaking"), (VoiceState.PAUSED, "Paused")):
        pill.set_state(state)
        assert word in pill.text()
    pill.set_state(VoiceState.ERROR)
    assert QColor(pill._dot.color).name().lower() == theme.DANGER.lower()
    pill.set_state(VoiceState.WAITING)
    assert QColor(pill._dot.color).name().lower() == theme.GREEN.lower()
