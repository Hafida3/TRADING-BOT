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
        elif self.path.startswith("/api/trades"):
            self._serve_trades()
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
            import sqlite3
            import time
            from layers.data.database import get_stats
            stats = get_stats()

            db_path = _DATA_JSON.parent / "trading_bot.db"
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cutoff = time.time() - 86400
            row = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(net_pnl, pnl_usdc)), 0.0) AS total "
                "FROM trades WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()
            conn.close()
            pnl_24h = float(row["total"]) if row else 0.0
            stats["pnl_24h_usdc"] = round(pnl_24h, 4)
            stats["pnl_24h_pct"]  = round(pnl_24h / 50.0 * 100, 4)

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

    def _serve_trades(self):
        try:
            import sqlite3
            db_path = Path(__file__).parent.parent / "trading_bot.db"
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, timestamp, direction, entry_price, exit_price, "
                "pnl_usdc, gross_pnl, fee_usdc, net_pnl "
                "FROM trades ORDER BY timestamp ASC"
            ).fetchall()
            conn.close()
            payload = json.dumps([dict(r) for r in rows]).encode()
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
