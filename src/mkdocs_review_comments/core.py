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
  ``rc archive`` later moves resolved threads to the comment log page.
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
HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.*?)(?:\s*\{\s*#(?P<anchor>[^}\s]+)\s*\})?\s*$")
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


class Grammar:
    """The tag and page conventions, shared by the plugin and the CLI."""

    def __init__(self, tag: str = DEFAULT_TAG, log_page: str = DEFAULT_LOG_PAGE, slugify: Slugify = default_slugify):
        self.tag = tag
        self.log_page = log_page
        self.slugify = slugify
        self._re = comment_re(tag)

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
        """(title, anchor) if the line is a heading, else None."""
        h = HEADING_RE.match(line)
        if not h:
            return None
        return h["title"], (h["anchor"] or self.slugify(h["title"]))

    def parse_page(self, page: str, text: str) -> list[Thread]:
        """Group the tagged comment lines of one page into threads."""
        threads: list[Thread] = []
        heading, anchor = "", ""
        current: Thread | None = None
        for i, raw in enumerate(text.splitlines(), start=1):
            h = self.heading_anchor(raw)
            if h:
                heading, anchor = h
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
        """Ids of threads already moved to the comment log page."""
        log = docs_dir / self.log_page
        if not log.exists():
            return set()
        entry = re.compile(rf"^###\s+(?P<id>{ID_RE})\s")
        return {m["id"] for line in read_text(log).splitlines() if (m := entry.match(line))}

    # -- writing ---------------------------------------------------------

    def format_line(self, c: Comment) -> str:
        head = f"<!-- {self.tag}#{c.id} "
        if c.resolved:
            head += "resolved "
        head += f"{c.author} {c.date}"
        if c.re:
            head += f" re {c.re}"
        return f"{c.indent}{head} | {c.text} -->"

    def insert_root(self, page_text: str, anchor: str, line: str) -> str:
        """Insert a new root comment at the end of the section whose heading has ``anchor``.

        The comment goes after the section's last non-blank line, before any closing
        horizontal rule, separated by a blank line so it can never land inside a table
        or a list.  An empty anchor means the top of the page, before the first heading.
        """
        lines = page_text.splitlines()
        start = None  # index of the heading line, or -1 for the page top
        if anchor == "":
            start = -1
        else:
            for i, raw in enumerate(lines):
                h = self.heading_anchor(raw)
                if h and h[1] == anchor:
                    start = i
                    break
        if start is None:
            raise KeyError(f"no heading with anchor {anchor!r}")
        end = len(lines)  # index of the next heading, or EOF
        for j in range(start + 1, len(lines)):
            if HEADING_RE.match(lines[j]):
                end = j
                break
        last = end - 1
        while last > start and (lines[last].strip() == "" or HR_RE.fullmatch(lines[last])):
            last -= 1
        insert_at = last + 1
        prev_is_comment = last >= 0 and last > start and self.parse_line(lines[last], 0) is not None
        block = [line] if last == start or prev_is_comment else ["", line]
        if end < len(lines) and insert_at == end:
            block = block + [""]
        lines[insert_at:insert_at] = block
        return "\n".join(lines) + "\n"

    @staticmethod
    def append_to_thread(page_text: str, thread: Thread, line: str) -> str:
        lines = page_text.splitlines()
        lines.insert(thread.last_line, line)  # last_line is 1-based: insert after it
        return "\n".join(lines) + "\n"

    @staticmethod
    def delete_thread(page_text: str, thread: Thread) -> str:
        lines = page_text.splitlines()
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
            lines = read_text(path).splitlines()
            for i, raw in enumerate(lines):
                if self.parse_line(raw, i + 1) is None:
                    continue
                above = lines[i - 1].lstrip() if i > 0 else ""
                below = lines[i + 1].lstrip() if i + 1 < len(lines) else ""
                if above.startswith("|") and below.startswith("|"):
                    problems.append(f"{rel}:{i + 1}: comment between table rows will break the table")
        return problems


def index_by_id(threads: list[Thread]) -> dict[str, Thread]:
    """Map every comment id (root or reply) to the thread it belongs to."""
    out: dict[str, Thread] = {}
    for t in threads:
        for c in t.lines:
            if not c.resolved:
                out.setdefault(c.id, t)
    return out


def next_number(threads: list[Thread], initials: str) -> int:
    n = 0
    for t in threads:
        for c in t.lines:
            if c.resolved:
                continue
            ini, num = c.id.split("-")
            if ini == initials:
                n = max(n, int(num))
    return n + 1


def clean_text(text: str) -> str:
    """One line, no ``|`` (the header separator) and nothing that could close the comment early."""
    return " ".join(text.split()).replace("|", "/").replace("-->", "-- >")
