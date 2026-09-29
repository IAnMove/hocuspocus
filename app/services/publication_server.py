"""Optional app-owned static server for explicitly published artifacts."""
from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_lock = threading.Lock()
_servers: dict[tuple[str, int], tuple[Path, ThreadingHTTPServer]] = {}


class PublicationHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def list_directory(self, path):
        self.send_error(403, "Directory listing is disabled")
        return None

    def translate_path(self, path):
        candidate = Path(super().translate_path(path)).resolve()
        root = Path(self.directory).resolve()
        if not candidate.is_relative_to(root):
            return str(root / ".blocked")
        return str(candidate)


def serve_publication(root: Path, host: str, port: int) -> None:
    """Reuse only this process's server; never stop an occupied external port."""
    root = root.resolve()
    key = (host, port)
    with _lock:
        if key in _servers:
            if _servers[key][0] != root:
                raise ValueError("Publication port already serves another root")
            return
        server = ThreadingHTTPServer(key, functools.partial(PublicationHandler, directory=str(root)))
        server.daemon_threads = True
        _servers[key] = (root, server)
        threading.Thread(target=server.serve_forever, name=f"publication-{port}", daemon=True).start()
