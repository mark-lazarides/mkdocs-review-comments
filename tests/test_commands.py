"""rc archive, delete, check and --docs, run in-process against a throwaway docs folder."""

from pathlib import Path

import pytest

from mkdocs_review_comments.cli import main
from mkdocs_review_comments.core import Grammar

INDEX = """# Home

para

<!-- RC#AA-1 Ann 2026-01-01 | one -->
<!-- RC#BB-1 Bob 2026-01-02 re AA-1 | reply -->
<!-- RC#AA-1 resolved Ann 2026-01-03 | done -->

<!-- RC#AA-2 Ann 2026-01-01 | still open -->
"""
SUB = """# Sub

## Part

<!-- RC#CC-1 Cy 2026-01-04 | three -->
<!-- RC#CC-1 resolved Cy 2026-01-05 | ok -->
"""


@pytest.fixture
def site(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "index.md").write_text(INDEX, encoding="utf-8")
    (docs / "sub" / "p.md").write_text(SUB, encoding="utf-8")
    (tmp_path / "mkdocs.yml").write_text("site_name: S\nplugins:\n  - review-comments\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return docs


def rc(*args: str) -> None:
    main(list(args))


def exit_code(*args: str) -> int:
    with pytest.raises(SystemExit) as e:
        rc(*args)
    return e.value.code


def test_archive_moves_resolved_threads_newest_first_and_is_idempotent(site, capsys):
    rc("archive")
    log = (site / "reviews" / "comment-log.md").read_text(encoding="utf-8")
    assert "AA-1" not in (site / "index.md").read_text(encoding="utf-8")
    assert "AA-2" in (site / "index.md").read_text(encoding="utf-8")
    assert "RC#" not in (site / "sub" / "p.md").read_text(encoding="utf-8")
    heads = [l for l in log.splitlines() if l.startswith("### ")]
    assert [h.split()[1] for h in heads] == ["CC-1", "AA-1"]
    assert "[sub/p.md](../sub/p.md#part)" in heads[0] and "[index.md](../index.md#home)" in heads[1]
    assert "- **BB-1 Bob 2026-01-02** (re AA-1): reply" in log
    rc("archive")
    assert "nothing to archive" in capsys.readouterr().out
    assert (site / "reviews" / "comment-log.md").read_text(encoding="utf-8") == log
    # a later archive goes above the earlier entries, below the intro
    rc("resolve", "AA-2", "later", "--by", "Ann")
    rc("archive")
    heads = [l.split()[1] for l in (site / "reviews" / "comment-log.md").read_text(encoding="utf-8").splitlines() if l.startswith("### ")]
    assert heads == ["AA-2", "CC-1", "AA-1"]


def test_archived_links_resolve_in_check(site):
    rc("archive")
    (site / "index.md").write_text("# Home\n\n<!-- RC#DD-1 Dee 2026-01-06 re BB-1 | points at an archived reply -->\n", encoding="utf-8")
    assert exit_code("check") == 0


def test_delete_needs_the_root_id(site):
    assert "reply inside thread AA-1" in str(exit_code("delete", "BB-1"))  # sys.exit(message)
    rc("delete", "AA-1")
    text = (site / "index.md").read_text(encoding="utf-8")
    assert "AA-1" not in text and "BB-1" not in text and "AA-2" in text


def test_check_exit_codes(site, capsys):
    assert exit_code("check") == 0
    (site / "index.md").write_text(INDEX + "\n<!-- RC#AA-2 Ann 2026-01-01 | duplicate -->\n", encoding="utf-8")
    assert exit_code("check") == 1
    assert "duplicate id AA-2" in capsys.readouterr().out


def test_list_shows_open_only_by_default(site, capsys):
    rc("list")
    out = capsys.readouterr().out
    assert "AA-2  [open]" in out and "AA-1" not in out and "2 resolved" in out
    rc("list", "--all")
    assert "AA-1  [resolved]" in capsys.readouterr().out


def test_docs_mode_without_a_mkdocs_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # no mkdocs.yml here
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("# A\n\n<!-- RC#AA-1 Ann 2026-01-01 | x -->\n", encoding="utf-8")
    assert "no mkdocs.yml" in str(exit_code("list"))
    rc("--docs", "notes", "list")
    assert "AA-1  [open]" in capsys.readouterr().out
    rc("--docs", "notes", "reply", "AA-1", "ok", "--by", "Bob", "--as", "BB", "--date", "2026-01-02")
    assert "RC#BB-1 Bob 2026-01-02 re AA-1 | ok" in (tmp_path / "notes" / "a.md").read_text(encoding="utf-8")


def test_reply_and_resolve_keep_the_threads_indent(site):
    (site / "index.md").write_text("# H\n\n!!! note\n    text\n\n    <!-- RC#AA-1 Ann 2026-01-01 | in admonition -->\n", encoding="utf-8")
    rc("reply", "AA-1", "r", "--by", "Bob", "--as", "BB", "--date", "2026-01-02")
    rc("resolve", "AA-1", "done", "--by", "Bob", "--date", "2026-01-03")
    lines = (site / "index.md").read_text(encoding="utf-8").splitlines()
    assert lines[-2:] == ["    <!-- RC#BB-1 Bob 2026-01-02 re AA-1 | r -->", "    <!-- RC#AA-1 resolved Bob 2026-01-03 | done -->"]
    assert Grammar().parse_page("index.md", "\n".join(lines) + "\n")[0].is_resolved
