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
from contextlib import contextmanager
from pathlib import Path

SUBMIT_LABELS = ("gửi", "submit")
SHOT_DIR = _bootstrap.SCREENSHOT_DIR


def _nfc(s) -> str:
    return unicodedata.normalize("NFC", s or "")


def _ddmmyyyy_to_iso(s: str) -> str:
    d, m, y = str(s).split("/")[:3]
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


DEFAULT_TIME = ("08", "00")   # giờ mặc định nếu chứng từ chỉ có ngày (câu hỏi date+time)


def _split_time(val: str) -> "tuple[str, str]":
    """Bóc 'HH:MM' (hoặc 'HHhMM') trong value; không có thì dùng giờ mặc định."""
    m = re.search(r"(\d{1,2})\s*[:h]\s*(\d{2})", str(val))
    if m:
        return str(int(m.group(1))), str(int(m.group(2)))
    return DEFAULT_TIME


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
            # Câu hỏi 'ngày + giờ' có thêm ô Giờ/Phút — BẮT BUỘC điền, nếu trống
            # Google báo "Thời gian không hợp lệ" và CHẶN nút Gửi.
            hh, mm = _split_time(val)
            for lbl, v in (("Giờ", hh), ("Hour", hh), ("Phút", mm), ("Minute", mm)):
                ti = q.locator(f'input[aria-label="{lbl}"]')
                if ti.count():
                    ti.first.fill(v)
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


def _confirm_submitted(page) -> "tuple[bool, str]":
    """Sau khi bấm Gửi: xác nhận đã sang trang phản hồi. Nếu chưa → bóc lỗi xác thực
    (tên ô bị 'không hợp lệ'/bắt buộc) để báo rõ vì sao form KHÔNG gửi được."""
    try:
        page.wait_for_url(re.compile(r"formResponse"), timeout=12000)
        return True, ""
    except Exception:
        pass
    try:
        page.wait_for_selector(
            "text=/đã ghi câu trả lời|response has been recorded/i", timeout=4000)
        return True, ""
    except Exception:
        pass
    # vẫn ở trên form → tìm thông báo lỗi và câu hỏi tương ứng
    bad = []
    try:
        errs = page.locator(
            "text=/không hợp lệ|câu hỏi bắt buộc|bắt buộc|required|invalid|must/i")
        for i in range(min(errs.count(), 6)):
            li = errs.nth(i).locator("xpath=ancestor::div[@role='listitem'][1]")
            txt = (li.first.inner_text() if li.count() else errs.nth(i).inner_text())
            head = _nfc(txt).replace("\n", " ").strip()[:70]
            if head and head not in bad:
                bad.append(head)
    except Exception:
        pass
    detail = "; ".join(bad) if bad else "form còn ô bắt buộc trống / lỗi xác thực"
    return False, "Chưa rời được form (chưa gửi) — " + detail


def fill_and_submit_browser(form_url: str, items: "list[dict]", *, headless: bool = True,
                            retries: int = 2, shot_dir: Path = SHOT_DIR,
                            channel: str = "chrome", slow_mo: int = 0,
                            shot_name: str = "form", browser=None) -> dict:
    """
    browser=None : tạo + đóng browser mới mỗi lần gọi (1 bản ghi độc lập).
    browser=<Browser> : tái sử dụng browser đã mở, chỉ mở tab mới (multi-record).
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    shot_dir.mkdir(exist_ok=True)
    last_err = ""

    def _attempt(n: int, _browser) -> dict:
        page = _browser.new_page()
        try:
            page.goto(form_url, wait_until="domcontentloaded")
            page.wait_for_selector("[role='button']", timeout=15000)

            remaining = [it for it in items if it.get("value") not in (None, "", [])]
            for pg in range(1, 21):
                remaining = [it for it in remaining if not _try_fill_field(page, it)]
                submit_b, next_b = _find_nav(page)
                if submit_b:
                    submit_b.click()
                    break
                if next_b:
                    print(f"   ➡️  sang trang {pg + 1} (bấm Tiếp)")
                    next_b.click()
                    try:
                        next_b.wait_for(state="hidden", timeout=3000)
                    except Exception:
                        pass
                    page.wait_for_selector("[role='button']", timeout=5000)
                    continue
                raise RuntimeError("Không thấy nút Tiếp/Gửi để đi tiếp")

            ok, detail = _confirm_submitted(page)
            tag = "" if ok else "_FAIL"
            shot = shot_dir / f"{shot_name}_attempt{n}{tag}.png"
            page.screenshot(path=str(shot), full_page=True)
            if ok:
                print(f"[OK] {shot_name} (lần {n}) -> {shot}")
                return {"ok": True, "screenshot": str(shot), "attempts": n, "error": ""}
            # lỗi xác thực là TẤT ĐỊNH → không retry vô ích
            print(f"[CHƯA GỬI] {shot_name}: {detail}")
            return {"ok": False, "screenshot": str(shot), "attempts": n, "error": detail}
        finally:
            page.close()

    for attempt in range(1, retries + 1):
        try:
            if browser is not None:
                return _attempt(attempt, browser)
            with sync_playwright() as p:
                _b = p.chromium.launch(headless=headless, channel=channel, slow_mo=slow_mo)
                try:
                    return _attempt(attempt, _b)
                finally:
                    _b.close()
        except PWTimeout as e:
            last_err = f"Timeout: {e}"
        except Exception as e:
            last_err = str(e)
        print(f"[RETRY] {shot_name} lần {attempt} lỗi: {last_err}")
        time.sleep(2 * attempt)
    return {"ok": False, "screenshot": "", "attempts": retries, "error": last_err}


@contextmanager
def browser_context(headless: bool = True, channel: str = "chrome", slow_mo: int = 0):
    """Mở 1 browser dùng chung cho nhiều bản ghi; đóng khi thoát context."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel=channel, slow_mo=slow_mo)
        try:
            yield browser
        finally:
            browser.close()


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
