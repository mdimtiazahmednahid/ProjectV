import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List

from app.automation.browser_dom_extractor import CLIPBOARD_BATCH_PREFIX

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_PORT = 19876


class _BridgeRequestHandler(BaseHTTPRequestHandler):
    server_version = "FBContestLocalBridge/2.2"

    def log_message(self, format, *args):
        # Silence per-request console spam
        pass

    def _send_cors_headers(self, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Requested-With")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_OPTIONS(self):
        self._send_cors_headers(200)

    def do_GET(self):
        self._send_cors_headers(200)
        self.wfile.write(b'{"ok":true,"service":"fb_contest_validator"}')

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_bytes = self.rfile.read(length) if length > 0 else b""
            raw_text = raw_bytes.decode("utf-8", errors="replace").strip()
            if raw_text:
                if not raw_text.startswith(CLIPBOARD_BATCH_PREFIX):
                    # Validate JSON object and wrap with CLIPBOARD_BATCH_PREFIX
                    obj = json.loads(raw_text)
                    if isinstance(obj, dict) and "items" in obj:
                        raw_text = CLIPBOARD_BATCH_PREFIX + json.dumps(obj, ensure_ascii=False)
                if raw_text.startswith(CLIPBOARD_BATCH_PREFIX):
                    self.server.bridge_owner.enqueue_batch_str(raw_text)
            self._send_cors_headers(200)
            self.wfile.write(b'{"ok":true}')
        except Exception as e:
            logger.debug(f"LocalBridge POST error: {e}")
            self._send_cors_headers(400)
            self.wfile.write(b'{"ok":false}')


class LocalBridgeServer:
    """
    Lightweight localhost HTTP bridge (`http://127.0.0.1:19876/batch`) that receives
    scraped Likes, Comments, and Shares batches directly from the Chrome/Edge Extension
    and Bookmarklet on Windows & macOS — completely bypassing clipboard focus restrictions!
    """

    def __init__(self, port: int = DEFAULT_BRIDGE_PORT):
        self.port = port
        self._lock = threading.Lock()
        self._queue: List[str] = []
        self._httpd: ThreadingHTTPServer = None
        self._thread: threading.Thread = None

    def start(self) -> bool:
        if self._httpd is not None:
            return True
        for candidate_port in (self.port, self.port + 1, self.port + 2):
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", candidate_port), _BridgeRequestHandler)
                httpd.bridge_owner = self
                self.port = candidate_port
                self._httpd = httpd
                self._thread = threading.Thread(
                    target=httpd.serve_forever,
                    name="FBContestLocalBridge",
                    daemon=True,
                )
                self._thread.start()
                logger.info(f"Local HTTP Extension Bridge listening on http://127.0.0.1:{self.port}/batch")
                return True
            except Exception as e:
                logger.debug(f"Port {candidate_port} unavailable for LocalBridgeServer: {e}")
        return False

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None

    def enqueue_batch_str(self, batch_str: str) -> None:
        with self._lock:
            self._queue.append(batch_str)

    def pop_batches(self) -> List[str]:
        with self._lock:
            if not self._queue:
                return []
            items = list(self._queue)
            self._queue.clear()
            return items

