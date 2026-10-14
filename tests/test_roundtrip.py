"""format_line and parse_line are inverses, and clean_text always yields a line that parses as one comment."""

import itertools

import pytest

from mkdocs_review_comments.core import Comment, Grammar, clean_text

AUTHORS = ["Mark", "Mark Lazarides", "Josephine  Bloggs", "Ñandú O'Brien-Smith", "re", "resolved"]
TEXTS = ["x", "has -- dashes", "a [link](p.md#rc-AA-1)", "unicode ✓ café", "trailing space ", "  leading", "tab\tinside", "pipe | and --> close"]
TAGS = ["RC", "REV", "R-C"]


@pytest.mark.parametrize("tag, author, text", list(itertools.product(TAGS, AUTHORS, TEXTS)))
def test_format_then_parse_is_identity(tag, author, text):
    g = Grammar(tag=tag)
    author, text = clean_text(author), clean_text(text)
    for c in (
        Comment(id="ML-7", author=author, date="2026-10-14", text=text, line_no=0),
        Comment(id="ML-7", author=author, date="2026-10-14", text=text, line_no=0, re="DD-14", indent="    "),
        Comment(id="DD-14", author=author, date="2026-10-14", text=text, line_no=0, resolved=True),
    ):
        line = g.format_line(c)
        assert "\n" not in line
        back = g.parse_line(line, 1)
        assert back is not None, line
        assert (back.id, back.author, back.date, back.text, back.re, back.resolved, back.indent) == (
            c.id, c.author, c.date, c.text, c.re, c.resolved, c.indent
        )
        # and the line is one comment, not two
        assert len(g.parse_page("p.md", line + "\n")) == 1


def test_clean_text_output_cannot_break_out_of_the_comment():
    for raw in ["-->", "a --> b <!-- c", "x\ny\r\nz", "|||", "<!-- RC#ZZ-1 A 2026-01-01 | nested -->"]:
        g = Grammar()
        c = Comment(id="AA-1", author="A", date="2026-01-01", text=clean_text(raw), line_no=0)
        line = g.format_line(c)
        assert line.count("-->") == 1 and line.endswith("-->")
        assert g.parse_line(line, 1).text == clean_text(raw)
