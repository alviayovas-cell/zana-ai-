# Zana

A local, privacy-first voice assistant for Windows 11 with a JARVIS-style interface.
Everything runs on your PC: chat uses Ollama, speech uses Faster-Whisper and Piper,
history is stored in SQLite. No API keys, no cloud services.

**Stack:** Python 3.12, PySide6, Ollama (`qwen3.5:4b`), Faster-Whisper (`base.en`), Piper TTS, SQLite.

**Look:** near-black with emerald accents (palette tokens in `zana/ui/theme.py`). The Home screen is an
animated orb (thin emerald rings orbiting a dark sphere) that changes with state: slow when idle,
brighter and pulsing when listening, faster rings while processing, rings that follow your voice
level while speaking, dimmed when paused. The animation pauses when the window is hidden. Home also
shows live Ollama / microphone / Whisper / Piper status and clickable example commands.

## Features

| Feature | Notes |
|---|---|
| Desktop GUI (Home, Chat, Applications, Memory, Settings) | Native Qt app, not a website |
| Streaming chat with the local Ollama model | |
| Local conversation history + Memory page | SQLite in `%LOCALAPPDATA%\Zana` |
| Push-to-talk (mic button) and spoken replies | |
| Hands-free "Hey Zana" | Opt-in; runs in the background, also while minimized/in the tray |
| Open and close apps by voice or text | Strict allowlist; you approve each new app; safe polite-first closing |
| Launch at Windows startup | Opt-in, per user |
| System tray (Open / Exit) | Opt-in "keep running when I close the window" |
| Single instance | A second launch just shows the running Zana |

## Setup (from source)

