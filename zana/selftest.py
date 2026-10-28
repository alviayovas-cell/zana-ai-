"""Headless self-check of the voice stack, used to verify packaged builds.

Run as ``Zana.exe --selftest <output.json>``. A windowed exe has no console, so
the result is written to a file.
"""

import json
import traceback

from .config import CONFIG


def run() -> dict:
    report: dict = {"models_dir": str(CONFIG.models_dir), "data_dir": str(CONFIG.data_dir)}

    def step(name, fn):
        try:
            report[name] = {"ok": True, "detail": fn()}
        except Exception as e:  # report every failure, don't stop at the first
            report[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}",
                            "trace": traceback.format_exc(limit=4)}

    def mic():
        import sounddevice as sd
        dev = sd.query_devices(None, "input")
        return str(dev["name"])

    state: dict = {}

    def tts():
        import numpy as np
        from piper import PiperVoice
        voice = PiperVoice.load(str(CONFIG.piper_model_path))
        chunks = list(voice.synthesize("Hey Zana, open Notepad."))
        audio = np.concatenate([c.audio_float_array for c in chunks])
        n = int(len(audio) * 16000 / chunks[0].sample_rate)
        state["audio"] = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
                                   ).astype("float32") * 0.05
        return f"{len(audio) / chunks[0].sample_rate:.1f}s of speech synthesised"

    def stt():
        from .voice.stt import WhisperTranscriber
        from .voice.wake import match_wake_phrase
        text = WhisperTranscriber(CONFIG.whisper_dir).transcribe(state["audio"], check_wake=True)
        rem = match_wake_phrase(text)
        if rem is None:
            raise RuntimeError(f"wake phrase not recognised in {text!r}")
        state["command"] = rem
        return f"heard {text!r}; command={rem!r}"

    def ollama():
        from .core.ollama_client import OllamaClient
        c = OllamaClient(CONFIG.ollama_url, CONFIG.ollama_model, timeout=5)
        if not c.is_available():
            raise RuntimeError(f"model {CONFIG.ollama_model} not available at {CONFIG.ollama_url}")
        return f"{CONFIG.ollama_model} available"

    def apps():
        from .apps.registry import AppRegistry
        return [a.name for a in AppRegistry(CONFIG.apps_path).list()]

    def open_close():
        """Spoken command -> allowlist -> real launch of Notepad -> graceful close of THAT window only."""
        import time
        from .apps.closer import AppCloser
        from .apps.registry import AppCommandHandler, AppRegistry
        registry = AppRegistry(CONFIG.apps_path)
        entry = registry.find("notepad")
        if entry is None:
            return "Notepad is not in the approved list; skipped"
        cmd = state.get("command", "open notepad")
        closer = AppCloser()
        handler = AppCommandHandler(registry, finder=None, closer=closer)
        if not handler.is_launch_intent(cmd):
            raise RuntimeError(f"command {cmd!r} was not recognised as an app command")
        before = {w.hwnd for w in closer.instances(entry).windows}
        res = handler.handle_ex(cmd)
        if res is None or not res.reply.startswith("Opening"):
            raise RuntimeError(f"open failed: {res.reply if res else None}")
        new = []
        for _ in range(40):                      # up to ~10 s for the window to appear
            time.sleep(0.25)
            new = [w for w in closer.instances(entry).windows if w.hwnd not in before]
            if new:
                break
        if not new:
            raise RuntimeError("Notepad was launched but its window never appeared")
        outcome = closer.close(entry, hwnds=[w.hwnd for w in new])   # only the window we opened
        if outcome.status != "closed":
            raise RuntimeError(f"close returned {outcome.status}: {outcome.message}")
        return f"{res.reply} then {outcome.message!r} (windows opened by the test: {len(new)})"

    def process_api():
        from .apps.processes import WinProcessApi
        api = WinProcessApi()
        procs, wins = api.list_processes(), api.list_windows()
        if len(procs) < 10:
            raise RuntimeError("process list looks empty")
        return f"{len(procs)} processes, {len(wins)} visible windows"

    step("microphone", mic)
    step("piper_tts", tts)
    if report["piper_tts"]["ok"]:
        step("whisper_stt_and_wake_phrase", stt)
    step("ollama", ollama)
    step("approved_apps", apps)
    step("process_api", process_api)
    if report.get("whisper_stt_and_wake_phrase", {}).get("ok"):
        step("voice_command_open_then_close_notepad", open_close)
    report["all_ok"] = all(v["ok"] for v in report.values() if isinstance(v, dict) and "ok" in v)
    return report


def main(out_path: str) -> int:
    report = run()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return 0 if report["all_ok"] else 1


def render(out_dir: str) -> int:
    """Render the real windows to PNGs and check the emerald palette is what is on screen."""
    import tempfile
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from .ui import theme
    from .ui.main_window import MainWindow

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    w = MainWindow(autostart_voice=False, tray=None)
    w.resize(1180, 760)
    w.show()
    report: dict = {"pages": {}}

    def pump(sec: float) -> None:
        import time
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    def is_blue(c) -> bool:
        return c.blue() > 150 and c.green() < c.blue() * 0.75

    def stats(img) -> dict:
        emerald = bluish = 0
        for y in range(0, img.height(), 3):
            for x in range(0, img.width(), 3):
                c = img.pixelColor(x, y)
                if c.green() > 190 and c.red() < 90 and 60 < c.blue() < 190:
                    emerald += 1
                # A blue/purple UI element (the old theme) is a solid area. ClearType fringes on
                # text are isolated pixels, so only count a pixel whose neighbours are blue too.
                if is_blue(c) and all(
                        is_blue(img.pixelColor(min(max(x + dx, 0), img.width() - 1),
                                               min(max(y + dy, 0), img.height() - 1)))
                        for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2))):
                    bluish += 1
        side = img.pixelColor(60, img.height() - 120)   # empty part of the sidebar
        return {"emerald_pixels": emerald, "blue_or_purple_pixels": bluish,
                "sidebar_rgb": [side.red(), side.green(), side.blue()]}

    for i, name in enumerate(("home", "chat", "applications", "memory", "settings")):
        w.sidebar.select(i)
        w._on_page_selected(i)
        pump(0.7)
        img = w.grab().toImage()
        img.save(str(out / f"{name}.png"))
        report["pages"][name] = stats(img)
    w.quit_app()
    pages = report["pages"]
    report["all_ok"] = (
        all(p["blue_or_purple_pixels"] == 0 for p in pages.values())
        and sum(p["emerald_pixels"] for p in pages.values()) > 500
        and pages["home"]["emerald_pixels"] > 30
        and all(max(p["sidebar_rgb"]) < 30 and p["sidebar_rgb"][1] >= p["sidebar_rgb"][0]
                for p in pages.values())
    )
    (out / "render.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["all_ok"] else 1
