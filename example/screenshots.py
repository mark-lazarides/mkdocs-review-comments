"""Regenerate the README screenshots from the example site.

    pip install mkdocs-material playwright && playwright install chromium
    python example/screenshots.py

Starts ``mkrc serve`` on the example, drives the review build in headless Chromium and writes
PNGs to example/screenshots/. Nothing is saved through the comment box, so the example pages
are left untouched.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "example" / "screenshots"
SITE, API = 8802, 8803
URL = f"http://127.0.0.1:{SITE}/"


def wait_for(port: int, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    sys.exit(f"nothing answered on port {port} within {timeout:.0f}s")


def clip_between(page: Page, top_selector: str, bottom_selector: str, pad: int = 16) -> dict:
    """A clip rectangle spanning from one element's top to another's bottom, across the content column."""
    page.locator(top_selector).scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -120)")
    page.wait_for_timeout(300)
    column = page.locator(".md-content__inner").bounding_box()
    top = page.locator(top_selector).bounding_box()
    bottom = page.locator(bottom_selector).bounding_box()
    y = top["y"] - pad
    return {"x": column["x"] - pad, "y": y, "width": column["width"] + 2 * pad, "height": bottom["y"] + bottom["height"] + pad - y}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1"}
    server = subprocess.Popen(
        [sys.executable, "-m", "mkdocs_review_comments", "-f", "example/mkdocs.yml", "serve", "-a", f"127.0.0.1:{SITE}", "--api-port", str(API)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(SITE)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # A tall viewport so a heading, its table and the thread under it all fit in one frame.
            tall, short = {"width": 1180, "height": 1800}, {"width": 1180, "height": 760}
            page = browser.new_page(viewport=tall, device_scale_factor=2)
            page.goto(URL, wait_until="load")
            page.wait_for_selector(".rc-thread")

            # 1. An open thread with a reply, rendered in place under the table it refers to.
            page.screenshot(path=OUT / "thread.png", clip=clip_between(page, "#operating-modes", "#rc-JB-2 .rc-actions"))

            # 2. A resolved thread renders greyed out and keeps only the Reply button.
            page.screenshot(path=OUT / "resolved.png", clip=clip_between(page, "#scope", "#rc-JB-1 .rc-actions"))

            # 3. Hovering a heading lights up its + button. Measure first: the helper scrolls, which would end the hover.
            clip = clip_between(page, "#alarms", "#alarms", pad=24)
            page.locator("#alarms").hover()
            page.wait_for_timeout(200)
            page.screenshot(path=OUT / "add-button.png", clip=clip)

            # 4. The comment box, filled in but not saved: a whole frame, so the box shows in context.
            page.set_viewport_size(short)
            page.locator("#alarms").scroll_into_view_if_needed()
            page.evaluate("window.scrollBy(0, -100)")
            page.locator("#alarms .rc-btn").click()
            page.fill(".rc-panel .rc-author", "Josephine Bloggs")
            page.fill(".rc-panel .rc-initials", "JB")
            page.fill(".rc-panel .rc-text", "Runtime-exceeded should be Medium, not Low: it is how we catch a stuck duty pump.")
            page.wait_for_timeout(200)
            page.screenshot(path=OUT / "comment-box.png")
            page.locator(".rc-panel .rc-cancel").click()
            page.set_viewport_size(tall)

            # 5. A reply from another page links back across pages.
            page.goto(URL + "electrical/panel-schedule/", wait_until="load")
            page.wait_for_selector(".rc-thread")
            page.screenshot(path=OUT / "cross-page.png", clip=clip_between(page, "#protection-relays", "#rc-ML-3 .rc-actions"))

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
    for f in sorted(OUT.glob("*.png")):
        print(f.relative_to(ROOT), f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
