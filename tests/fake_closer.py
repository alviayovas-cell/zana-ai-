"""A scripted stand-in for AppCloser, for UI tests (never touches a real process)."""

from zana.apps.closer import CloseOutcome


class FakeCloser:
    def __init__(self, close_script=None, force_script=None):
        self.close_script = list(close_script or [])
        self.force_script = list(force_script or [])
        self.close_calls, self.force_calls = [], []

    def close(self, entry, hwnds=None):
        self.close_calls.append((entry.id, None if hwnds is None else list(hwnds)))
        if self.close_script:
            out = self.close_script.pop(0)
            if isinstance(out, Exception):
                raise out
            return out
        return CloseOutcome("closed", f"Closed {entry.name}.", entry)

    def force(self, entry):
        self.force_calls.append(entry.id)
        if self.force_script:
            return self.force_script.pop(0)
        return CloseOutcome("closed", f"Force-closed {entry.name}.", entry)
