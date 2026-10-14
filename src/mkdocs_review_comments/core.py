"""Parser and file operations for review comments kept in the markdown.

One comment per line, on its own line after the paragraph or table it refers to:

    <!-- RC#DD-14 Josephine Bloggs 2026-10-14 | The figure came from the pump vendor. Cite the close-out. -->
    <!-- RC#ML-7 Mark 2026-10-15 re DD-14 | Agreed. Cited Item 12 and raised TQ-061. -->
    <!-- RC#DD-14 resolved Mark 2026-10-15 | fixed in TQ-061 -->

* ``RC`` is the tag (configurable).  The id is the author's initials and the
  author's own running number, so two people commenting on separate branches
  never collide.
* A thread is a root comment plus the comment lines directly beneath it
  (replies and the resolution line).  A reply carries its own id and ``re <id>``;
  ``re`` may point at a comment on another page.
* Resolving appends a line that reuses the root id with the word ``resolved``.
  ``mkrc archive`` later moves resolved threads to the comment log page.
* Author names may contain spaces.  The text may not contain ``|``.

This module has no MkDocs dependency; the plugin and the CLI both build on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from markdown.extensions.toc import slugify as _md_slugify

BOM = "\ufeff"

DEFAULT_TAG = "RC"
DEFAULT_LOG_PAGE = "reviews/comment-log.md"
ID_RE = r"[A-Z]{2,3}-\d+"
# ATX heading, with optional closing hashes and an optional attr_list block: ``## Title ## {: #id .cls }``.
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.*?)(?:\s+#+)?(?:\s*\{:?\s*(?P<attrs>[^}]*)\})?\s*$")
ATTR_ID_RE = re.compile(r"(?:^|\s)#(?P<id>[^\s}]+)")
SETEXT_RE = re.compile(r"^ {0,3}(?P<char>=+|-+)\s*$")
HR_RE = re.compile(r"\s*([-*_])(\s*\1){2,}\s*")
Slugify = Callable[[str], str]


def default_slugify(title: str) -> str:
    """Python-Markdown's toc slug, as MkDocs uses by default."""
    return _md_slugify(title, "-")


def comment_re(tag: str = DEFAULT_TAG) -> re.Pattern[str]:
    return re.compile(
        rf"^(?P<indent>\s*)<!--\s*{re.escape(tag)}#(?P<id>{ID_RE})\s+"
        rf"(?:(?P<resolved>resolved)\s+)?"
        rf"(?P<author>[^|]+?)\s+(?P<date>\d{{4}}-\d{{2}}-\d{{2}})"
        rf"(?:\s+re\s+(?P<re>{ID_RE}))?"
        rf"\s*\|\s*(?P<text>.*?)\s*-->\s*$"
    )


@dataclass
class Comment:
    id: str
    author: str
    date: str
    text: str
    line_no: int  # 1-based line in the page
    indent: str = ""
    resolved: bool = False  # this line is a resolution line for ``id``
    re: str | None = None

    @property
    def is_reply(self) -> bool:
        return self.re is not None


@dataclass
class Heading:
    index: int  # 0-based line index of the heading text
    level: int
    title: str
    anchor: str


@dataclass
class Thread:
    page: str  # src path relative to the docs dir, forward slashes
    anchor: str  # nearest heading anchor above the thread ("" if none)
    heading: str
    root: Comment
    lines: list[Comment] = field(default_factory=list)  # root first

    @property
    def id(self) -> str:
        return self.root.id

    @property
    def resolution(self) -> Comment | None:
        for c in self.lines[1:]:
            if c.resolved and c.id == self.root.id:
                return c
        return None

    @property
    def is_resolved(self) -> bool:
        return self.resolution is not None

    @property
    def replies(self) -> list[Comment]:
        return [c for c in self.lines[1:] if not (c.resolved and c.id == self.root.id)]

    @property
    def first_line(self) -> int:
        return self.lines[0].line_no

    @property
    def last_line(self) -> int:
        return self.lines[-1].line_no


