"""A fake Windows process/window layer: no test using it can touch a real process."""

from zana.apps.processes import ProcInfo, WindowInfo
from zana.apps.registry import AppEntry

WIN = r"C:\Windows"
WINAPPS = r"C:\Program Files\WindowsApps"


def proc(pid, name, path, ppid=1, created=100):
    return ProcInfo(pid, ppid, name, path, created)


def win(hwnd, pid, title="Window", cls="Chrome_WidgetWin_1", frame_pids=()):
    return WindowInfo(hwnd, pid, title, cls, tuple(frame_pids))


class FakeClock:
    """Each call advances time, so wait loops finish instantly and deterministically."""

    def __init__(self, step=0.25):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


class FakeProcessApi:
    """behaviours maps hwnd -> what WM_CLOSE does:
       "exit"  window closes; the process exits when its last window is gone (default)
       "hide"  window closes, the process keeps running (tray app)
       "stuck" nothing happens (unsaved-changes prompt / hung app)
    """

    def __init__(self, procs, windows, own_pid=9999, behaviours=None, terminate_fails=()):
        self.procs, self.windows = list(procs), list(windows)
        self._own = own_pid
        self.behaviours = behaviours or {}
        self.posted, self.terminated = [], []
        self.terminate_fails = set(terminate_fails)
        self.list_calls = 0
        self.reuse_pid_after_call = None     # (call_number, pid): that pid gets a new creation time

    def own_pid(self):
        return self._own

    def list_processes(self):
        self.list_calls += 1
        out = list(self.procs)
        if self.reuse_pid_after_call and self.list_calls > self.reuse_pid_after_call[0]:
            pid = self.reuse_pid_after_call[1]
            out = [ProcInfo(p.pid, p.ppid, p.name, p.path, p.created + 1) if p.pid == pid else p for p in out]
        return out

    def list_windows(self):
        return list(self.windows)

    def post_close(self, hwnd):
        self.posted.append(hwnd)
        w = next((w for w in self.windows if w.hwnd == hwnd), None)
        mode = self.behaviours.get(hwnd, "exit")
        if w is None or mode == "stuck":
            return True
        self.windows = [x for x in self.windows if x.hwnd != hwnd]
        if mode == "exit" and not any(x.pid == w.pid for x in self.windows):
            dead = {w.pid}                         # the process and all of its helpers exit
            while True:
                more = {p.pid for p in self.procs if p.ppid in dead} - dead
                if not more:
                    break
                dead |= more
            self.procs = [p for p in self.procs if p.pid not in dead]
        return True

    def terminate(self, pid):
        self.terminated.append(pid)
        if pid in self.terminate_fails:
            return False
        self.procs = [p for p in self.procs if p.pid != pid]
        self.windows = [w for w in self.windows if w.pid != pid]
        return True


# ---- ready-made approved entries --------------------------------------------------
SPOTIFY = AppEntry("spotify", "Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "uwp")
SPOTIFY_EXE = WINAPPS + r"\SpotifyAB.SpotifyMusic_1.250.0.0_x64__zpdnekdrzrea0\Spotify.exe"
WHATSAPP = AppEntry("whatsapp", "WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", "uwp")
WHATSAPP_EXE = WINAPPS + r"\5319275A.WhatsAppDesktop_2.2450.0.0_x64__cv1g1gvanyjgm\WhatsApp.Root.exe"
CHROME = AppEntry("google-chrome", "Google Chrome", "Chrome", "uwp")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
NOTEPAD = AppEntry("notepad", "Notepad", WIN + r"\System32\notepad.exe", "exe", aliases=("text editor",),
                   builtin=True, match_images=("notepad.exe",), package="Microsoft.WindowsNotepad")
CALCULATOR = AppEntry("calculator", "Calculator", WIN + r"\System32\calc.exe", "exe", builtin=True,
                      match_images=("calculatorapp.exe", "calculator.exe", "calc.exe"),
                      package="Microsoft.WindowsCalculator")
EXPLORER = AppEntry("file-explorer", "File Explorer", WIN + r"\explorer.exe", "exe", builtin=True,
                    match_images=("explorer.exe",), window_classes=("CabinetWClass", "ExploreWClass"),
                    never_terminate=True)
MYTOOL = AppEntry("my-tool", "My Tool", r"C:\Tools\mytool.exe", "exe")
