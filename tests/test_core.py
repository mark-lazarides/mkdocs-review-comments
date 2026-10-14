from pathlib import Path

import pytest

from mkdocs_review_comments.core import Comment, Grammar, clean_text, index_by_id, next_number

PAGE = """# Title

intro para

## One { #one }

text one

| a | b |
|---|---|
| 1 | 2 |

## Two

- item a
- item b

<!-- RC#AA-1 Ann Other 2026-10-13 | existing -->
<!-- RC#BB-1 Bob 2026-10-13 re AA-1 | reply -->
<!-- RC#AA-1 resolved Bob 2026-10-14 | done -->

## Three

last para

---
"""

NEW = "<!-- RC#ML-1 Mark 2026-10-14 | new -->"


@pytest.fixture
def g():
    return Grammar()


def test_parse_threads_and_names_with_spaces(g):
    threads = g.parse_page("p.md", PAGE)
    assert [t.id for t in threads] == ["AA-1"]
    t = threads[0]
    assert t.anchor == "two" and t.heading == "Two"
    assert t.root.author == "Ann Other"
    assert [c.id for c in t.replies] == ["BB-1"]
    assert t.is_resolved and t.resolution.author == "Bob"
    assert t.first_line == 18 and t.last_line == 20


def test_explicit_and_slug_anchors(g):
    assert g.heading_anchor("## One { #one }") == ("One", "one")
    assert g.heading_anchor("## F — Schematic AB4 against the notes") == ("F — Schematic AB4 against the notes", "f-schematic-ab4-against-the-notes")


def test_custom_tag():
    g = Grammar(tag="REV")
    assert g.parse_line("<!-- REV#AB-2 Al 2026-01-01 | x -->", 1).id == "AB-2"
    assert g.parse_line("<!-- RC#AB-2 Al 2026-01-01 | x -->", 1) is None


def test_format_round_trip(g):
    c = Comment(id="ML-3", author="Mark L", date="2026-10-14", text="hello", line_no=0, re="AA-1")
    line = g.format_line(c)
    back = g.parse_line(line, 1)
    assert (back.id, back.author, back.re, back.text) == ("ML-3", "Mark L", "AA-1", "hello")


@pytest.mark.parametrize(
    "anchor, expect_prev, expect_next",
    [
        ("one", "", ""),  # after the table, blank line either side
        ("two", "<!-- RC#AA-1 resolved Bob 2026-10-14 | done -->", ""),  # directly under the existing thread
        ("three", "", ""),  # before the closing rule, not after it
        ("title", "", ""),  # intro section of the page
    ],
)
def test_insert_root_placement(g, anchor, expect_prev, expect_next):
    out = g.insert_root(PAGE, anchor, NEW)
    lines = out.splitlines()
    i = lines.index(NEW)
    assert lines[i - 1] == expect_prev
    assert lines[i + 1] == expect_next
    assert g.check(g.parse_page("p.md", out), Path(".")) == []


def test_insert_root_before_rule(g):
    out = g.insert_root(PAGE, "three", NEW).splitlines()
    assert out.index(NEW) < out.index("---")


def test_insert_root_unknown_anchor(g):
    with pytest.raises(KeyError):
        g.insert_root(PAGE, "nope", NEW)


def test_append_and_delete(g):
    t = g.parse_page("p.md", PAGE)[0]
    out = g.append_to_thread(PAGE, t, "<!-- RC#CC-1 Cy 2026-10-15 re AA-1 | late -->")
    assert len(g.parse_page("p.md", out)[0].lines) == 4
    gone = g.delete_thread(PAGE, t)
    assert "RC#" not in gone


def test_next_number_and_index(g):
    threads = g.parse_page("p.md", PAGE)
    assert next_number(threads, "AA") == 2
    assert next_number(threads, "BB") == 2
    assert next_number(threads, "ZZ") == 1
    assert set(index_by_id(threads)) == {"AA-1", "BB-1"}


def test_check_reports_problems(g, tmp_path):
    bad = "## H\n\n| a |\n|---|\n<!-- RC#AA-1 A 2026-01-01 | in table -->\n| 1 |\n\n<!-- RC#AA-1 A 2026-01-01 | dup -->\n<!-- RC#AA-2 A 2026-01-01 re QQ-9 | dangling -->\n"
    (tmp_path / "p.md").write_text(bad, encoding="utf-8")
    problems = g.check(g.scan(tmp_path), tmp_path)
    assert any("duplicate id AA-1" in p for p in problems)
    assert any("unknown id QQ-9" in p for p in problems)
    assert any("between table rows" in p for p in problems)


def test_archived_ids_satisfy_check(g, tmp_path):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "comment-log.md").write_text("# Log\n\n### AA-9 — x\n", encoding="utf-8")
    (tmp_path / "p.md").write_text("## H\n\n<!-- RC#BB-1 B 2026-01-01 re AA-9 | ok -->\n", encoding="utf-8")
    assert g.check(g.scan(tmp_path), tmp_path) == []


def test_clean_text():
    assert clean_text("a |\n b --> c") == "a / b -- > c"


def test_check_flags_malformed_tagged_lines(g, tmp_path):
    (tmp_path / "p.md").write_text("## H\n\n<!-- RC#AA-1 A 2026-01-01 | unterminated\nstray -->\n<!-- RC#bad -->\n", encoding="utf-8")
    problems = g.check(g.scan(tmp_path), tmp_path)
    assert [p.split(":")[1] for p in problems if "malformed" in p] == ["3", "5"]


FENCED = """---
title: Front
---

# Real

```markdown
# fake heading
<!-- RC#ZZ-1 Doc 2026-01-01 | example in the docs -->
```

~~~
<!-- RC#ZZ-2 Doc 2026-01-01 | tilde fence -->
~~~

<!-- RC#AA-1 Ann 2026-01-01 | real -->
"""


def test_fences_and_front_matter_are_not_parsed(g):
    threads = g.parse_page("p.md", FENCED)
    assert [(t.id, t.heading) for t in threads] == [("AA-1", "Real")]


def test_insert_root_ignores_fenced_headings_and_front_matter(g):
    with pytest.raises(KeyError):
        g.insert_root(FENCED, "fake-heading", NEW)
    out = g.insert_root(FENCED, "", NEW).splitlines()
    assert out[:4] == ["---", "title: Front", "---", ""] and out[4] == NEW


def test_check_ignores_fenced_comments(g, tmp_path):
    (tmp_path / "p.md").write_text("# H\n\n```\n<!-- RC#bad -->\n| a |\n<!-- RC#AA-1 A 2026-01-01 | x -->\n| b |\n```\n", encoding="utf-8")
    assert g.check(g.scan(tmp_path), tmp_path) == []


def test_next_number_counts_archived_ids(g, tmp_path):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "comment-log.md").write_text(
        "# Log\n\n### ML-7 — [p.md](../p.md#h) { #ml-7 }\n\n- **ML-7 Mark 2026-01-01:** root\n- **DD-3 Josephine 2026-01-02** (re ML-7): reply\n",
        encoding="utf-8",
    )
    (tmp_path / "p.md").write_text("# H\n\n<!-- RC#ML-2 Mark 2026-01-03 | live -->\n", encoding="utf-8")
    archived = g.archived_ids(tmp_path)
    assert archived == {"ML-7", "DD-3"}
    threads = g.scan(tmp_path)
    assert next_number(threads, "ML", archived) == 8
    assert next_number(threads, "DD", archived) == 4
    assert next_number(threads, "ML") == 3  # without the log, as before