@dataclass
class SourceFile:
    """A markdown file read for editing: text normalised to LF, plus what is needed to write it back unchanged.

    Every write path goes through here so that a one-line edit stays a one-line diff: the file keeps
    its CRLF or LF endings, its BOM if it had one, and the presence or absence of a final newline.
    """

    path: Path
    text: str  # LF line endings, no BOM
    eol: str = "\n"
    bom: bool = False
    final_newline: bool = True

    @classmethod
    def read(cls, path: Path) -> SourceFile:
        with open(path, encoding="utf-8", newline="") as f:
            raw = f.read()
        bom = raw.startswith(BOM)
        if bom:
            raw = raw[len(BOM) :]
        eol = "\r\n" if "\r\n" in raw else "\n"
        text = raw.replace("\r\n", "\n")
        return cls(path, text, eol, bom, final_newline=(text == "" or text.endswith("\n")))

    def write(self, text: str) -> None:
        if not self.final_newline and text.endswith("\n"):
            text = text[:-1]
        out = (BOM if self.bom else "") + text.replace("\n", self.eol)
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(out)
        self.text = text


def read_text(path: Path) -> str:
    """The file's text with LF endings and no BOM, for parsing."""
    return SourceFile.read(path).text


def split_lines(text: str) -> list[str]:
    """Split on newlines only. ``str.splitlines`` also splits on form feeds, U+2028 and the like,
    which would turn one source line into several and rewrite the page on the next save."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


class Grammar:
    """The tag and page conventions, shared by the plugin and the CLI."""

    def __init__(self, tag: str = DEFAULT_TAG, log_page: str = DEFAULT_LOG_PAGE, slugify: Slugify = default_slugify):
        self.tag = tag
        self.log_page = log_page
        self.slugify = slugify
        self._re = comment_re(tag)
        self._tagged = re.compile(rf"^\s*<!--\s*{re.escape(tag)}#")  # looks like one of ours, whether or not it parses

    # -- parsing ---------------------------------------------------------

    def parse_line(self, line: str, line_no: int) -> Comment | None:
        m = self._re.match(line)
        if not m:
            return None
        return Comment(
            id=m["id"],
            author=m["author"].strip(),
            date=m["date"],
            text=m["text"],
            line_no=line_no,
            indent=m["indent"],
            resolved=bool(m["resolved"]),
            re=m["re"],
        )

    def heading_anchor(self, line: str) -> tuple[str, str] | None:
        """(title, anchor) if the line is an ATX heading, else None."""
        h = HEADING_RE.match(line)
        if not h:
            return None
        return h["title"], self._anchor_of(h["title"], h["attrs"])

    def _anchor_of(self, title: str, attrs: str | None) -> str:
        m = ATTR_ID_RE.search(attrs or "")
        return m["id"] if m else self.slugify(title)

    def headings(self, lines: list[str], skip: list[bool] | None = None) -> list[Heading]:
        """Every heading outside fences and front matter, ATX or setext, in page order."""
        skip = protected_lines(lines) if skip is None else skip
        out: list[Heading] = []
        for i, raw in enumerate(lines):
            if skip[i]:
                continue
            h = HEADING_RE.match(raw)
            if h:
                out.append(Heading(i, len(h["hashes"]), h["title"], self._anchor_of(h["title"], h["attrs"])))
                continue
            u = SETEXT_RE.match(raw)
            if u and i > 0 and not skip[i - 1] and lines[i - 1].strip() and (i == 1 or not lines[i - 2].strip()):
                prev = lines[i - 1]
                if not HEADING_RE.match(prev) and (out == [] or out[-1].index != i - 1) and not prev.lstrip().startswith(("<!--", "|", "- ", "* ", "+ ")):
                    title = prev.strip()
                    out.append(Heading(i - 1, 1 if u["char"][0] == "=" else 2, title, self.slugify(title)))
        return out

    def locate_heading(self, lines: list[str], anchor: str, level: int | None = None, ordinal: int | None = None) -> int | None:
        """Line index of the heading the page-side button meant, or -1 for the page top, or None.

        The anchor the browser sends is the id MkDocs rendered, which usually equals our slug of
        the raw heading but not always (markup in the title, duplicate headings, a custom slugify).
        The level and ordinal of the clicked heading among headings of that level is the fallback,
        and an h1 at ordinal 0 with no match is the one Material synthesises from the page title.
        """
        hs = self.headings(lines)
        if anchor == "":
            return -1
        same = [h for h in hs if h.anchor == anchor]
        if same and (level is None or any(h.level == level for h in same)):
            return next(h for h in same if level is None or h.level == level).index
        if level is not None and ordinal is not None:
            of_level = [h for h in hs if h.level == level]
            if 0 <= ordinal < len(of_level):
                return of_level[ordinal].index
            if level == 1 and ordinal == 0:
                return -1
        if same:
            return same[0].index
        return None

    def parse_page(self, page: str, text: str) -> list[Thread]:
        """Group the tagged comment lines of one page into threads."""
        threads: list[Thread] = []
        heading, anchor = "", ""
        current: Thread | None = None
        lines = split_lines(text)
        skip = protected_lines(lines)
        by_line = {h.index: h for h in self.headings(lines, skip)}
        for i, raw in enumerate(lines, start=1):
            if skip[i - 1]:
                continue
            h = by_line.get(i - 1)
            if h:
                heading, anchor = h.title, h.anchor
                current = None
                continue
            c = self.parse_line(raw, i)
            if c is None:
                current = None
                continue
            if current is not None and (c.is_reply or c.resolved):
                current.lines.append(c)
                continue
            current = Thread(page=page, anchor=anchor, heading=heading, root=c, lines=[c])
            threads.append(current)
        return threads

    def scan(self, docs_dir: Path) -> list[Thread]:
        threads: list[Thread] = []
        for path in sorted(docs_dir.rglob("*.md")):
            rel = path.relative_to(docs_dir).as_posix()
            if rel == self.log_page:
                continue
            threads.extend(self.parse_page(rel, read_text(path)))
        return threads

    def archived_ids(self, docs_dir: Path) -> set[str]:
        """Every comment id, root or reply, already moved to the comment log page.

        Roots are the ``### ID`` entry headings; replies are the ``- **ID Name date**`` bullets.
        """
        log = docs_dir / self.log_page
        if not log.exists():
            return set()
        entry = re.compile(rf"^(?:###\s+|-\s+\*\*)(?P<id>{ID_RE})\s")
        return {m["id"] for line in split_lines(read_text(log)) if (m := entry.match(line))}

    # -- writing ---------------------------------------------------------

    def format_line(self, c: Comment) -> str:
        head = f"<!-- {self.tag}#{c.id} "
        if c.resolved:
            head += "resolved "
        head += f"{c.author} {c.date}"
        if c.re:
            head += f" re {c.re}"
        return f"{c.indent}{head} | {c.text} -->"

    def insert_root(self, page_text: str, anchor: str, line: str, level: int | None = None, ordinal: int | None = None) -> str:
        """Insert a new root comment at the end of the section whose heading has ``anchor``.

        The comment goes after the section's last non-blank line, before any closing
        horizontal rule, separated by a blank line so it can never land inside a table
        or a list.  An empty anchor means the top of the page, before the first heading.
        ``level`` and ``ordinal`` identify the heading when the anchor does not (see locate_heading).
        """
        lines = split_lines(page_text)
        found = self.locate_heading(lines, anchor, level, ordinal)
        if found is None:
            raise KeyError(f"no heading with anchor {anchor!r}")
        # index of the heading line, or of the last front-matter line, or -1 for the page top
        start = front_matter_end(lines) if found == -1 else found
        if found == -1:
            anchor = ""
        elif not HEADING_RE.match(lines[found]) and found + 1 < len(lines) and SETEXT_RE.match(lines[found + 1]):
            start = found + 1  # setext heading: the underline belongs to it
        end = len(lines)  # index of the next heading, or EOF
        for h in self.headings(lines):
            if h.index > start:
                end = h.index
                break
        last = end - 1
        while last > start and (lines[last].strip() == "" or HR_RE.fullmatch(lines[last])):
            last -= 1
        insert_at = last + 1
        prev_is_comment = last >= 0 and last > start and self.parse_line(lines[last], 0) is not None
        new = self.parse_line(line, 0)
        if prev_is_comment and new is not None and (new.is_reply or new.resolved):
            prev_is_comment = False  # a reply or resolution right under another thread would be read as part of it
        directly_under_heading = last == start and anchor != ""
        block = [line] if directly_under_heading or last < 0 or prev_is_comment else ["", line]
        if end < len(lines) and insert_at == end:
            block = block + [""]
        lines[insert_at:insert_at] = block
        return "\n".join(lines) + "\n"

    @staticmethod
    def append_to_thread(page_text: str, thread: Thread, line: str) -> str:
        lines = split_lines(page_text)
        lines.insert(thread.last_line, line)  # last_line is 1-based: insert after it
        return "\n".join(lines) + "\n"

    @staticmethod
    def delete_thread(page_text: str, thread: Thread) -> str:
        lines = split_lines(page_text)
        del lines[thread.first_line - 1 : thread.last_line]
        return "\n".join(lines) + "\n"

    # -- checks ----------------------------------------------------------

    def check(self, threads: list[Thread], docs_dir: Path) -> list[str]:
        """Human-readable problems: duplicate ids, dangling references, bad placement."""
        problems: list[str] = []
        seen: dict[str, str] = {}
        ids: set[str] = set(index_by_id(threads)) | self.archived_ids(docs_dir)
        for t in threads:
            for c in t.lines:
                where = f"{t.page}:{c.line_no}"
                if c.resolved:
                    if c.id != t.root.id:
                        problems.append(f"{where}: resolution for {c.id} is not under its own root ({t.root.id})")
                    continue
                if c.id in seen:
                    problems.append(f"{where}: duplicate id {c.id} (also at {seen[c.id]})")
                seen[c.id] = where
                if c.re and c.re not in ids:
                    problems.append(f"{where}: reply to unknown id {c.re}")
        for path in sorted(docs_dir.rglob("*.md")):
            rel = path.relative_to(docs_dir).as_posix()
            lines = split_lines(read_text(path))
            skip = protected_lines(lines)
            for i, raw in enumerate(lines):
                if skip[i]:
                    continue
                if self.parse_line(raw, i + 1) is None:
                    if self._tagged.match(raw):
                        problems.append(f"{rel}:{i + 1}: malformed review comment (expected <!-- {self.tag}#XX-1 Name YYYY-MM-DD | text -->)")
                    continue
                above = lines[i - 1].lstrip() if i > 0 else ""
                below = lines[i + 1].lstrip() if i + 1 < len(lines) else ""
                if above.startswith("|") and below.startswith("|"):
                    problems.append(f"{rel}:{i + 1}: comment between table rows will break the table")
        return problems


FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")


def front_matter_end(lines: list[str]) -> int:
    """Index of the closing ``---`` of a YAML front-matter block, or -1 if the page has none."""
    if not lines or lines[0].strip() != "---":
        return -1
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return i
    return -1


def protected_lines(lines: list[str]) -> list[bool]:
    """Which lines are front matter or inside a fenced code block, where headings and comments are just text."""
    out = [False] * len(lines)
    fm = front_matter_end(lines)
    for i in range(fm + 1):
        out[i] = True
    fence: str | None = None
    for i in range(fm + 1, len(lines)):
        m = FENCE_RE.match(lines[i])
        if fence is None:
            if m:
                fence = m["fence"]
                out[i] = True
            continue
        out[i] = True
        if m and m["fence"][0] == fence[0] and len(m["fence"]) >= len(fence) and lines[i].strip() == m["fence"]:
            fence = None
    return out


def index_by_id(threads: list[Thread]) -> dict[str, Thread]:
    """Map every comment id (root or reply) to the thread it belongs to."""
    out: dict[str, Thread] = {}
    for t in threads:
        for c in t.lines:
            if not c.resolved:
                out.setdefault(c.id, t)
    return out


def next_number(threads: list[Thread], initials: str, archived: set[str] = frozenset()) -> int:
    """One past the highest number ``initials`` has used, in live threads or in the comment log."""
    ids = {c.id for t in threads for c in t.lines if not c.resolved} | set(archived)
    n = 0
    for cid in ids:
        ini, num = cid.split("-")
        if ini == initials:
            n = max(n, int(num))
    return n + 1


def clean_text(text: str) -> str:
    """One line, no ``|`` (the header separator) and nothing that could close the comment early."""
    return " ".join(text.split()).replace("|", "/").replace("-->", "-- >")
