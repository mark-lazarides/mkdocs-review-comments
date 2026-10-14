# mkdocs-review-comments

Review comments that live **in the markdown**, as tagged HTML comments. They travel with the page, show up in `git diff`, need no server to store them, and are invisible in the published site. A review build renders them in place with reply and resolve buttons that write back into the source.

```markdown
<!-- RC#DD-14 Josephine Bloggs 2026-10-14 | The figure came from the pump vendor. Cite the close-out. -->
<!-- RC#ML-7 Mark 2026-10-15 re DD-14 | Agreed. Cited Item 12 and raised TQ-061. -->
<!-- RC#DD-14 resolved Mark 2026-10-15 | fixed in TQ-061 -->
```

## Install

```
pip install git+https://<your host>/mkdocs-review-comments.git
```

or, for development, `pip install -e .` from a clone. Then in `mkdocs.yml`:

```yaml
plugins:
  - search
  - review-comments
```

Options, all optional:

```yaml
  - review-comments:
      tag: RC                          # the tag inside <!-- RC#... -->
      log_page: reviews/comment-log.md # where `rc archive` moves resolved threads
      review: false                    # true renders threads in place
      api_url: http://127.0.0.1:8803   # where the page-side comment box posts
```

## The grammar

One comment per line, on its own line after the paragraph or table it refers to.

- **Id.** The author's initials and the author's own running number (`ML-7`). Two people commenting on separate branches never collide.
- **Thread.** A root comment plus the comment lines directly beneath it: replies and the resolution line. A reply carries its own id and `re <id>`. `re` may point at a comment on another page, in which case the reply is a thread of its own with a link back.
- **Resolve.** A line that reuses the root id with the word `resolved`. The thread stays in the page until it is archived.
- **Names** may contain spaces. The text may not contain `|`, which separates the header from the text.
- **Placement.** Never between two table rows. Inside an admonition, keep the indent. The page-side comment box and `rc` always place comments safely; these rules are for hand-written ones.

## Two builds

A normal build (`mkdocs build`, `mkdocs serve`) strips every tagged comment, so the issued site carries nothing.

A review build renders each thread in place as a note with an anchor (`#rc-DD-14`), so a comment has a URL and every `re` is a link, across pages and into the log once a thread is archived. Resolved threads render greyed. Review mode is on when any of these holds:

- the plugin option `review: true`;
- the environment variable `RC_REVIEW=1`, which `rc serve` sets;
- `extra.review_comments: true` in the config, convenient in an `INHERIT` file:

```yaml
# mkdocs.review.yml
INHERIT: mkdocs.yml
extra:
    review_comments: true
```

The site name gains " (review build)" so the two are easy to tell apart.

## Commenting from the page

```
rc serve
```

serves the review build (default `127.0.0.1:8802`) and a small comment API (`8803`) in one process. Every heading gets a `+` button that adds a comment at the end of its section; every thread gets Reply and Resolve. Each save writes the tagged line into the markdown and the live reload rebuilds the page. Name and initials are remembered in the browser. Ctrl-C stops both.

`rc serve` refuses to start if either port is already in use, naming the port, because Windows will otherwise let two copies bind the same port and answer at random.

## The command line

```
rc list            # open threads by page
rc list --all      # including resolved
rc check           # duplicate ids, replies to unknown ids, comments that would break a table
rc reply   DD-14 "text" --by "Mark Lazarides" --as ML
rc resolve DD-14 "text" --by "Mark Lazarides"
rc delete  DD-14   # remove a thread outright (junk or test comments)
rc archive         # move resolved threads to the comment log page
rc serve [-a IP:PORT] [--api-port N]
```

`rc` reads `mkdocs.yml` in the current folder for the docs directory and the plugin options (`-f` for another config). With no MkDocs config at all, `--docs <folder>` scans a plain folder of markdown; the grammar and the CLI do not depend on MkDocs.

`rc check` is cheap and worth running in CI.

## Notes

- With click 8.2, `mkdocs serve` silently loses its live-reload default and never rebuilds on file changes. `rc serve` forces it on. If you run `mkdocs serve` by hand, pass `--livereload`.
- The rendered notes use Material for MkDocs' CSS variables where present and plain colours otherwise, so other themes work, just less tidily.
- Python 3.10 or later.

## Development

```
pip install -e .[test]
pytest
```