1. Install [Ollama](https://ollama.com) and `ollama pull qwen3.5:4b`.
2. Python 3.12, then in the project folder:
   ```
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Download the voice models into `models\` (about 200 MB):
   ```
   .venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir models\piper
   .venv\Scripts\python.exe -c "from faster_whisper.utils import download_model; download_model('base.en', output_dir=r'models\whisper\base.en')"
   ```
4. Run: `.venv\Scripts\python.exe main.py`

## Using it

**Fully hands-free, one time:** the first time you open Zana it offers to turn on hands-free mode.
Or open **Settings** and click **Turn on everything for fully hands-free use**. That switches on:
listening for "Hey Zana", starting with Windows, and staying in the tray when you close the window.
All three are saved and respected on every restart; you never have to enable them again.

**Talking to it:** say "Hey Zana, what is the capital of France?" in one breath, or "Hey Zana",
wait for the chime, then speak. After Zana answers it keeps the conversation open for a few seconds
(Settings > *Keep the conversation open after a reply*, default 8 s, 0 = off): you can just keep
talking without repeating "Hey Zana". Say "thanks" or "stop" to end it, or stay quiet and it
returns to waiting for the wake phrase. The microphone is muted while Zana processes and speaks,
plus a short guard afterwards, so it does not answer its own voice.

**Status** (sidebar indicator and tray tooltip): *Listening for "Hey Zana"*, *Listening to you*,
*Processing*, *Speaking*, *Paused*, or a microphone problem. **Tray menu:** Open Zana,
Pause/Resume listening (closes the microphone while paused), Exit Zana. If the microphone
disappears while running (unplugged, driver reset), Zana reconnects automatically and keeps
retrying for several minutes before reporting a problem; your saved preference is kept.

**Open apps:** "Hey Zana, open Notepad" / type "open calculator". Only apps on the
**Applications** page can be opened. If you ask for an installed app that isn't approved yet
(e.g. "open WhatsApp"), Zana finds it in the Start menu and shows a dialog asking you to
approve it; nothing is added or launched unless you click Yes. You can also use
*Find installed app...* or *Add .exe...* on the Applications page, and remove added apps there.
Command shells and script hosts (PowerShell, cmd, Terminal, wscript, ...) can never be added.
Natural phrasing works for voice and typed chat: "Can you close Spotify?", "Please launch Chrome",
"open vs code", "quit chrome". A unique partial name is enough ("chrome" finds "Google Chrome").

**Close apps:** "Hey Zana, close Spotify" (also quit / exit / shut down; the Applications page has a
**Close** button too). Only *approved* apps can be closed, and Zana first identifies exactly which
running processes belong to that app (by exe path, Store package, or the exe behind its Start-menu
shortcut) before touching anything.
- It closes politely first (the same as clicking the window's X). If the app has several windows
  you are asked which one to close (or all).
- If the app doesn't close (it is asking you to save, hung, or it keeps running in the tray, as
  Spotify/WhatsApp/Claude do), Zana tells you and **asks before force-closing**; force-closing can
  lose unsaved work. Declining leaves everything running.
- Never force-closed, whatever you say: Windows system/shell processes and anything inside the
  Windows folder, security software (Defender and common antivirus), Zana itself and the process
  that started it, processes Windows won't let it inspect (elevated), and File Explorer / Task
  Manager / Windows Settings (those can only be closed politely). "Close File Explorer" closes the
  folder windows, never the desktop shell.
- Limits: apps running with administrator rights can't be closed; apps that hide to the tray keep
  running after their window closes (Zana offers the force-quit); matching Store apps relies on
  their package, and plain-name apps (Chrome, VS Code) on their Start-menu shortcut.

**Start with Windows (off until you turn it on, once):**
1. Open Zana > **Settings** > click **Turn on everything for fully hands-free use** (or switch on
   **Launch Zana at Windows startup** and **Keep running in the system tray** yourself).
2. Sign out and back in (or restart).
3.  Zana starts hidden in the tray; if *Listen for "Hey Zana"* is on, it
   starts listening and shows a "Zana is ready" notification once the microphone is up.
4. To undo: switch the setting off, or Task Manager > Startup apps > Zana > Disable.

It uses your per-user `Run` registry entry only: no administrator rights, nothing machine-wide,
and it starts *after* you sign in (it cannot and does not bypass the Windows sign-in screen).

**Tray:** click the icon (or right-click > Open Zana) to show the window; right-click > Exit
Zana to quit completely.

## Limits and honest notes

- "Hey Zana" is found by transcribing short speech with Whisper, not a dedicated wake-word model
  (openWakeWord has no "Hey Zana"). The bare phrase alone was recognised ~82% of the time on
  synthetic speech; "Hey Zana, <command>" in one breath is more reliable. English only.
- The listener keeps the microphone open while enabled; Windows shows its microphone-in-use
  indicator. Audio is processed in memory and never saved or sent anywhere.
- At sign-in the audio service may not be ready; Zana retries the microphone for ~25 seconds
  and then reports the problem (it keeps your setting and tries again next launch).
- Store apps (WhatsApp, Spotify, ...) can be approved and launched. Classic desktop apps that
  Windows lists only by a short name (e.g. Chrome) can't be found automatically: add their `.exe`.
- Replies are spoken after the full reply arrives (voice replies are kept to ~2 sentences).
- The Run-key startup entry and tray icon were tested with a throwaway registry key and fake
  tray in automated tests; a real sign-out/sign-in cycle has to be tried by you.

## Packaged app

`tools\build_exe.ps1` builds a one-folder app to `dist\Zana\Zana.exe` (PyInstaller).
AI models are **not** bundled. The app looks for `models\` (containing `piper\` and `whisper\`)
in this order: `ZANA_MODELS_DIR`, next to `Zana.exe`, `%LOCALAPPDATA%\Zana\models`, and
`<project>\models` (when the build sits in `<project>\dist\Zana`). Ollama must be installed and running.
Settings, history, approved apps and logs live in `%LOCALAPPDATA%\Zana` (logs in `logs\zana.log`).

## Configuration

Environment variables: `ZANA_MODEL` (default `qwen3.5:4b`), `ZANA_OLLAMA_URL`
(default `http://localhost:11434`), `ZANA_MODELS_DIR`.

## Tests

```
.venv\Scripts\python.exe -m pytest
```

Unit and GUI tests use fake audio, fake launcher and a throwaway registry key, and run
headless; no test opens a real program. `tests/test_voice_real_models.py` uses the real models
(skipped if absent) with Piper-synthesised speech.
`Zana.exe --selftest out.json` checks mic, Piper, Whisper, Ollama and the app list, then speaks
"Hey Zana, open Notepad" through Whisper, really opens Notepad and closes only the window it opened.
`Zana.exe --render-test <folder>` renders every screen from the packaged build and checks the emerald palette.
The current build lives in `dist_next\Zana` (the Desktop shortcut points there); the previous build is
untouched in `dist\Zana`. `tools\create_shortcut.ps1 -Force [-Folder dist]` repoints the shortcut.

## Layout

```
main.py            entry point (--background, --selftest)
zana/ui/           PySide6 interface, tray, voice bridge
zana/core/         Ollama client, chat orchestration
zana/voice/        mic, segmentation, Whisper STT, wake phrase, Piper TTS, engine
zana/apps/         allowlist registry, installed-app discovery
zana/startup.py    Windows startup (HKCU Run) ; zana/single_instance.py
zana/storage/      SQLite history
tests/
```
