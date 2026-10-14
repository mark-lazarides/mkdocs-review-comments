"""MkDocs plugin: strip review comments on a normal build, render them on a review build.

    plugins:
      - review-comments:
          tag: RC                       # the tag inside <!-- RC#... -->
          log_page: reviews/comment-log.md
          review: false                 # true renders threads in place
          api_url: http://127.0.0.1:8803   # where the page-side comment box posts

Review mode is on when any of these is true: the ``review`` option, the
environment variable ``RC_REVIEW=1`` (what ``mkrc serve`` sets), or
``extra.review_comments: true`` in the config (handy with an INHERIT file).
``RC_API_URL``, also set by ``mkrc serve``, overrides ``api_url`` so the
buttons always post to the API that is actually running.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mkdocs.config import config_options as c
from mkdocs.config.base import Config
from mkdocs.plugins import BasePlugin

from .core import DEFAULT_LOG_PAGE, DEFAULT_TAG, Grammar, Thread, default_slugify, index_by_id, split_lines

ASSETS = Path(__file__).resolve().with_name("assets")


class ReviewCommentsConfig(Config):
    tag = c.Type(str, default=DEFAULT_TAG)
    log_page = c.Type(str, default=DEFAULT_LOG_PAGE)
    review = c.Type(bool, default=False)
    api_url = c.Type(str, default="http://127.0.0.1:8803")
    site_name_suffix = c.Type(str, default=" (review build)")


class ReviewCommentsPlugin(BasePlugin[ReviewCommentsConfig]):
    def __init__(self) -> None:
        self.grammar = Grammar()
        self.review = False
        self.id_to_page: dict[str, str] = {}
        self.archived: set[str] = set()

    # -- lifecycle -------------------------------------------------------

    def on_config(self, config):
        by_env = os.environ.get("RC_REVIEW", "").strip().lower() in {"1", "true", "yes", "on"}
        by_extra = bool((config.extra or {}).get("review_comments"))
        self.review = self.config.review or by_env or by_extra
        if self.review and "attr_list" not in config.markdown_extensions:
            config.markdown_extensions.append("attr_list")  # the rendered threads carry their class and anchor this way
        slugify = default_slugify
        toc = (config.mdx_configs or {}).get("toc") or {}
        if callable(toc.get("slugify")):
            fn = toc["slugify"]
            sep = toc.get("separator", "-")
            slugify = lambda title: fn(title, sep)  # noqa: E731
        self.grammar = Grammar(tag=self.config.tag, log_page=self.config.log_page, slugify=slugify)
        suffix = self.config.site_name_suffix
        if self.review and suffix and not config.site_name.endswith(suffix):
            config.site_name = config.site_name + suffix
        return config

    def on_files(self, files, config):
        self.id_to_page.clear()
        self.archived.clear()
        if not self.review:
            return files
        docs = Path(config.docs_dir)
        for cid, t in index_by_id(self.grammar.scan(docs)).items():
            self.id_to_page[cid] = t.page
        self.archived.update(self.grammar.archived_ids(docs))
        return files

    def on_page_markdown(self, markdown, page, config, files):
        src = page.file.src_uri
        threads = self.grammar.parse_page(src, markdown)
        if not threads:
            return markdown
        lines = split_lines(markdown)
        for t in sorted(threads, key=lambda t: t.first_line, reverse=True):
            start, end = t.first_line - 1, t.last_line
            if self.review:
                lines[start:end] = [""] + self._render(t, src) + [""]
            else:
                del lines[start:end]
        return "\n".join(lines) + "\n"

    def on_post_page(self, output, page, config):
        """Review build only: inline the stylesheet, tell the page which source file it is, add the buttons."""
        if not self.review:
            return output
        css = (ASSETS / "review.css").read_text(encoding="utf-8")
        js = (ASSETS / "review.js").read_text(encoding="utf-8")
        api = os.environ.get("RC_API_URL") or self.config.api_url  # mkrc serve sets the variable to match --api-port
        cfg = json.dumps({"page": page.file.src_uri, "api": api})
        head = f"<style>\n{css}\n</style>\n"
        body = f"<script>window.RC = {cfg};</script>\n<script>\n{js}\n</script>\n"
        output = output.replace("</head>", head + "</head>", 1)
        return output.replace("</body>", body + "</body>", 1)

    # -- rendering -------------------------------------------------------

    def _link(self, cid: str, from_page: str) -> str:
        target = self.id_to_page.get(cid)
        anchor = f"rc-{cid}"
        if target is None:
            if cid in self.archived:
                target, anchor = self.grammar.log_page, cid.lower()
            else:
                return f"`{cid}`"
        if target == from_page:
            return f"[{cid}](#{anchor})"
        rel = os.path.relpath(target, os.path.dirname(from_page) or ".").replace(os.sep, "/")
        return f"[{cid}]({rel}#{anchor})"

    def _render(self, t: Thread, page: str) -> list[str]:
        """One markdown paragraph per thread, classed and anchored with attr_list.

        A paragraph, rather than a raw ``<div markdown="1">`` block, renders the same whether the
        thread sits at the top level or indented inside an admonition, and needs no ``md_in_html``.
        Each comment is a ``<span class="rc-line">`` ended by ``<br>``; the CSS makes them blocks.
        """
        ind = t.root.indent
        out: list[str] = []
        for c in t.lines:
            if c.resolved:
                body = f'<span class="rc-line rc-res">**Resolved** by {c.author} {c.date}: {c.text}</span>'
            else:
                ref = f" re {self._link(c.re, page)}" if c.re else ""
                kind = "rc-reply" if c.is_reply else "rc-root"
                body = f'<span class="rc-line {kind}"><span class="rc-id">{c.id}</span> **{c.author}** {c.date}{ref}: {c.text}</span>'
            out.append(f"{ind}{body}<br>")
        cls = ".rc-thread .rc-resolved" if t.is_resolved else ".rc-thread"
        out.append(f"{ind}{{ {cls} #rc-{t.id} }}")
        return out
