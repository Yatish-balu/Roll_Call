"""Temporary crash probe: poll the backend while driving the UI."""
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
API = "http://127.0.0.1:8000/health"
state = {"health": [], "stop": False, "pageerrors": [], "console": [], "bad_pages": []}


def poll():
    while not state["stop"]:
        started = time.time()
        try:
            with urllib.request.urlopen(API, timeout=8) as r:
                body = r.read(80).decode(errors="replace")
            state["health"].append([round(started, 1), r.status, body])
        except Exception as exc:  # noqa: BLE001
            state["health"].append([round(started, 1), "DOWN", f"{type(exc).__name__}: {exc}"])
        time.sleep(4)


def login(page):
    page.goto(BASE + "/login", wait_until="networkidle")
    page.fill("#user_id", "faculty_ds")
    page.fill("#password", "FacultyPass_DIST_2026!")
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"5173/$"), timeout=30000)
    page.wait_for_timeout(2000)


def note_page(page, label):
    body = page.inner_text("body") if page.locator("body").count() else ""
    if len(body.strip()) < 120:
        state["bad_pages"].append({"label": label, "url": page.url, "text": body[:200]})


def main():
    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("pageerror", lambda e: state["pageerrors"].append(f"{time.time():.0f} {e}"))
            page.on("console", lambda m: state["console"].append(f"{time.time():.0f} [{m.type}] {m.text[:200]}")
                    if m.type == "error" else None)

            login(page)
            for route in ["/", "/students", "/attendance", "/timetable", "/calendar", "/sessions",
                          "/defaulters", "/reports", "/assistant", "/settings", "/profile"]:
                page.goto(BASE + route, wait_until="networkidle")
                page.wait_for_timeout(4000)
                note_page(page, route)
                state.setdefault("route_len", {})[route] = len(page.inner_text("body"))

            # attendance save
            page.goto(BASE + "/attendance", wait_until="networkidle")
            page.wait_for_timeout(6000)
            page.locator("tbody tr").filter(has_text="1MS21ME026").first.get_by_role("button", name="Absent").click()
            page.wait_for_timeout(300)
            page.get_by_role("button", name="Save Changes").click()
            page.wait_for_timeout(8000)
            note_page(page, "attendance-save")
            page.locator("tbody tr").filter(has_text="1MS21ME026").first.get_by_role("button", name="Present").click()
            page.wait_for_timeout(300)
            page.get_by_role("button", name="Save Changes").click()
            page.wait_for_timeout(8000)

            # csv upload
            page.goto(BASE + "/assistant", wait_until="networkidle")
            page.wait_for_timeout(4000)
            page.set_input_files("input[type=file]", "data/demo/clean_demo.csv")
            page.wait_for_timeout(20000)
            note_page(page, "csv-upload")

            # photo upload (heaviest path: vision + OCR fallback)
            page.set_input_files("input[type=file]", "data/photos/sheet_clean.jpg")
            page.wait_for_timeout(70000)
            note_page(page, "photo-upload")
            page.screenshot(path="crash_probe_final.png", full_page=False)

            # reload after the heavy flow
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(6000)
            note_page(page, "after-photo-reload")
            browser.close()
    finally:
        state["stop"] = True
        thread.join(timeout=10)


main()
down = [h for h in state["health"] if h[1] == "DOWN"]
summary = {
    "health_samples": len(state["health"]),
    "down_samples": down[:10],
    "down_count": len(down),
    "pageerrors": state["pageerrors"][:10],
    "console_errors": state["console"][:10],
    "bad_pages": state["bad_pages"],
    "route_len": state.get("route_len"),
}
Path("crash_probe.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False)[:2000])
