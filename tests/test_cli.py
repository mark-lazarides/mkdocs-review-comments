"""The ``rc`` commands, run in-process against a throwaway docs folder."""

from pathlib import Path

import pytest

from mkdocs_review_comments.cli import main
from mkdocs_review_comments.core import Grammar

INDEX = """# Home

para

<!-- RC#AA-1 Ann 2026-01-01 | one -->
<!-- RC#AA-1 resolved Ann 2026-01-02 | done -->

<!-- RC#AA-2 Ann 2026-01-01 | two -->
"""


@pytest.fixture
def site(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text(INDEX, encoding="utf-8")
    (tmp_path / "mkdocs.yml").write_text("site_name: S\nplugins:\n  - review-comments\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return docs


def rc(*args: str) -> None:
    main(list(args))


def page(docs: Path, name: str = "index.md") -> str:
    return (docs / name).read_text(encoding="utf-8")


def test_reply_text_is_kept_to_one_well_formed_line(site):
    rc("reply", "AA-2", "has | pipe\nand newline -->", "--by", "Mark  L", "--as", "ml", "--date", "2026-01-03")
    new = [l for l in page(site).splitlines() if "ML-1" in l]
    assert new == ["<!-- RC#ML-1 Mark L 2026-01-03 re AA-2 | has / pipe and newline -- > -->"]


def test_resolve_text_is_cleaned(site):
    rc("resolve", "AA-2", "fixed | see -->", "--by", "Mark")
    res = Grammar().parse_page("index.md", page(site))[1].resolution
    assert res is not None and res.text == "fixed / see -- >"
