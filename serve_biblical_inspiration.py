"""Local static server with clean Bible routes.

Serves the BiblicalInspiration/ folder and adds simple URL rewrites:
- /Book/            -> /Book/index.html
- /Book/<n>         -> /Book/Book<n>.html
- /Book/<n>/        -> same

Examples:
- http://localhost:8000/Mark/1
- http://localhost:8000/Matthew/21
- http://localhost:8000/Mark/ (book index)

Run:
  D:/Webdesign/neocities/.venv/Scripts/python.exe BiblicalInspiration/serve_biblical_inspiration.py

Optional:
  ... serve_biblical_inspiration.py --port 8080
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR  # serve BiblicalInspiration/
TIMINGS_DIR = ROOT_DIR / ".timings"  # local-only persistence for verse start-times


_BOOK_CHAPTER_RE = re.compile(r"^/([A-Za-z0-9]+)/([0-9]+)(?:/)?$")


class RewritingHandler(SimpleHTTPRequestHandler):
    # Python's handler serves from current working directory; we instead serve from ROOT_DIR.

    def _send_json(self, obj: dict, *, status: int = 200) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length else b"{}"
        try:
            decoded = body.decode("utf-8")
        except Exception:
            return None
        try:
            data = json.loads(decoded)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _timing_file_path(self, *, book_order: int, chapter: int) -> Path:
        return TIMINGS_DIR / f"{book_order:02d}" / f"{chapter:03d}.json"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/timing":
            qs = urllib.parse.parse_qs(parsed.query or "")
            try:
                book_order = int((qs.get("bookOrder") or qs.get("book_order") or [""])[0])
                chapter = int((qs.get("chapter") or [""])[0])
            except Exception:
                self._send_json({"error": "bookOrder and chapter are required"}, status=400)
                return

            if book_order < 1 or book_order > 66 or chapter < 1:
                self._send_json({"error": "invalid bookOrder/chapter"}, status=400)
                return

            p = self._timing_file_path(book_order=book_order, chapter=chapter)
            if not p.exists():
                self._send_json({"ok": True, "times": None})
                return
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                self._send_json({"error": "timing file unreadable"}, status=500)
                return

            if not isinstance(data, dict):
                self._send_json({"error": "timing file invalid"}, status=500)
                return

            self._send_json({"ok": True, **data})
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/timing":
            data = self._read_json_body()
            if data is None:
                self._send_json({"error": "invalid json"}, status=400)
                return

            try:
                book_order = int(data.get("bookOrder") or data.get("book_order") or 0)
                chapter = int(data.get("chapter") or 0)
            except Exception:
                self._send_json({"error": "invalid bookOrder/chapter"}, status=400)
                return

            times = data.get("times")
            if not isinstance(times, list) or not times:
                self._send_json({"error": "times must be a non-empty array"}, status=400)
                return

            # Validate times are finite >= 0.
            cleaned: list[float] = []
            for t in times:
                try:
                    x = float(t)
                except Exception:
                    self._send_json({"error": "times must be numbers"}, status=400)
                    return
                if not (x >= 0.0):
                    self._send_json({"error": "times must be >= 0"}, status=400)
                    return
                cleaned.append(round(x, 3))

            if book_order < 1 or book_order > 66 or chapter < 1:
                self._send_json({"error": "invalid bookOrder/chapter"}, status=400)
                return

            payload = {
                "bookOrder": book_order,
                "chapter": chapter,
                "verseCount": int(data.get("verseCount") or len(cleaned)),
                "audioDuration": data.get("audioDuration"),
                "times": cleaned,
            }

            # Optional derived ranges (client-derived). Keep if present.
            ranges = data.get("ranges")
            if isinstance(ranges, list):
                payload["ranges"] = ranges

            p = self._timing_file_path(book_order=book_order, chapter=chapter)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json({"ok": True, "saved": True})
            return

        return super().do_POST()

    def translate_path(self, path: str) -> str:
        # Apply our rewrite rules first.
        rewritten = self._rewrite_path(path)
        # Then translate to filesystem path under ROOT_DIR.
        parsed = urllib.parse.urlparse(rewritten)
        clean = posixpath.normpath(urllib.parse.unquote(parsed.path))
        clean = clean.lstrip("/")

        # Prevent escaping the root.
        full = (ROOT_DIR / clean).resolve()
        if ROOT_DIR not in full.parents and full != ROOT_DIR:
            return str(ROOT_DIR)
        return str(full)

    def _rewrite_path(self, path: str) -> str:
        parsed = urllib.parse.urlparse(path)
        p = parsed.path or "/"

        # /Book/<n> -> /Book/Book<n>.html
        m = _BOOK_CHAPTER_RE.match(p)
        if m:
            book = m.group(1)
            chapter = int(m.group(2))
            new_path = f"/{book}/{book}{chapter}.html"
            return urllib.parse.urlunparse(parsed._replace(path=new_path))

        # /Book or /Book/ -> /Book/index.html
        if p != "/" and p.count("/") <= 2:
            # normalize /Book (no trailing slash)
            if not p.endswith("/"):
                # Only rewrite if there is no extension.
                if "." not in p.split("/")[-1]:
                    new_path = p + "/index.html"
                    return urllib.parse.urlunparse(parsed._replace(path=new_path))
            else:
                new_path = p + "index.html"
                return urllib.parse.urlunparse(parsed._replace(path=new_path))

        return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), RewritingHandler)
    print(f"Serving {ROOT_DIR} at http://{args.host}:{args.port}/")
    print("Example: /Mark/1  /Matthew/21  /Mark/")
    print("Timing API: /api/timing (GET/POST)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
