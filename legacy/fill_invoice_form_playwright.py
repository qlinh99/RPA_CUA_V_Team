# -*- coding: utf-8 -*-
"""
Bậc 3 — điền Google Form bằng Playwright (trình duyệt thật) + screenshot bằng chứng.
Đọc cấu hình trường từ form_config.py; điền theo NHÃN câu hỏi (không phụ thuộc id tự sinh).

    from fill_invoice_form_playwright import submit_invoice_browser
    submit_invoice_browser(form_dict, headless=False, slow_mo=700)
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _bootstrap  # PHẢI đứng đầu: temp sang D:, nạp .env, sys.path
import time
import unicodedata

from . import form_config as cfg

SHOT_DIR = _bootstrap.SCREENSHOT_DIR


def _nfc(s) -> str:
    return unicodedata.normalize("NFC", s or "")


def _click_submit(page) -> None:
    """Tìm nút Gửi/Submit không phụ thuộc dạng Unicode (NFC/NFD tiếng Việt)."""
    btns = page.get_by_role("button")
    for i in range(btns.count()):
        b = btns.nth(i)
        label = _nfc(b.get_attribute("aria-label") or "") or _nfc(b.inner_text() or "")
        if label.strip().lower() in cfg.SUBMIT_LABELS:
            b.click()
            return
    raise RuntimeError("Không tìm thấy nút Gửi/Submit")


def _ddmmyyyy_to_iso(s: str) -> str:
    d, m, y = s.split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _fill_one(page, inv: dict) -> None:
    """Điền từng trường theo type khai báo trong form_config.FIELDS."""
    for f in cfg.FIELDS:
        val = inv.get(f["key"])
        if val in (None, ""):
            continue
        t = f["type"]
        if t in ("text", "paragraph"):
            box = page.get_by_role("textbox", name=f["label"], exact=False).first
            box.click()
            box.fill(str(val))
        elif t == "date":
            page.locator('input[type="date"]').first.fill(_ddmmyyyy_to_iso(str(val)))
        elif t == "radio":
            page.get_by_role("radio", name=str(val), exact=True).click()
        elif t == "dropdown":
            page.get_by_role("listbox").first.click()
            page.get_by_role("option", name=str(val), exact=True).click()
        else:
            raise ValueError(f"type chưa hỗ trợ: {t} (trường {f['key']})")


def submit_invoice_browser(inv: dict, *, headless: bool = True, retries: int = 2,
                           shot_dir: Path = SHOT_DIR, channel: str = "chrome",
                           slow_mo: int = 0) -> dict:
    """
    Mở form, điền, submit, chụp screenshot xác nhận.
    channel='chrome'|'msedge' -> dùng trình duyệt sẵn có (khỏi tải Chromium).
    slow_mo: ms chờ mỗi thao tác (>0 để xem rõ quá trình điền).
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    shot_dir.mkdir(exist_ok=True)
    inv_id = str(inv.get("so_hoa_don", "unknown"))
    last_err = ""

    for attempt in range(1, retries + 1):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless, channel=channel, slow_mo=slow_mo)
                page = browser.new_page()
                page.goto(cfg.FORM_URL, wait_until="domcontentloaded")
                page.wait_for_selector("div[role='listitem']", timeout=15000)

                _fill_one(page, inv)
                _click_submit(page)

                page.wait_for_selector("text=/ghi|recorded|response/i", timeout=15000)
                shot = shot_dir / f"{inv_id}_attempt{attempt}.png"
                page.screenshot(path=str(shot), full_page=True)
                browser.close()
                print(f"[OK] {inv_id} (lần {attempt}) -> {shot}")
                return {"ok": True, "screenshot": str(shot), "attempts": attempt, "error": ""}
        except PWTimeout as e:
            last_err = f"Timeout: {e}"
        except Exception as e:
            last_err = str(e)
        print(f"[RETRY] {inv_id} lần {attempt} lỗi: {last_err}")
        time.sleep(2 * attempt)

    return {"ok": False, "screenshot": "", "attempts": retries, "error": last_err}


if __name__ == "__main__":
    mau = {
        "so_hoa_don": "PW-0001", "ky_hieu": "1C25TAA", "ngay_lap": "18/06/2026",
        "ten_ncc": "Cong ty TNHH ABC", "mst_ncc": "0312345678",
        "dien_giai": "Test Playwright", "tien_truoc_thue": "1000000",
        "thue_suat": "8%", "tong_thanh_toan": "1080000",
    }
    print(submit_invoice_browser(mau, headless=False, slow_mo=700))
