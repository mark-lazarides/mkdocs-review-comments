"""The MkDocs plugin, exercised through real ``mkdocs build`` runs on a tiny site."""

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PAGE = textwrap.dedent("""\
    # Page

    para

    <!-- RC#AA-1 Ann Other 2026-10-13 | root with a [link](other.md) -->
    <!-- RC#BB-1 Bob 2026-10-13 re AA-1 | reply -->
    <!-- RC#AA-1 resolved Bob 2026-10-14 | done -->

    !!! note
        inside admonition

        <!-- RC#CC-1 Cy 2026-10-13 | indented thread re [DD-1](other.md#rc-DD-1) -->

    ```markdown
    <!-- RC#ZZ-9 Doc 2026-01-01 | grammar example in a code block -->
    ```
    """)

OTHER = "# Other\n\n<!-- RC#DD-1 Dee 2026-10-13 | on the other page -->\n<!-- RC#EE-1 Ed 2026-10-13 re CC-1 | cross-page reply -->\n"


def build(tmp_path: Path, *, review: bool, theme: str = "mkdocs", extensions: list[str] = (), env: dict[str, str] | None = None) -> dict[str, str]:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.md").write_text(PAGE, encoding="utf-8")
    (docs / "other.md").write_text(OTHER, encoding="utf-8")
    cfg = f"site_name: Site\ntheme:\n  name: {theme}\nplugins:\n  - review-comments:\n      review: {str(review).lower()}\n"
    cfg += "markdown_extensions:\n" + "".join(f"  - {e}\n" for e in ["admonition", *extensions])
    (tmp_path / "mkdocs.yml").write_text(cfg, encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "mkdocs", "build", "-q"], cwd=tmp_path, capture_output=True, text=True, env={**os.environ, **(env or {})})
    assert r.returncode == 0, r.stderr
    out = {}
    for name, rel in (("index", "index.html"), ("other", "other/index.html")):
        html = (tmp_path / "site" / rel).read_text(encoding="utf-8")
        out[name] = re.sub(r"\s+", " ", html[html.find("<h1") :])
    return out


def test_normal_build_strips_every_comment_and_keeps_code_samples(tmp_path):
    html = build(tmp_path, review=False)["index"]
    assert "RC#" not in html.replace("RC#ZZ-9", "")  # only the fenced sample remains
    assert "grammar example in a code block" in html
    assert "rc-thread" not in html and "Ann Other" not in html


@pytest.mark.parametrize("extensions", [[], ["attr_list", "md_in_html"]])
def test_review_build_renders_threads_without_extra_extensions(tmp_path, extensions):
    html = build(tmp_path, review=True, extensions=extensions)["index"]
    assert "RC#" not in html.replace("RC#ZZ-9", "")
    assert "**" not in html, "markdown inside the thread was not rendered"
    assert html.count('class="rc-thread') == 2
    assert 'id="rc-AA-1"' in html and "rc-resolved" in html
    assert "<strong>Ann Other</strong>" in html
    assert "<p><p" not in html and "<p><div" not in html, "nested block elements"
    assert 'href="other/"' in html, "link in the comment text should be rewritten like any markdown link"


def test_review_build_links_replies_across_pages(tmp_path):
    out = build(tmp_path, review=True)
    assert 'href="other/#rc-DD-1">DD-1</a>' in out["index"]
    assert 'href="#rc-AA-1">AA-1</a>' in out["index"]
    assert 'href="../#rc-CC-1">CC-1</a>' in out["other"]


def test_review_build_marks_the_site_name(tmp_path):
    html = (build(tmp_path, review=True), (tmp_path / "site" / "index.html").read_text(encoding="utf-8"))[1]
    assert "Site (review build)" in html


def test_rc_serve_environment_selects_review_mode_and_api_url(tmp_path):
    html = build(tmp_path, review=False, env={"RC_REVIEW": "1", "RC_API_URL": "http://0.0.0.0:9911"})["index"]
    assert 'class="rc-thread' in html
    assert '"api": "http://0.0.0.0:9911"' in html


def test_api_url_default_comes_from_the_plugin_option(tmp_path):
    html = build(tmp_path, review=True, env={"RC_API_URL": ""})["index"]
    assert '"api": "http://127.0.0.1:8803"' in html
