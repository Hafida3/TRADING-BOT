"""
Lightweight HTTP server that serves dashboard/index.html and exposes
/data.json (read from the root data.json written by the main loop).
Runs in a daemon thread so it doesn't block the trading loop.
"""

import json
import threading
import http.server
from pathlib import Path

_DASHBOARD_DIR = Path(__file__).parent
_DATA_JSON = Path(__file__).parent.parent / "data.json"


http.server.HTTPServer.allow_reuse_address = True


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_DASHBOARD_DIR), **kwargs)

    def do_GET(self):
        if self.path.startswith("/data.json"):
            self._serve_data_json()
        elif self.path.startswith("/stats"):
            self._serve_stats()
        else:
            super().do_GET()

    def _serve_data_json(self):
        try:
            payload = _DATA_JSON.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"data.json not found yet"}')

    def _serve_stats(self):
        try:
            from layers.data.database import get_stats
            stats = get_stats()
            payload = json.dumps(stats).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    def log_message(self, fmt, *args):  # suppress access logs
        pass


def start_dashboard(port: int = 8080) -> threading.Thread:
    server = http.server.HTTPServer(("0.0.0.0", port), _Handler)
    server.allow_reuse_address = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[Dashboard] http://localhost:{port}")
    return thread
