"""Headings: what we recognise in the markdown, and whether the page-side button can find them.

The browser sends the id MkDocs rendered plus the heading's level and ordinal. For every heading
style below, rendering through the same Markdown pipeline MkDocs uses must lead the button back to
the right markdown line, whether through the anchor or through the fallback.
"""

import re

import markdown
import pytest

from mkdocs_review_comments.core import Grammar, split_lines

PAGE = """\
# Page title

Setext One
==========

## Using `rc check`

## A & B

## See [the spec](spec.md)

## Dup

## Dup

## Closing hashes ##

## X {: #custom }

## Y { #yid .cls }

Setext Two
----------

```bash
# not a heading
```

### Deep
"""

NEW = "<!-- RC#ML-1 Mark 2026-10-14 | new -->"


def rendered_headings(text: str) -> list[tuple[int, str, int]]:
    """(level, id, ordinal-within-level) for each heading as MkDocs would render it."""
    html = markdown.Markdown(extensions=["toc", "attr_list", "fenced_code"]).convert(text)
    out, seen = [], {}
    for level, attrs in re.findall(r"<h([1-6])([^>]*)>", html):
        hid = re.search(r'id="([^"]+)"', attrs).group(1)
        n = seen.get(level, 0)
        seen[level] = n + 1
        out.append((int(level), hid, n))
    return out


def test_we_see_every_heading_the_renderer_sees():
    g = Grammar()
    ours = g.headings(split_lines(PAGE))
    theirs = rendered_headings(PAGE)
    assert [(h.level, h.title) for h in ours] == [
        (1, "Page title"), (1, "Setext One"), (2, "Using `rc check`"), (2, "A & B"), (2, "See [the spec](spec.md)"),
        (2, "Dup"), (2, "Dup"), (2, "Closing hashes"), (2, "X"), (2, "Y"), (2, "Setext Two"), (3, "Deep"),
    ]
    assert len(ours) == len(theirs)


@pytest.mark.parametrize("level, hid, ordinal", rendered_headings(PAGE))
def test_button_finds_the_heading_it_was_on(level, hid, ordinal):
    g = Grammar()
    lines = split_lines(PAGE)
    expected = [h for h in g.headings(lines) if h.level == level][ordinal]
    assert g.locate_heading(lines, hid, level, ordinal) == expected.index
    out = split_lines(g.insert_root(PAGE, hid, NEW, level, ordinal))
    i = out.index(NEW)
    # the comment sits inside that heading's section: after it, before the next heading
    following = [h.index for h in g.headings(out) if h.index > expected.index]
    assert expected.index < i < (following[0] if following else len(out))


def test_anchor_alone_still_works_for_plain_headings():
    g = Grammar()
    assert g.locate_heading(split_lines(PAGE), "a-b") == 7
    assert g.locate_heading(split_lines(PAGE), "custom") == 17
    assert g.locate_heading(split_lines(PAGE), "yid") == 19
    assert g.locate_heading(split_lines(PAGE), "nope") is None


def test_synthesised_h1_means_page_top():
    g = Grammar()
    lines = split_lines("intro\n\n## Only section\n")
    assert g.locate_heading(lines, "title-from-config", 1, 0) == -1
    out = g.insert_root("intro\n\n## Only section\n", "title-from-config", NEW, 1, 0)
    assert split_lines(out)[:3] == ["intro", "", NEW]


def test_custom_slugify_is_used():
    g = Grammar(slugify=lambda t: t.upper().replace(" ", "_"))
    assert g.heading_anchor("## Two Words") == ("Two Words", "TWO_WORDS")


def test_empty_setext_section_keeps_its_underline():
    g = Grammar()
    page = "Title\n=====\n\nSection\n-------\n\n## Next\n"
    out = split_lines(g.insert_root(page, "section", NEW))
    assert out == ["Title", "=====", "", "Section", "-------", NEW, "", "## Next"]
