"""Drive the review screen through the three demo cases and record it.

Needs the local stack with fresh cases: Odoo up, `trimatch process data/synthetic/e2e/*_clean.pdf
--extractor gemini` run, `trimatch serve` on 127.0.0.1:8000. It makes real changes: two draft
bills in Odoo and three closed review cases (replay: odoo/reset_bills.py + `trimatch review
clear --yes`).

    uv run --project backend python scripts/record_review_demo.py

Writes docs/img/review-*.png (2x) and docs/img/review-demo.gif (needs ffmpeg).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from playwright.sync_api import Page, expect, sync_playwright

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "img"
W, H = 1440, 900


def case_ids() -> dict[str, int]:
    cases = httpx.get(f"{BASE}/api/reviews").json()
    return {c["po_ref"]: c["id"] for c in cases}


def field(page: Page, path: str):
    return page.locator(f'[id="f-{path}"]')


def shot(page: Page, name: str) -> None:
    page.screenshot(path=IMG / f"review-{name}.png")


def pause(page: Page, ms: int = 900) -> None:
    page.wait_for_timeout(ms)


def run(page: Page, ids: dict[str, int]) -> None:
    page.goto(BASE)
    expect(page.get_by_role("link", name="FA-DA-2026-0162")).to_be_visible()
    pause(page, 1500)
    shot(page, "queue")

    # 1. PO-003: Gemini read the 10% VAT base 2 204,00 as 2 204,04.
    page.get_by_role("link", name="FA-DA-2026-0162").click()
    expect(page.get_by_text("VAT breakdown does not add up")).to_be_visible()
    expect(page.locator(".box").first).to_be_visible()
    pause(page)
    page.get_by_text("VAT breakdown does not add up").click()
    base = field(page, "vat.0.base_ht")
    if base.input_value() != "2204.04":
        base = field(page, "vat.1.base_ht")
    base.scroll_into_view_if_needed()
    base.focus()
    pause(page, 1200)
    shot(page, "misread")
    base.fill("")
    base.press_sequentially("2204.00", delay=120)
    expect(page.get_by_text("All checks pass")).to_be_visible(timeout=10_000)
    pause(page, 1200)
    shot(page, "fixed")
    page.get_by_role("button", name="Approve → draft bill in Odoo").click()
    expect(page.get_by_text("Draft bill created in Odoo")).to_be_visible(timeout=20_000)
    pause(page, 1500)
    shot(page, "approved")

    # 2. PO-004: +8% on one price; approve only with a reason.
    page.goto(f"{BASE}/cases/{ids['PO-004']}")
    expect(page.get_by_text("Price differs from the PO")).to_be_visible()
    pause(page, 1200)
    reason = page.get_by_role("textbox", name="Why approve over")
    reason.press_sequentially("New oil price agreed with Anfa by phone on 9 Nov.", delay=35)
    approve = page.get_by_role("button", name="Approve → draft bill in Odoo")
    expect(approve).to_be_enabled()
    pause(page)
    shot(page, "override")
    approve.click()
    expect(page.get_by_text("Draft bill created in Odoo")).to_be_visible(timeout=20_000)
    pause(page, 1200)

    # 3. PO-002: total HT misread (4 700,05) and a real short delivery. Fixing the total
    # clears the arithmetic, the short delivery stays: reject.
    page.goto(f"{BASE}/cases/{ids['PO-002']}")
    expect(page.get_by_text("Billed more than received")).to_be_visible()
    pause(page, 1200)
    total = field(page, "total_ht")
    total.scroll_into_view_if_needed()
    total.fill("")
    total.press_sequentially("4700.00", delay=120)
    expect(page.get_by_text("Total incl. tax does not add up")).to_have_count(0, timeout=10_000)
    page.locator(".right").evaluate("el => el.scrollTo({top: 0, behavior: 'smooth'})")
    pause(page, 1200)
    shot(page, "short-delivery")
    page.get_by_role("button", name="Reject…").click()
    page.get_by_role("textbox", name="Why reject?").press_sequentially(
        "Short delivery: 14 of 20 kg merlan received. Credit note asked.", delay=30
    )
    page.get_by_role("button", name="Reject case").click()
    expect(page.get_by_text("Rejected by")).to_be_visible(timeout=10_000)
    pause(page, 1200)

    page.goto(f"{BASE}/?status=all")
    expect(page.get_by_text("rejected").first).to_be_visible()
    pause(page, 1500)
    shot(page, "queue-done")


def to_gif(video: Path, out: Path) -> None:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found: no GIF", file=sys.stderr)
        return
    vf = "fps=8,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", vf, str(out)], check=True
    )


def main() -> int:
    ids = case_ids()
    missing = {"PO-002", "PO-003", "PO-004"} - set(ids)
    if missing:
        print(f"no open review case for {sorted(missing)}: see the docstring", file=sys.stderr)
        return 1
    IMG.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": W, "height": H},
            device_scale_factor=2,
            color_scheme="light",
            record_video_dir=tmp,
            record_video_size={"width": W, "height": H},
        )
        page = ctx.new_page()
        try:
            run(page, ids)
        finally:
            video = Path(page.video.path())
            ctx.close()
            browser.close()
        to_gif(video, IMG / "review-demo.gif")
    print(f"wrote {sorted(f.name for f in IMG.glob('review-*'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
