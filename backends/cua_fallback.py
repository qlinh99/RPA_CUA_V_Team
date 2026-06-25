# -*- coding: utf-8 -*-
"""
FALLBACK CUA (Bậc 4) cho WEB form — khi Playwright/DOM tất định gãy.
Cơ chế: Gemini Vision NHÌN ảnh chụp form → trả toạ độ (bounding box) từng ô →
Playwright click/gõ theo toạ độ (pixel), KHÔNG dùng selector DOM.

Tái dùng adapter Gemini có sẵn (test_image_processing) nên KHÔNG cần cài browser-use.
Đúng tinh thần Computer-Use Agent: thích nghi khi DOM đổi vì chỉ dựa vào pixel.

  cua_fill_web(form_url, items, headless=False) -> {ok, screenshot, error}
"""
from __future__ import annotations
import _bootstrap  # .env, temp->D:, sys.path
import re
import json
import time
from pathlib import Path

from core.ocr_engine import create_ocr_adapter, prepare_for_api

VW, VH = 1280, 1600           # viewport CSS px (scale=1) -> map toạ độ chuẩn hoá 0-1000


def _targets(items: list) -> list:
    """Mỗi item -> 1 'mục cần định vị' cho Gemini (ô nhập / lựa chọn). KHÔNG gồm nút Gửi."""
    out = []
    for i, it in enumerate(items):
        if it.get("value") in (None, "", []):
            continue
        t = it["type"]
        label = it["label"]
        if t in ("radio", "dropdown", "scale", "checkbox"):
            out.append({"id": f"t{i}", "act": "click",
                        "desc": f"lựa chọn '{it['value']}' của câu hỏi \"{label}\"",
                        "value": it["value"]})
        else:
            val = str(it["value"])
            if t == "date" and val.count("/") == 2:
                d, m, y = val.split("/")           # ô date Google Form là mm/dd/yyyy (Mỹ)
                val = f"{m}{d}{y}"                  # gõ chuỗi số MMDDYYYY -> hợp lệ
            out.append({"id": f"t{i}", "act": "type",
                        "desc": f"ô nhập của câu hỏi \"{label}\"",
                        "value": val})
    return out


def _shot_b64(page):
    import cv2, numpy as np
    png = page.screenshot(type="png")
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    b64, _ = prepare_for_api(img)
    return b64


def _ask_boxes(adapter, b64: str, targets: list) -> dict:
    lines = "\n".join(f'- {t["id"]}: {t["desc"]}' for t in targets)
    prompt = (
        "Đây là ẢNH CHỤP một Google Form. Tìm các phần tử sau, trả hộp bao chuẩn hoá 0-1000 "
        "[ymin,xmin,ymax,xmax].\n"
        "CỰC KỲ QUAN TRỌNG — với 'ô nhập': trả hộp của CHÍNH Ô TEXTBOX để gõ chữ "
        "(khung/đường kẻ trống NẰM NGAY DƯỚI dòng chữ câu hỏi), TUYỆT ĐỐI KHÔNG trả hộp của "
        "dòng chữ câu hỏi. Với 'lựa chọn': trả hộp nút tròn (radio) cạnh chữ đó.\n"
        "CHỈ in JSON: {\"id\": [ymin,xmin,ymax,xmax], ...}. Mục không thấy thì bỏ qua.\n\n"
        f"CÁC MỤC:\n{lines}"
    )
    res = adapter.ocr(b64, prompt=prompt)
    if not res.get("success"):
        print(f"  ⚠️  Gemini lỗi: {str(res.get('error'))[:140]}")
        return {}
    txt = (res.get("text") or "").strip()
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        print(f"  ⚠️  Gemini không trả JSON: {txt[:90]!r}")
        return {}
    try:
        return json.loads(m.group(0))
    except Exception as e:
        print(f"  ⚠️  Lỗi parse JSON từ Gemini: {e} | {m.group(0)[:90]!r}")
        return {}


def _center(box, w, h):
    ymin, xmin, ymax, xmax = box
    cx = (xmin + xmax) / 2 / 1000 * w
    cy = (ymin + ymax) / 2 / 1000 * h
    return cx, cy


def cua_fill_web(form_url: str, items: list, *, headless: bool = False,
                 shot_dir: Path = None) -> dict:
    from playwright.sync_api import sync_playwright

    shot_dir = shot_dir or _bootstrap.SCREENSHOT_DIR
    shot_dir.mkdir(exist_ok=True)
    adapter = create_ocr_adapter()
    targets = _targets(items)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel="chrome")
        page = browser.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=1)
        page.goto(form_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # định vị + điền; ô nào Gemini bỏ sót -> THỬ LẠI (chụp lại, hỏi riêng) tối đa 3 vòng
        pending = list(targets)
        for attempt in range(1, 4):
            if not pending:
                break
            print(f"  👁️  CUA: Gemini định vị {len(pending)} ô (vòng {attempt})...")
            boxes = _ask_boxes(adapter, _shot_b64(page), pending)
            still = []
            for t in pending:
                box = boxes.get(t["id"])
                if not box or len(box) != 4:
                    still.append(t)
                    continue
                cx, cy = _center(box, VW, VH)
                page.mouse.click(cx, cy)
                page.wait_for_timeout(250)
                if t["act"] == "type":
                    page.keyboard.press("Control+A")
                    page.keyboard.type(str(t["value"]), delay=20)
                print(f"  • {t['act']:<5} @({cx:.0f},{cy:.0f}) ← {t['desc'][:38]}")
                page.wait_for_timeout(200)
            pending = still
            if pending:
                print(f"  🔁 còn thiếu {len(pending)} ô → thử định vị lại: "
                      f"{[t['desc'][:20] for t in pending]}")
        if pending:
            print(f"  ⚠️  CUA vẫn không định vị được {len(pending)} ô sau 3 vòng")

        # CUỘN XUỐNG đáy + chụp lại để thấy nút Gửi
        print("  ⬇️  cuộn xuống tìm nút Gửi (ảnh 2)...")
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(800)
        sb = _ask_boxes(adapter, _shot_b64(page),
                        [{"id": "submit", "desc": "nút Gửi (Submit) màu xanh ở cuối form"}])
        if sb.get("submit") and len(sb["submit"]) == 4:
            cx, cy = _center(sb["submit"], VW, VH)
            page.mouse.click(cx, cy)
            print(f"  • click @({cx:.0f},{cy:.0f}) ← nút Gửi")
        else:
            print("  ⚠️  vẫn không thấy nút Gửi")

        # XÁC MINH thật: URL đổi sang /formResponse HOẶC text xác nhận đặc trưng
        ok = False
        try:
            page.wait_for_url(re.compile(r"formResponse"), timeout=10000)
            ok = True
        except Exception:
            try:
                page.wait_for_selector(
                    "text=/đã ghi câu trả lời|câu trả lời của bạn đã được ghi|response has been recorded/i",
                    timeout=4000)
                ok = True
            except Exception:
                ok = False

        shot = shot_dir / "cua_web_result.png"
        page.screenshot(path=str(shot), full_page=True)
        browser.close()

    print(f"  {'✅' if ok else '⛔'} {'Đã gửi (xác minh URL/text)' if ok else 'CHƯA chắc gửi được'}  📸 {shot}")
    return {"ok": ok, "screenshot": str(shot), "error": "" if ok else "không xác minh được trang xác nhận"}
