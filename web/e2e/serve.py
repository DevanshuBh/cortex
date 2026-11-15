"""Static server for the end-to-end tests: serves out/ like GitHub Pages does, optionally under a sub-path.

`python -m http.server` keeps a listen backlog of 5, so parallel browsers get "connection refused" on a busy machine;
this one keeps 128 and is threaded.

    python e2e/serve.py 3100 out [/base-path]
"""

from __future__ import annotations

import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Handler(SimpleHTTPRequestHandler):
    base = ""

    def translate_path(self, path: str) -> str:
        if self.base and path.startswith(self.base):
            path = path[len(self.base) :] or "/"
        return super().translate_path(path)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - signature from the base class
        pass


class Server(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def main() -> None:
    port, root, *rest = sys.argv[1:]
    Handler.base = rest[0].rstrip("/") if rest else ""
    Handler.extensions_map = {**Handler.extensions_map, ".js": "text/javascript", ".mjs": "text/javascript"}
    server = Server(("127.0.0.1", int(port)), functools.partial(Handler, directory=root))
    server.serve_forever()


if __name__ == "__main__":
    main()
