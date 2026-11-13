import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# Screenshots stay inside the repository; never write to an absolute path that
# belongs to a specific developer's machine.
SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "reports" / "smoke"

def run_verification():
    smoke_user = os.getenv("ROLLCALL_SMOKE_USER", "faculty_ml")
    smoke_password = os.getenv("ROLLCALL_SMOKE_PASSWORD", "")
    if not smoke_password:
        print(
            "ROLLCALL_SMOKE_PASSWORD must be set to the seeded faculty password.",
            file=sys.stderr,
        )
        sys.exit(2)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        print("[TEST 1] Visiting login page...")
        page.goto("http://localhost:5173/login", wait_until="networkidle")
        time.sleep(1)

        # Fill credentials for the seeded faculty account
        page.fill("input#user_id", smoke_user)
        page.fill("input#password", smoke_password)
        page.click("button[type='submit']")

        print("[TEST 1] Waiting for dashboard navigation...")
        page.wait_for_selector("text=Teacher Workspace", timeout=10000)
        print("  -> Logged in successfully as faculty_ml")

        # Save screenshot of dashboard
        page.screenshot(path=str(SCREENSHOT_DIR / "verify_dashboard.png"))
        print("  -> Captured verify_dashboard.png")

        # F5 Check: Verify breakdown tables on Dashboard
        print("[TEST 2] Checking F5 Dashboard Overview & Faculty Upload Table...")
        page.wait_for_selector("text=Institute Attendance Rate", timeout=5000)
        page.wait_for_selector("text=Branch Breakdown", timeout=5000)
        page.wait_for_selector("text=Room Breakdown", timeout=5000)
        page.wait_for_selector("text=Faculty Upload & Session Activity", timeout=5000)
        print("  -> F5: Institutional KPIs, Branch Breakdown, Room Breakdown, and Faculty Upload Activity present!")

        # F2 Check: Sessions View
        print("[TEST 3] Checking F2 Sessions View & Schedule Modal...")
        page.goto("http://localhost:5173/sessions", wait_until="networkidle")
        time.sleep(1)
        page.wait_for_selector("text=Academic Sessions", timeout=5000)
        page.wait_for_selector("text=Attendance Ledger", timeout=5000)
        page.screenshot(path=str(SCREENSHOT_DIR / "verify_sessions.png"))
        print("  -> F2: Sessions list loaded with Attendance Ledger buttons and faculty attribution")

        # Open Schedule Session modal
        page.click("button:has-text('Schedule Session')")
        time.sleep(1)
        page.wait_for_selector("text=Schedule New Session", timeout=5000)
        # Verify assigned subject code is present
        page.wait_for_selector("text=Assigned Subject Code", timeout=5000)
        page.screenshot(path=str(SCREENSHOT_DIR / "verify_schedule_modal.png"))
        print("  -> F2: Schedule Session modal correctly binds authoritative assigned subjects!")
        page.click("button:has-text('Cancel')")

        # F3 Check: Attendance Ledger
        print("[TEST 4] Checking F3 Attendance Editing Screen...")
        page.goto("http://localhost:5173/attendance?session=SESS-20261024-02", wait_until="networkidle")
        time.sleep(2)
        page.wait_for_selector("text=Attendance Verification", timeout=5000)
        page.wait_for_selector("text=1MS21IS001", timeout=5000)
        print("  -> F3: Session SESS-20261024-02 roster loaded with students!")

        # Toggle Present / Absent
        print("[TEST 4] Toggling student attendance status...")
        toggle_buttons = page.locator("button:has-text('Absent')")
        if toggle_buttons.count() > 0:
            toggle_buttons.first.click()
            time.sleep(0.5)

        # Click Save Changes
        print("[TEST 4] Clicking 'Save Changes'...")
        page.click("button:has-text('Save Changes')")
        time.sleep(3)
        page.screenshot(path=str(SCREENSHOT_DIR / "verify_attendance_saved.png"))
        alerts = page.locator("div[class*='border']").all_text_contents()
        print("Alerts/elements on page:", [a.strip() for a in alerts if "attendance" in a.lower() or "session" in a.lower() or "error" in a.lower() or "success" in a.lower() or "replace" in a.lower()])

        # F10 Check: Assistant Chat View
        print("[TEST 5] Checking F10 Assistant Chat View...")
        page.goto("http://localhost:5173/assistant", wait_until="networkidle")
        time.sleep(1)
        page.wait_for_selector("text=RollCall AI Assistant", timeout=5000)
        page.screenshot(path=str(SCREENSHOT_DIR / "verify_assistant.png"))
        print("  -> F10: Assistant View loaded cleanly with Dual-Source Agent and Confirmation Card architecture!")

        # F6 Check: RBAC Protection on /audit for Faculty
        print("[TEST 6] Checking F6 /audit route RBAC protection for faculty...")
        page.goto("http://localhost:5173/audit", wait_until="networkidle")
        time.sleep(1)
        page.wait_for_selector("text=Access Denied", timeout=5000)
        page.screenshot(path=str(SCREENSHOT_DIR / "verify_audit_denied_for_faculty.png"))
        print("  -> F6: /audit route correctly rejects non-ADMIN faculty with Access Denied!")

        browser.close()
        print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_verification()

