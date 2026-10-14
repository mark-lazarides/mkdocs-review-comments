"""Serve the review build and accept comments from it.

``rc serve`` runs ``mkdocs serve`` in review mode in this process and a small
JSON API beside it.  The buttons the plugin adds to the review build post here;
each post writes one tagged comment line into the markdown source, and the
MkDocs live reload rebuilds the page.

POST /api/comment  JSON body:
    page      src path relative to the docs dir, e.g. "reviews/x/review.md"  (required)
    author    display name                                                    (required)
    initials  id prefix, e.g. "ML"                                           (required unless resolve)
    text      the comment                                                     (required)
    anchor    heading anchor for a new root comment (omit or "" for page top)
    level     heading level 1-6 and
    ordinal   its 0-based position among headings of that level: the fallback when the
              rendered anchor does not match a markdown heading (optional)
    re        id of the comment being replied to      (reply)
    resolve   id of the thread being resolved         (resolution)
Exactly one of anchor / re / resolve selects the mode.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core import Comment, Grammar, SourceFile, clean_text, index_by_id, next_number

INITIALS_RE = re.compile(r"^[A-Z]{2,3}$")
log = logging.getLogger("rc-api")


class CommentWriter:
    def __init__(self, docs_dir: Path, grammar: Grammar):
        self.docs = docs_dir.resolve()
        self.grammar = grammar
        self._lock = threading.Lock()  # the server is threaded; numbering and the file edit must not interleave

    def write(self, body: dict) -> dict:
        with self._lock:
            return self._write(body)

    FIELDS = ("page", "author", "initials", "text", "anchor", "re", "resolve")

    def _write(self, body: dict) -> dict:
        g = self.grammar
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        for k in self.FIELDS:
            if k in body and body[k] is not None and not isinstance(body[k], str):
                raise ValueError(f"{k} must be a string")
        where: dict = {"anchor": body.get("anchor") or ""}
        for k in ("level", "ordinal"):
            v = body.get(k)
            if v is not None:
                if isinstance(v, bool) or not isinstance(v, (int, str)) or (isinstance(v, str) and not v.isdigit()):
                    raise ValueError(f"{k} must be a whole number")
                where[k] = int(v)
        page = body.get("page") or ""
        path = (self.docs / page).resolve()
        if not page or path.suffix.lower() != ".md" or not path.is_file() or self.docs not in path.parents:
            raise ValueError(f"unknown page {page!r}")
        author = " ".join((body.get("author") or "").split())
        text = clean_text(body.get("text") or "")
        if not author or not text:
            raise ValueError("author and text are required")
        date = dt.date.today().isoformat()
        threads = g.scan(self.docs)
        src = SourceFile.read(path)
        page_text = src.text
        if body.get("resolve"):
            t = index_by_id(threads).get(body["resolve"])
            if t is None:
                raise ValueError(f"no thread {body['resolve']}")
            if t.page != page:
                raise ValueError(f"{t.id} lives on {t.page}, not {page}")
            if t.is_resolved:
                raise ValueError(f"{t.id} is already resolved")
            c = Comment(id=t.id, author=author, date=date, text=text, line_no=0, indent=t.root.indent, resolved=True)
            new_text = g.append_to_thread(page_text, t, g.format_line(c))
            result = {"id": t.id, "mode": "resolve"}
        else:
            initials = (body.get("initials") or "").strip().upper()
            if not INITIALS_RE.match(initials):
                raise ValueError("initials must be two or three letters")
            cid = f"{initials}-{next_number(threads, initials, g.archived_ids(self.docs))}"
            if body.get("re"):
                t = index_by_id(threads).get(body["re"])
                if t is None:
                    raise ValueError(f"no comment {body['re']}")
                c = Comment(id=cid, author=author, date=date, text=text, line_no=0, indent=t.root.indent, re=body["re"])
                if t.page == page:
                    new_text = g.append_to_thread(page_text, t, g.format_line(c))
                else:  # reply from another page: a new thread under the given heading, linked by ``re``
                    new_text = g.insert_root(page_text, line=g.format_line(c), **where)
                result = {"id": cid, "mode": "reply"}
            else:
                c = Comment(id=cid, author=author, date=date, text=text, line_no=0)
                new_text = g.insert_root(page_text, line=g.format_line(c), **where)
                result = {"id": cid, "mode": "root"}
        src.write(new_text)
        return result


def make_handler(writer: CommentWriter):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):  # CORS preflight from the site on the other port
            self._send(204, {})

        def do_GET(self):  # liveness only; the docs path is not something any site on the network needs
            self._send(200, {"ok": True})

        def do_POST(self):
            if self.path.rstrip("/") != "/api/comment":
                return self._send(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                result = writer.write(body)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e)})
            log.info("wrote %s %s on %s", result["mode"], result["id"], body.get("page"))
            self._send(200, result)

        def log_message(self, fmt, *args):
            log.info(fmt, *args)

    return Handler


def _port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("127.0.0.1" if host in ("0.0.0.0", "") else host, port))
        return True
    except OSError:
        return False


def api_url(host: str, api_port: int) -> str:
    """What the page should post to. A wildcard host is left for the page to fill in from its own location."""
    return f"http://{host}:{api_port}"


def serve(config_file: str | None, host: str, port: int, api_port: int, docs_dir: Path, grammar: Grammar) -> None:
    # MkDocs logs through `logging`; when serve() is called from code nothing configures it.
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s -  %(message)s", stream=sys.stderr)

    # Refuse to start on top of another copy. Windows lets two processes bind the same port
    # when SO_REUSEADDR is set, which both servers do, and the result is two sites on one URL.
    for p in (api_port, port):
        if _port_in_use(host, p):
            sys.exit(f"port {p} is already in use: another `rc serve` or `mkdocs serve` is running. Stop it first.")

    # The plugin reads both: review mode on, and where the page-side comment box should post.
    os.environ["RC_REVIEW"] = "1"
    os.environ["RC_API_URL"] = api_url(host, api_port)
    # The API listens on the same interface as the site, so a reviewer on another machine can comment too.
    api = ThreadingHTTPServer((host, api_port), make_handler(CommentWriter(docs_dir, grammar)))
    threading.Thread(target=api.serve_forever, daemon=True).start()
    log.info("comment API on %s/api/comment", os.environ["RC_API_URL"])
    log.info("review site will be on http://%s:%d/ once the build below finishes", host, port)

    # livereload=True is passed explicitly: with click 8.2 the CLI default silently comes
    # out False, so a bare `mkdocs serve` does not rebuild on file changes.
    from mkdocs.commands.serve import serve as mkdocs_serve

    mkdocs_serve(config_file=config_file, dev_addr=f"{host}:{port}", livereload=True)
