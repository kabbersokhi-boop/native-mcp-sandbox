#!/usr/bin/env python3
"""Verify the static evidence viewer and optionally record a real replay walkthrough."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def check_site(output: Path, record: bool) -> None:
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT / "site")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_port}/"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1360, "height": 960})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(address)
            expect(page.locator("#outcome")).to_have_text("recovery-observed")
            page.screenshot(path=str(output / "desktop.png"), full_page=True)
            page.locator('[data-scenario="inconclusive"]').click()
            expect(page.locator("#outcome")).to_have_text("inconclusive")
            assert "search is incomplete" in page.locator("#unresolved").inner_text()
            page.locator('[data-scenario="hostile"]').focus()
            page.keyboard.press("Enter")
            expect(page.locator("#outcome")).to_have_text("boundary-held")
            assert page.locator("#rejections .rejection").count() == 2
            page.locator('[data-evidence="e1"]').click()
            assert "<img" in page.locator("#evidence-detail").inner_text()
            assert page.locator("#evidence-detail img").count() == 0
            page.locator('[data-evidence="e5"]').click()
            assert "invalid_relative_path" in page.locator("#evidence-detail").inner_text()
            page.locator(".control-trace summary").click()
            assert page.locator("#trace li").count() > 32
            page.locator("#investigation").screenshot(path=str(output / "hostile-trace.png"))
            page.set_viewport_size({"width": 375, "height": 812})
            page.emulate_media(reduced_motion="reduce")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.evaluate("getComputedStyle(document.documentElement).scrollBehavior") == "auto"
            page.screenshot(path=str(output / "mobile.png"), full_page=True)
            awaitable_route = lambda route: route.fulfill(status=200, content_type="application/json", body="x" * (128 * 1024 + 1))
            page.route("**/data/recovered/report.json", awaitable_route)
            page.locator('[data-scenario="recovered"]').click()
            expect(page.locator("#load-status")).to_contain_text("byte bound")
            assert not errors, errors
            context.close()
            if record:
                preview = browser.new_page(viewport={"width": 1280, "height": 640})
                preview.goto(address + "assets/social-preview.svg")
                preview.screenshot(path=str(ROOT / "site/assets/social-preview.png"))
                preview.close()
                recording = browser.new_context(viewport={"width": 1280, "height": 800},
                    record_video_dir=str(output / "video"), record_video_size={"width": 1280, "height": 800})
                tour = recording.new_page()
                tour.goto(address)
                expect(tour.locator("#outcome")).to_have_text("recovery-observed")
                tour.wait_for_timeout(2500)
                tour.locator("#investigation").scroll_into_view_if_needed()
                tour.wait_for_timeout(2500)
                tour.locator('[data-scenario="inconclusive"]').click()
                tour.wait_for_timeout(2500)
                tour.locator('[data-scenario="hostile"]').click()
                tour.wait_for_timeout(2500)
                tour.locator('[data-evidence="e5"]').click()
                tour.wait_for_timeout(2500)
                tour.locator(".control-trace summary").click()
                tour.wait_for_timeout(2000)
                tour.locator("#measurements").scroll_into_view_if_needed()
                tour.wait_for_timeout(2500)
                video = tour.video
                recording.close()
                shutil.copyfile(video.path(), ROOT / "site/assets/walkthrough.webm")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    (output / "verification.json").write_text(json.dumps({"passed": True,
        "checks": ["three scenarios", "keyboard scenario activation", "native denial reference",
                   "hostile HTML rendered as text", "bounded download rejection", "375px layout",
                   "reduced motion", "no JavaScript exceptions"], "recorded": record}, indent=2) + "\n")
    print("Browser verification passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "build/site-verification")
    parser.add_argument("--record", action="store_true")
    arguments = parser.parse_args()
    check_site(arguments.output, arguments.record)
