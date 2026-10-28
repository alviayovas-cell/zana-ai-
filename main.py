"""Zana entry point.

Flags: ``--background`` start hidden in the system tray (used by the Windows
startup entry); ``--selftest <file>`` headless check of the voice stack.
"""

import logging
import logging.handlers
import sys
import traceback


def _setup_logging() -> None:
    from zana.config import CONFIG

    try:
        CONFIG.log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            CONFIG.log_path, maxBytes=512_000, backupCount=2, encoding="utf-8")
    except OSError:
        return  # logging is best-effort
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    def hook(exc_type, exc, tb):
        logging.getLogger("zana").error("Uncaught exception:\n%s",
                                        "".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        from zana import selftest
        return selftest.main(sys.argv[2])
    if len(sys.argv) >= 3 and sys.argv[1] == "--render-test":
        from zana import selftest
        return selftest.render(sys.argv[2])
    background = "--background" in sys.argv[1:]

    _setup_logging()
    log = logging.getLogger("zana")
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from zana import startup
    from zana.config import CONFIG, resource_path
    from zana.single_instance import SingleInstance
    from zana.ui.main_window import MainWindow
    from zana.ui.theme import STYLESHEET

    app = QApplication(sys.argv)
    app.setApplicationName(CONFIG.app_name)
    app.setQuitOnLastWindowClosed(False)  # the tray keeps Zana alive when the window is hidden
    app.setStyleSheet(STYLESHEET)
    icon = resource_path("assets/zana.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    instance = SingleInstance()
    if not instance.acquire():
        log.info("Zana is already running; asked it to show its window.")
        return 0

    log.info("Starting Zana (background=%s); models at %s", background, CONFIG.models_dir)
    from zana.core.ollama_client import OllamaClient
    from zana.ui.system_status import probe_system

    def status_probe() -> dict:  # short timeout so a stopped Ollama never stalls the check
        return probe_system(OllamaClient(CONFIG.ollama_url, CONFIG.ollama_model, timeout=3),
                            CONFIG.whisper_dir, CONFIG.piper_model_path)

    window = MainWindow(status_probe=status_probe)
    window.background_start = background
    def on_activate() -> None:
        log.info("Another launch asked Zana to show its window.")
        window.show_and_raise()
        log.info("Window visible=%s minimized=%s", window.isVisible(), window.isMinimized())

    instance.activated.connect(on_activate)

    if window.settings.launch_at_startup:  # keep the Run entry pointing at this exe
        try:
            startup.sync(True)
        except startup.StartupError as e:
            log.warning("Could not refresh startup entry: %s", e)

    if background and window.tray is not None:
        pass  # stay hidden in the tray until opened
    elif background:
        window.showMinimized()  # no tray available: don't take over the screen
    else:
        window.show()
        # One-time offer to turn on hands-free mode; never shown for silent startup launches.
        QTimer.singleShot(1200, window.maybe_offer_hands_free)
    code = app.exec()
    instance.release()
    return code


if __name__ == "__main__":
    sys.exit(main())
