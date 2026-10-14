"""The comment API's writer, driven directly, and its small helpers."""

import pytest

from mkdocs_review_comments.core import Grammar
from mkdocs_review_comments.serve import CommentWriter, api_url

INDEX = "# Home\n\npara\n\n<!-- RC#AA-1 Ann 2026-01-01 | one -->\n\n## Two\n\nmore\n"


@pytest.fixture
def docs(tmp_path):
    (tmp_path / "index.md").write_text(INDEX, encoding="utf-8")
    (tmp_path / "style.css").write_text("body { color: red }\n", encoding="utf-8")
    (tmp_path.parent / "outside.md").write_text("# Outside\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def writer(docs):
    return CommentWriter(docs, Grammar())


def read(docs, name="index.md"):
    return (docs / name).read_text(encoding="utf-8")


def test_root_reply_and_resolve(writer, docs):
    assert writer.write({"page": "index.md", "author": "Mark", "initials": "ml", "text": "new", "anchor": "two"}) == {"id": "ML-1", "mode": "root"}
    assert writer.write({"page": "index.md", "author": "Mark", "initials": "ML", "text": "back", "re": "AA-1"}) == {"id": "ML-2", "mode": "reply"}
    assert writer.write({"page": "index.md", "author": "Ann", "text": "done", "resolve": "AA-1"}) == {"id": "AA-1", "mode": "resolve"}
    threads = Grammar().parse_page("index.md", read(docs))
    assert [(t.id, [c.id for c in t.lines], t.is_resolved) for t in threads] == [("AA-1", ["AA-1", "ML-2", "AA-1"], True), ("ML-1", ["ML-1"], False)]
    with pytest.raises(ValueError, match="already resolved"):
        writer.write({"page": "index.md", "author": "Ann", "text": "again", "resolve": "AA-1"})


@pytest.mark.parametrize(
    "body, message",
    [
        ({"page": "style.css", "author": "X", "initials": "XX", "text": "oops", "anchor": ""}, "unknown page"),
        ({"page": "../outside.md", "author": "X", "initials": "XX", "text": "oops", "anchor": ""}, "unknown page"),
        ({"page": "missing.md", "author": "X", "initials": "XX", "text": "oops", "anchor": ""}, "unknown page"),
        ({"page": "index.md", "author": "X", "text": "t", "resolve": ["AA-1"]}, "resolve must be a string"),
        ({"page": "index.md", "author": "X", "initials": 7, "text": "t", "anchor": ""}, "initials must be a string"),
        ({"page": "index.md", "author": "X", "initials": "X", "text": "t", "anchor": ""}, "two or three letters"),
        ({"page": "index.md", "author": "", "initials": "XX", "text": "t", "anchor": ""}, "author and text"),
        ({"page": "index.md", "author": "X", "initials": "XX", "text": "t", "anchor": "nope"}, "no heading"),
        ({"page": "index.md", "author": "X", "initials": "XX", "text": "t", "re": "QQ-9"}, "no comment QQ-9"),
    ],
)
def test_bad_requests_are_rejected_without_writing(writer, docs, body, message):
    before = read(docs), read(docs, "style.css")
    with pytest.raises((ValueError, KeyError), match=message):
        writer.write(body)
    assert (read(docs), read(docs, "style.css")) == before


def test_api_url_follows_the_dev_addr_host():
    assert api_url("127.0.0.1", 8803) == "http://127.0.0.1:8803"
    assert api_url("0.0.0.0", 9000) == "http://0.0.0.0:9000"


def test_concurrent_posts_get_distinct_ids(writer, docs):
    from concurrent.futures import ThreadPoolExecutor

    def post(i):
        return writer.write({"page": "index.md", "author": "Mark", "initials": "ML", "text": f"c{i}", "anchor": "two"})["id"]

    with ThreadPoolExecutor(8) as ex:
        ids = list(ex.map(post, range(24)))
    assert len(set(ids)) == 24
    threads = Grammar().parse_page("index.md", read(docs))
    assert sorted(t.id for t in threads if t.id.startswith("ML")) == sorted(ids)
