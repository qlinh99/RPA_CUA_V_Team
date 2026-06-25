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

# ── JS helpers: giảm roundtrips ───────────────────────────────────────────────

def _labels_on_page(page, items: "list[dict]") -> "set[str]":
    """1 JS roundtrip → set nhãn đang hiển thị trên trang.
    Thay thế N lần q.count() tuần tự."""
    labels = [it["label"] for it in items if it.get("value") not in (None, "", [])]
    if not labels:
        return set()
    found: list = page.evaluate(
        """(labels) => {
            const texts = [...document.querySelectorAll('div[role="listitem"]')]
                          .map(el => el.textContent.normalize('NFC'));
            return labels.filter(lbl =>
                texts.some(t => t.includes(lbl.normalize('NFC'))));
        }""",
        labels,
    )
    return set(found)


def _js_click_radio(page, label: str, val: str,
                    grid_label: "str | None") -> bool:
    """Click radio/scale bằng JS — 1 roundtrip thay vì 4–5 locator chains.
    grid_label khác None → tìm radiogroup theo aria-label (grid row)."""
    if grid_label:
        js = """([label, val]) => {
            const lbl = label.normalize('NFC');
            const v   = val.normalize('NFC');
            const rg  = [...document.querySelectorAll('[role="radiogroup"]')]
                .find(el => (el.getAttribute('aria-label') || '').normalize('NFC') === lbl);
            if (!rg) return false;
            const r = [...rg.querySelectorAll('[role="radio"]')].find(r => {
                const al = (r.getAttribute('aria-label') || '').normalize('NFC');
                return al === v || al.startsWith(v + ',');
            });
            if (r) { r.click(); return true; }
            return false;
        }"""
    else:
        js = """([label, val]) => {
            const lbl = label.normalize('NFC');
            const v   = val.normalize('NFC');
            const li  = [...document.querySelectorAll('div[role="listitem"]')]
                .find(el => el.textContent.normalize('NFC').includes(lbl));
            if (!li) return false;
            const r = [...li.querySelectorAll('[role="radio"]')].find(r => {
                const al = (r.getAttribute('aria-label') || '').normalize('NFC');
                return al === v || r.textContent.normalize('NFC').trim() === v;
            });
            if (r) { r.click(); return true; }
            return false;
        }"""
    return bool(page.evaluate(js, [label, val]))


def _js_click_checkbox(page, label: str, vals: "list[str]") -> bool:
    """Click checkbox(es) bằng JS — 1 roundtrip."""
    js = """([label, vals]) => {
        const lbl = label.normalize('NFC');
        const li  = [...document.querySelectorAll('div[role="listitem"]')]
            .find(el => el.textContent.normalize('NFC').includes(lbl));
        if (!li) return false;
        let ok = false;
        for (const val of vals) {
            const v  = val.normalize('NFC');
            const cb = [...li.querySelectorAll('[role="checkbox"]')].find(el => {
                const al = (el.getAttribute('aria-label') || '').normalize('NFC');
                return al === v || el.textContent.normalize('NFC').trim() === v;
            });
            if (cb) { cb.click(); ok = true; }
        }
        return ok;
    }"""
    return bool(page.evaluate(js, [label, vals]))


def _find_nav(page):
    """Tìm nút Gửi/Tiếp — 1 JS roundtrip, index đồng nhất với querySelectorAll."""
    idx: list = page.evaluate(
        """() => {
            const SL = new Set(['gửi', 'submit']);
            const NL = new Set(['tiếp', 'tiếp theo', 'next']);
            const btns = [...document.querySelectorAll('[role="button"]')];
            let si = -1, ni = -1;
            btns.forEach((b, i) => {
                const l = (b.getAttribute('aria-label') || b.textContent || '')
                           .trim().normalize('NFC').toLowerCase();
                if (SL.has(l)) si = i;
                else if (NL.has(l)) ni = i;
            });
            return [si, ni];
        }"""
    )
    # Dùng attribute selector để index khớp với querySelectorAll trong JS
    btns = page.locator('[role="button"]')
    si, ni = idx
    return (btns.nth(si) if si >= 0 else None,
            btns.nth(ni) if ni >= 0 else None)


