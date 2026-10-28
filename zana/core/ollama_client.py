"""Minimal streaming client for the local Ollama HTTP API (stdlib only)."""

import json
import threading
import urllib.error
import urllib.request
from typing import Iterator, Optional


class OllamaError(Exception):
    """Raised for any problem talking to Ollama; message is user-presentable."""


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _open(self, path: str, payload: Optional[dict] = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise OllamaError(
                    f"Model '{self.model}' not found. Run: ollama pull {self.model}"
                ) from e
            raise OllamaError(f"Ollama returned HTTP {e.code}.") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise OllamaError(
                f"Cannot reach Ollama at {self.base_url}. Is it running?"
            ) from e

    def list_models(self) -> list[str]:
        with self._open("/api/tags") as resp:
            data = json.load(resp)
        return [m.get("name", "") for m in data.get("models", [])]

    def is_available(self) -> bool:
        try:
            return self.model in self.list_models()
        except (OllamaError, ValueError):
            return False

    def stream_chat(
        self, messages: list[dict], cancel: Optional[threading.Event] = None
    ) -> Iterator[str]:
        """Yield response text chunks. Thinking mode is disabled for speed."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "think": False,
        }
        resp = self._open("/api/chat", payload)
        try:
            for raw in resp:
                if cancel is not None and cancel.is_set():
                    return
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError as e:
                    raise OllamaError("Received an invalid response from Ollama.") from e
                if "error" in obj:
                    raise OllamaError(str(obj["error"]))
                chunk = obj.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if obj.get("done"):
                    return
        except (TimeoutError, ConnectionError, OSError) as e:
            raise OllamaError("Connection to Ollama was lost.") from e
        finally:
            resp.close()
