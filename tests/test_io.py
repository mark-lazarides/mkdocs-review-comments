"""Every write must leave the file byte-identical apart from the intended lines."""

import difflib

import pytest

from mkdocs_review_comments.core import Grammar, SourceFile

BODY = "# Title\n\nintro\n\n## Two\n\npara two\n"
NEW = "<!-- RC#ML-1 Mark 2026-10-14 | new -->"

VARIANTS = {
    "lf": BODY.encode(),
    "crlf": BODY.replace("\n", "\r\n").encode(),
    "no-final-newline": BODY.rstrip("\n").encode(),
    "bom-crlf": b"\xef\xbb\xbf" + BODY.replace("\n", "\r\n").encode(),
}


def added_lines(before: bytes, after: bytes) -> list[str]:
    """Lines that differ between two files, with their diff prefix; the only ones should be the insertion."""
    a = before.decode("utf-8").splitlines(keepends=True)
    b = after.decode("utf-8").splitlines(keepends=True)
    return [d for d in difflib.ndiff(a, b) if d[:1] in "+-"]


@pytest.mark.parametrize("name", list(VARIANTS))
def test_insert_changes_only_the_intended_lines(tmp_path, name):
    path = tmp_path / "p.md"
    before = VARIANTS[name]
    path.write_bytes(before)
    src = SourceFile.read(path)
    src.write(Grammar().insert_root(src.text, "two", NEW))
    after = path.read_bytes()
    eol = "\r\n" if "crlf" in name else "\n"
    expect = [f"+ {eol}", f"+ {NEW}{eol}"]
    if name == "no-final-newline":  # the old last line gains an eol, the new last line has none
        expect = ["- para two", f"+ para two{eol}", f"+ {eol}", f"+ {NEW}"]
    assert added_lines(before, after) == expect
    assert after.startswith(b"\xef\xbb\xbf") == name.startswith("bom")


def test_bom_does_not_hide_the_first_heading(tmp_path):
    path = tmp_path / "p.md"
    path.write_bytes(b"\xef\xbb\xbf# Title\n\npara\n")
    text = SourceFile.read(path).text
    assert Grammar().heading_anchor(text.splitlines()[0]) == ("Title", "title")


def test_write_round_trip_is_identity(tmp_path):
    for name, data in VARIANTS.items():
        path = tmp_path / f"{name}.md"
        path.write_bytes(data)
        src = SourceFile.read(path)
        src.write(src.text)
        assert path.read_bytes() == data, name