def _try_fill_field(page, item) -> bool:
    """Điền 1 trường — giả định trường đã được xác nhận có trên trang (từ _labels_on_page).
    Radio/checkbox dùng JS (1 roundtrip); text/date/dropdown dùng Playwright fill."""
    val = item.get("value")
    if val in (None, "", []):
        return True
    label, t = item["label"], item["type"]
    try:
        if t in ("radio", "scale"):
            return _js_click_radio(
                page, _nfc(label), _nfc(str(val)),
                _nfc(item["grid_label"]) if item.get("grid_label") else None,
            )
        if t == "checkbox":
            vals = val if isinstance(val, list) else [val]
            return _js_click_checkbox(page, _nfc(label), [_nfc(v) for v in vals])

        # text / date / dropdown — Playwright fill (đáng tin cậy với Angular/React)
        q = page.locator("div[role='listitem']").filter(has_text=label).first
        if t in ("text", "paragraph"):
            q.get_by_role("textbox").first.fill(str(val), timeout=4000)
        elif t == "date":
            q.locator('input[type="date"]').first.fill(_ddmmyyyy_to_iso(val), timeout=4000)
            hh, mm = _split_time(val)
            for lbl, v in (("Giờ", hh), ("Hour", hh), ("Phút", mm), ("Minute", mm)):
                ti = q.locator(f'input[aria-label="{lbl}"]')
                if ti.count():
                    ti.first.fill(v)
        elif t == "dropdown":
            q.get_by_role("listbox").first.click()
            page.get_by_role("option", name=str(val), exact=True).first.click()
        else:
            return True
        return True
    except Exception:
        return False


def _confirm_submitted(page) -> "tuple[bool, str]":
    """Sau khi bấm Gửi: xác nhận đã sang trang phản hồi. Nếu chưa → bóc lỗi xác thực
    (tên ô bị 'không hợp lệ'/bắt buộc) để báo rõ vì sao form KHÔNG gửi được."""
    try:
        page.wait_for_url(re.compile(r"formResponse"), timeout=20000)
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
                            shot_name: str = "form", browser=None,
                            debug: bool = False) -> dict:
    """
    browser=None : tạo + đóng browser mới mỗi lần gọi (1 bản ghi độc lập).
    browser=<Browser> : tái sử dụng browser đã mở, chỉ mở tab mới (multi-record).
    debug=True : in chi tiết từng trường thất bại trên mỗi trang.
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
                # 1 JS roundtrip → biết label nào đang hiển thị trang này
                on_page = _labels_on_page(page, remaining)

                prev_len = len(remaining)
                new_remaining = []
                for it in remaining:
                    if it["label"] not in on_page:
                        new_remaining.append(it)          # chưa đến trang này
                    elif not _try_fill_field(page, it):
                        new_remaining.append(it)          # trên trang nhưng thất bại
                remaining = new_remaining
                filled_now = prev_len - len(remaining)

                submit_b, next_b = _find_nav(page)

                # Trường nào ở trang này nhưng vẫn còn trong remaining → thất bại
                on_page_fail = [it for it in remaining if it["label"] in on_page
                                and it.get("value") not in (None, "", [])]
                pg_label = "Trước khi nộp" if submit_b else f"Trang {pg}"
                if on_page_fail:
                    print(f"   ⚠️  {pg_label}: {len(on_page_fail)} trường CHƯA ĐIỀN ĐƯỢC")
                    if debug:
                        for it in on_page_fail:
                            print(f"      • {it['label']!r}  ← {it['value']!r}")
                elif filled_now:
                    print(f"   ✅  {pg_label}: điền {filled_now} trường")

                if submit_b:
                    # [G1] Pre-submit DOM check: trường required nào chưa có giá trị?
                    empty_req = page.evaluate("""() => {
                        return [...document.querySelectorAll('div[role="listitem"]')]
                            .filter(li => {
                                const rg = li.querySelector('[role="radiogroup"]');
                                if (rg) {
                                    if (rg.getAttribute('aria-required') !== 'true') return false;
                                    return ![...li.querySelectorAll('[role="radio"]')]
                                        .some(r => r.getAttribute('aria-checked') === 'true');
                                }
                                const tb = li.querySelector('[role="textbox"]');
                                if (tb && tb.getAttribute('aria-required') === 'true')
                                    return !tb.value.trim();
                                const inp = li.querySelector(
                                    'input[type="date"], input[type="time"], input[type="text"]');
                                if (inp && inp.getAttribute('aria-required') === 'true')
                                    return !inp.value.trim();
                                return false;
                            })
                            .map(li => li.textContent.trim()
                                         .replace(/\\s+/g, ' ').slice(0, 60));
                    }""")
                    if empty_req:
                        print(f"   ⚠️  PRE-SUBMIT DOM: {len(empty_req)} trường bắt buộc"
                              f" chưa điền theo DOM:")
                        for t in empty_req:
                            print(f"      • {t!r}")
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
