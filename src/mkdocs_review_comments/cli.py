"""``rc``: the command line for review comments kept in the markdown.

    rc list [--all]
    rc check
    rc reply   <id> "text" --by "Mark Lazarides" --as ML
    rc resolve <id> "text" --by "Mark Lazarides"
    rc delete  <id>
    rc archive
    rc serve [-a 127.0.0.1:8802] [--api-port 8803]

The docs directory, tag and log page come from mkdocs.yml (``-f`` to point at
another config).  Without a config, ``--docs`` names the folder to scan.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from .core import DEFAULT_LOG_PAGE, DEFAULT_TAG, Comment, Grammar, SourceFile, Thread, clean_text, index_by_id, next_number, split_lines


class Site:
    """Where the docs are and how the comments are tagged, resolved from the MkDocs config when there is one."""

    def __init__(self, config_file: str | None, docs: str | None):
        self.config_file = config_file
        self.docs = Path(docs) if docs else None
        self.grammar = Grammar()
        if self.docs is None:
            cfg = config_file or ("mkdocs.yml" if os.path.exists("mkdocs.yml") else None)
            if cfg is None:
                sys.exit("no mkdocs.yml here: pass -f <config> or --docs <folder>")
            from mkdocs.config import load_config

            config = load_config(cfg)
            self.config_file = cfg
            self.docs = Path(config.docs_dir)
            plugin = config.plugins.get("review-comments")
            if plugin is not None:
                self.grammar = Grammar(tag=plugin.config.tag, log_page=plugin.config.log_page)
        self.log = self.docs / self.grammar.log_page

    def source(self, page: str) -> SourceFile:
        return SourceFile.read(self.docs / page)

    def threads(self) -> list[Thread]:
        return self.grammar.scan(self.docs)

    def find(self, cid: str) -> Thread:
        t = index_by_id(self.threads()).get(cid)
        if t is None:
            sys.exit(f"no comment with id {cid}")
        return t


# -- commands --------------------------------------------------------------


def cmd_list(site: Site, args) -> None:
    threads = site.threads()
    for t in threads:
        if t.is_resolved and not args.all:
            continue
        state = "resolved" if t.is_resolved else "open"
        print(f"{t.id}  [{state}]  {t.page}#{t.anchor}  ({t.heading})")
        for c in t.lines:
            tag = "resolved by" if c.resolved else ("reply" if c.is_reply else "")
            ref = f" re {c.re}" if c.re else ""
            print(f"    {tag:11s} {c.author} {c.date}{ref}: {c.text}")
    open_n = sum(1 for t in threads if not t.is_resolved)
    print(f"\n{open_n} open, {len(threads) - open_n} resolved")


def cmd_check(site: Site, args) -> None:
    threads = site.threads()
    problems = site.grammar.check(threads, site.docs)
    for p in problems:
        print(p)
    print(f"{len(threads)} threads, {len(problems)} problems")
    sys.exit(1 if problems else 0)


def cmd_reply(site: Site, args) -> None:
    threads = site.threads()
    t = site.find(args.id)
    initials = args.initials.upper()
    cid = f"{initials}-{next_number(threads, initials, site.grammar.archived_ids(site.docs))}"
    c = Comment(id=cid, author=clean_text(args.by), date=args.date, text=clean_text(args.text), line_no=0, indent=t.root.indent, re=args.id)
    src = site.source(t.page)
    src.write(site.grammar.append_to_thread(src.text, t, site.grammar.format_line(c)))
    print(f"{cid} added to {t.page}:{t.last_line + 1}")


def cmd_resolve(site: Site, args) -> None:
    t = site.find(args.id)
    if t.is_resolved:
        sys.exit(f"{t.id} is already resolved")
    c = Comment(id=t.id, author=clean_text(args.by), date=args.date, text=clean_text(args.text), line_no=0, indent=t.root.indent, resolved=True)
    src = site.source(t.page)
    src.write(site.grammar.append_to_thread(src.text, t, site.grammar.format_line(c)))
    print(f"{t.id} resolved in {t.page}")


def cmd_delete(site: Site, args) -> None:
    t = site.find(args.id)
    if t.id != args.id:
        sys.exit(f"{args.id} is a reply inside thread {t.id}; delete the thread by its root id")
    src = site.source(t.page)
    src.write(site.grammar.delete_thread(src.text, t))
    print(f"deleted {t.id} ({len(t.lines)} line(s)) from {t.page}")


def _log_entry(site: Site, t: Thread) -> list[str]:
    res = t.resolution
    rel = os.path.relpath(t.page, os.path.dirname(site.grammar.log_page) or ".").replace(os.sep, "/")
    out = [f"### {t.id} — [{t.page}]({rel}#{t.anchor}) {{ #{t.id.lower()} }}", ""]
    out.append(f"*{t.heading}* · resolved by {res.author} on {res.date}" if res else f"*{t.heading}*")
    out.append("")
    for c in t.lines:
        if c.resolved:
            out.append(f"- **Resolved, {c.author} {c.date}:** {c.text}")
        elif c.is_reply:
            out.append(f"- **{c.id} {c.author} {c.date}** (re {c.re}): {c.text}")
        else:
            out.append(f"- **{c.id} {c.author} {c.date}:** {c.text}")
    out.append("")
    return out


def cmd_archive(site: Site, args) -> None:
    threads = [t for t in site.threads() if t.is_resolved]
    if not threads:
        print("nothing to archive")
        return
    if site.log.exists():
        log_src = SourceFile.read(site.log)
        log = split_lines(log_src.text.rstrip("\n"))
    else:
        site.log.parent.mkdir(parents=True, exist_ok=True)
        log_src = SourceFile(site.log, "")
        log = ["# Comment Log", "", "Resolved review-comment threads, moved here from the pages by `rc archive`. Newest first.", ""]
    insert_at = len(log)
    for i, line in enumerate(log):  # after the intro paragraph: newest first
        if i > 0 and line.strip() == "" and not log[i - 1].startswith("#") and log[i - 1].strip():
            insert_at = i + 1
            break
    entries: list[str] = []
    by_page: dict[str, list[Thread]] = {}
    for t in threads:
        by_page.setdefault(t.page, []).append(t)
    for page, ts in by_page.items():
        src = site.source(page)
        text = src.text
        for t in sorted(ts, key=lambda t: t.first_line, reverse=True):  # bottom up keeps line numbers valid
            text = site.grammar.delete_thread(text, t)
            entries = _log_entry(site, t) + entries
        src.write(text)
    log[insert_at:insert_at] = entries
    log_src.write("\n".join(log) + "\n")
    print(f"archived {len(threads)} thread(s) to {site.grammar.log_page}")


def cmd_serve(site: Site, args) -> None:
    from .serve import serve

    host, _, port = args.dev_addr.partition(":")
    serve(site.config_file, host or "127.0.0.1", int(port or 8802), args.api_port, site.docs, site.grammar)


# -- entry point -----------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-f", "--config-file", help="MkDocs config (default mkdocs.yml)")
    ap.add_argument("--docs", help="docs folder, when there is no MkDocs config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    today = dt.date.today().isoformat()

    p = sub.add_parser("list", help="open threads (or all with --all)")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("check", help="duplicate ids, dangling replies, bad placement")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("reply", help="append a reply to a thread")
    p.add_argument("id")
    p.add_argument("text")
    p.add_argument("--by", required=True, help="author name as it should appear")
    p.add_argument("--as", dest="initials", required=True, help="author initials used in ids, e.g. ML")
    p.add_argument("--date", default=today)
    p.set_defaults(func=cmd_reply)
    p = sub.add_parser("resolve", help="append a resolution line to a thread")
    p.add_argument("id")
    p.add_argument("text")
    p.add_argument("--by", required=True)
    p.add_argument("--date", default=today)
    p.set_defaults(func=cmd_resolve)
    p = sub.add_parser("delete", help="remove a thread outright (junk or test comments)")
    p.add_argument("id")
    p.set_defaults(func=cmd_delete)
    p = sub.add_parser("archive", help="move resolved threads to the comment log page")
    p.set_defaults(func=cmd_archive)
    p = sub.add_parser("serve", help="serve the review build with the page-side comment box")
    p.add_argument("-a", "--dev-addr", default="127.0.0.1:8802", metavar="IP:PORT")
    p.add_argument("--api-port", type=int, default=8803)
    p.set_defaults(func=cmd_serve)

    args = ap.parse_args(argv)
    site = Site(args.config_file, args.docs)
    args.func(site, args)


if __name__ == "__main__":
    main()
