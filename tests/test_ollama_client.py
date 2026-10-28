import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from zana.core.ollama_client import OllamaClient, OllamaError


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "m:1"}]}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        self.server.last_payload = json.loads(self.rfile.read(n))
        if _Handler.mode == "404":
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.end_headers()
        lines = [
            {"message": {"content": "He"}, "done": False},
            {"message": {"content": "llo"}, "done": False},
            {"message": {"content": ""}, "done": True},
        ]
        if _Handler.mode == "error":
            lines = [{"error": "model exploded"}]
        for l in lines:
            self.wfile.write((json.dumps(l) + "\n").encode())


@pytest.fixture()
def server():
    _Handler.mode = "ok"
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def client(srv, model="m:1"):
    return OllamaClient(f"http://127.0.0.1:{srv.server_port}", model, timeout=5)


def test_streams_chunks_and_disables_thinking(server):
    assert "".join(client(server).stream_chat([{"role": "user", "content": "x"}])) == "Hello"
    assert server.last_payload["think"] is False and server.last_payload["stream"] is True


def test_availability(server):
    assert client(server).is_available()
    assert not client(server, "other").is_available()


def test_error_object_raises(server):
    _Handler.mode = "error"
    with pytest.raises(OllamaError, match="exploded"):
        list(client(server).stream_chat([]))


def test_missing_model_message(server):
    _Handler.mode = "404"
    with pytest.raises(OllamaError, match="ollama pull"):
        list(client(server).stream_chat([]))


def test_unreachable():
    c = OllamaClient("http://127.0.0.1:1", "m", timeout=2)
    with pytest.raises(OllamaError, match="Cannot reach"):
        list(c.stream_chat([]))
    assert not c.is_available()
