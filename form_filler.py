# -*- coding: utf-8 -*-
"""
Điền Google Form TỔNG QUÁT theo danh sách trường (bất kỳ form nào).
Mỗi 'item' = {label, type, options, entry, value}. Không gắn cứng form nào.

  fill_and_submit_browser(form_url, items, ...)  # Playwright (trình duyệt thật)
  submit_post(post_url, items)                   # HTTP POST (không trình duyệt)
"""
from __future__ import annotations
import _bootstrap  # temp->D:, .env, sys.path
import re
import time
import unicodedata
from pathlib import Path

SUBMIT_LABELS = ("gửi", "submit")
SHOT_DIR = _bootstrap.SCREENSHOT_DIR


def _nfc(s) -> str:
    return unicodedata.normalize("NFC", s or "")


def _ddmmyyyy_to_iso(s: str) -> str:
    d, m, y = str(s).split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


# ── Playwright ────────────────────────────────────────────────────────────────
NEXT_LABELS = ("tiếp", "tiếp theo", "next")


def _find_nav(page):
    """Tìm nút điều hướng trên trang hiện tại: (nút Gửi, nút Tiếp). 'Quay lại' bị bỏ qua."""
    submit_b = next_b = None
    btns = page.get_by_role("button")
    for i in range(btns.count()):
        b = btns.nth(i)
        l = (_nfc(b.get_attribute("aria-label") or "") or _nfc(b.inner_text() or "")).strip().lower()
        if l in SUBMIT_LABELS:
            submit_b = b
        elif l in NEXT_LABELS:
            next_b = b
    return submit_b, next_b


def _try_fill_field(page, item) -> bool:
    """Điền 1 trường NẾU nó nằm trên trang hiện tại. Trả True nếu đã xử lý, False nếu không có ở đây."""
    val = item.get("value")
    if val in (None, "", []):
        return True
    label, t = item["label"], item["type"]
    q = page.locator("div[role='listitem']").filter(has_text=label)   # ô câu hỏi theo nhãn
    if q.count() == 0:
        return False                                                  # không ở trang này
    q = q.first
    try:
        if t in ("text", "paragraph"):
            box = q.get_by_role("textbox").first
            box.click(); box.fill(str(val))
        elif t == "date":
            q.locator('input[type="date"]').first.fill(_ddmmyyyy_to_iso(val))
        elif t in ("radio", "scale"):
            q.get_by_role("radio", name=str(val), exact=True).click()
        elif t == "dropdown":
            q.get_by_role("listbox").first.click()
            page.get_by_role("option", name=str(val), exact=True).first.click()
        elif t == "checkbox":
            for v in (val if isinstance(val, list) else [val]):
                q.get_by_role("checkbox", name=str(v), exact=True).click()
        else:
            return True
        return True
    except Exception:
        return False


def fill_and_submit_browser(form_url: str, items: "list[dict]", *, headless: bool = True,
                            retries: int = 2, shot_dir: Path = SHOT_DIR,
                            channel: str = "chrome", slow_mo: int = 0,
                            shot_name: str = "form") -> dict:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    shot_dir.mkdir(exist_ok=True)
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless, channel=channel, slow_mo=slow_mo)
                page = browser.new_page()
                page.goto(form_url, wait_until="domcontentloaded")
                page.wait_for_selector("[role='button']", timeout=15000)   # trang bìa không có ô, chỉ có nút

                # ĐIỀN QUA NHIỀU TRANG: điền ô trang hiện tại → "Tiếp" → ... → "Gửi"
                remaining = [it for it in items if it.get("value") not in (None, "", [])]
                for pg in range(1, 21):                       # tối đa 20 trang
                    remaining = [it for it in remaining if not _try_fill_field(page, it)]
                    submit_b, next_b = _find_nav(page)
                    if submit_b:
                        submit_b.click()
                        break
                    if next_b:
                        print(f"   ➡️  sang trang {pg + 1} (bấm Tiếp)")
                        next_b.click()
                        page.wait_for_timeout(900)
                        continue
                    raise RuntimeError("Không thấy nút Tiếp/Gửi để đi tiếp")

                # xác minh thật: URL đổi sang /formResponse hoặc text xác nhận đặc trưng
                try:
                    page.wait_for_url(re.compile(r"formResponse"), timeout=15000)
                except Exception:
                    page.wait_for_selector(
                        "text=/đã ghi câu trả lời|response has been recorded/i", timeout=5000)
                shot = shot_dir / f"{shot_name}_attempt{attempt}.png"
                page.screenshot(path=str(shot), full_page=True)
                browser.close()
                print(f"[OK] {shot_name} (lần {attempt}) -> {shot}")
                return {"ok": True, "screenshot": str(shot), "attempts": attempt, "error": ""}
        except PWTimeout as e:
            last_err = f"Timeout: {e}"
        except Exception as e:
            last_err = str(e)
        print(f"[RETRY] {shot_name} lần {attempt} lỗi: {last_err}")
        time.sleep(2 * attempt)
    return {"ok": False, "screenshot": "", "attempts": retries, "error": last_err}


# ── HTTP POST (không trình duyệt) ─────────────────────────────────────────────
def submit_post(post_url: str, items: "list[dict]", pages: int = 1) -> bool:
    import requests
    payload: dict = {}
    for it in items:
        val = it.get("value")
        if val in (None, ""):
            continue
        if it["type"] == "date":
            d, m, y = str(val).split("/")
            payload[f"{it['entry']}_day"] = int(d)
            payload[f"{it['entry']}_month"] = int(m)
            payload[f"{it['entry']}_year"] = int(y)
        elif it["type"] == "checkbox" and isinstance(val, list):
            payload[it["entry"]] = val
        else:
            payload[it["entry"]] = str(val)
    if pages > 1:
        # form nhiều trang: báo server đã "đi qua" tất cả trang (0,1,...,pages-1)
        payload["pageHistory"] = ",".join(str(i) for i in range(pages))
    r = requests.post(post_url, data=payload, timeout=15)
    ok = r.status_code in (200, 302)
    print(f"[{'OK' if ok else 'FAIL'}] POST -> HTTP {r.status_code}")
    return ok
