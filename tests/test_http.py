"""The comment API over real HTTP: CORS preflight, routing, error bodies and a successful write."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from mkdocs_review_comments.core import Grammar
from mkdocs_review_comments.serve import CommentWriter, make_handler


@pytest.fixture
def api(tmp_path):
    (tmp_path / "index.md").write_text("# Home\n\npara\n", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(CommentWriter(tmp_path, Grammar())))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    server.shutdown()


def call(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:8802"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read() or b"{}")


def test_preflight_and_liveness(api):
    base, _ = api
    status, headers, _ = call(base + "/api/comment", "OPTIONS")
    assert status == 204 and headers["Access-Control-Allow-Origin"] == "*" and "POST" in headers["Access-Control-Allow-Methods"]
    assert call(base + "/")[0:3:2] == (200, {"ok": True})


def test_routing_and_validation_errors(api):
    base, _ = api
    assert call(base + "/api/other", "POST", {})[0] == 404
    status, _, body = call(base + "/api/comment", "POST", {"page": "index.md", "author": "", "initials": "ML", "text": "x", "anchor": "home"})
    assert status == 400 and "author and text" in body["error"]
    status, _, body = call(base + "/api/comment", "POST", {"page": "index.md", "author": "M", "initials": "ML", "text": "x", "resolve": ["AA-1"]})
    assert status == 400 and "resolve must be a string" in body["error"]
    req = urllib.request.Request(base + "/api/comment", data=b"not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 400


def test_successful_post_writes_the_comment(api):
    base, docs = api
    status, _, body = call(base + "/api/comment", "POST", {"page": "index.md", "author": "Mark", "initials": "ML", "text": "hello", "anchor": "home", "level": 1, "ordinal": 0})
    assert (status, body) == (200, {"id": "ML-1", "mode": "root"})
    assert (docs / "index.md").read_text(encoding="utf-8").endswith("para\n\n<!-- RC#ML-1 Mark " + __import__("datetime").date.today().isoformat() + " | hello -->\n")
