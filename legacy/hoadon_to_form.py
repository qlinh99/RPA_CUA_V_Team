# -*- coding: utf-8 -*-
"""
CHƯƠNG TRÌNH CHÍNH: hoá đơn (ẢNH hoặc PDF) -> OCR -> điền Google Form (Playwright).

PDF điện tử  : lấy text bằng pdfplumber, gửi TEXT cho LLM bóc JSON (rẻ + chính xác).
PDF scan/ảnh : render/encode ảnh, gửi ẢNH cho LLM vision OCR.

CÁCH CHẠY (Python 3.11):
    # chỉ trích xuất, in 9 trường (an toàn, không gửi):
    py -3.11 hoadon_to_form.py "đường_dẫn\\hoadon.pdf"

    # trích xuất rồi GỬI lên form:
    py -3.11 hoadon_to_form.py "đường_dẫn\\hoadon.jpg" --submit

    # thêm --headed để XEM trình duyệt điền (chạy chậm)
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _bootstrap  # PHẢI đứng đầu: temp sang D:, nạp .env, thêm sys.path
import json
import re

from core.ocr_engine import create_ocr_adapter, process_image, prepare_for_api, OCR_PROMPTS
from core.ocr_to_form import to_form_dict
from .fill_invoice_form_playwright import submit_invoice_browser
from . import form_config as cfg

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
FORM_KEYS = [f["key"] for f in cfg.FIELDS]
PDF_TEXT_MIN = 50  # >50 ký tự text => coi là PDF điện tử (như covert.py)

TEXT_EXTRACT_PROMPT = OCR_PROMPTS["structured"] + (
    "\n\nDưới đây là NỘI DUNG VĂN BẢN đã trích xuất sẵn từ một trang PDF điện tử "
    "(KHÔNG phải ảnh). Hãy trích xuất JSON đúng schema trên TỪ VĂN BẢN NÀY:\n\n----------\n"
)


# ── kế thừa covert.py: bảng -> markdown, text ngoài vùng bảng ─────────────────
def _table_to_markdown(table_data) -> str:
    if not table_data or not any(table_data):
        return ""
    rows = [r for r in table_data if r and any(c is not None for c in r)]
    if not rows:
        return ""
    md = ""
    for i, row in enumerate(rows):
        clean = [str(c).replace("\n", "<br>").strip() if c is not None else "" for c in row]
        md += "| " + " | ".join(clean) + " |\n"
        if i == 0:
            md += "| " + " | ".join(["---"] * len(clean)) + " |\n"
    return md + "\n"


def _pdf_page_text(page_plumber) -> str:
    table_bboxes = [t.bbox for t in page_plumber.find_tables()]

    def not_within_table(obj):
        if obj["object_type"] != "char":
            return True
        for x0, top, x1, bottom in table_bboxes:
            if (x0 <= obj["x0"] <= x1) and (top <= obj["top"] <= bottom):
                return False
        return True

    clean_text = page_plumber.filter(not_within_table).extract_text() or ""
    md_tables = "".join(_table_to_markdown(t) for t in page_plumber.extract_tables())
    return (clean_text + "\n\n" + md_tables).strip()


# ── file -> danh sách "trang": ('text', md) hoặc ('image', b64, size) ─────────
def file_to_pages(path: str) -> "list[tuple]":
    ext = Path(path).suffix.lower()

    if ext in IMG_EXT:
        b64, _q, size = process_image(path)
        return [("image", b64, size)]

    if ext == ".pdf":
        import fitz
        import pdfplumber
        import cv2
        import numpy as np

        pages: list[tuple] = []
        doc = fitz.open(path)
        plumber = pdfplumber.open(path)
        for i in range(len(doc)):
            txt = _pdf_page_text(plumber.pages[i])
            if len(txt.strip()) > PDF_TEXT_MIN:
                print(f"  ⚡ Trang {i+1}/{len(doc)}: PDF điện tử → lấy text bằng pdfplumber "
                      f"(không gửi ảnh; LLM chỉ bóc JSON từ text → rẻ + chính xác hơn)")
                pages.append(("text", txt))
            else:
                print(f"  📸 Trang {i+1}/{len(doc)}: PDF scan → render ảnh + LLM OCR")
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))
                arr = np.frombuffer(pix.tobytes("jpg"), np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                b64, size = prepare_for_api(img)
                pages.append(("image", b64, size))
        plumber.close()
        doc.close()
        return pages

    raise ValueError(f"Định dạng không hỗ trợ: {ext} (chỉ nhận ảnh hoặc .pdf)")


def _strip_json(text: str) -> str:
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    if not t.startswith("{"):
        brace = re.search(r"\{.*\}", t, re.S)
        if brace:
            t = brace.group(0)
    return t


def _merge_forms(forms: "list[dict]") -> dict:
    if len(forms) == 1:
        return forms[0]
    merged: dict = {}
    for k in FORM_KEYS:
        merged[k] = next((f.get(k) for f in forms if f.get(k) not in (None, "")), None)
    merged["_issues"] = [f"{k}: thiếu trên mọi trang" for k in FORM_KEYS if merged[k] in (None, "")]
    return merged


def extract_invoice(path: str) -> dict:
    """Đọc 1 file hoá đơn (ảnh/pdf) -> dict 9 trường đã chuẩn hoá."""
    pages = file_to_pages(path)
    adapter = create_ocr_adapter()

    forms: list[dict] = []
    for idx, page in enumerate(pages, 1):
        if page[0] == "text":
            result = adapter.ocr([], prompt=TEXT_EXTRACT_PROMPT + page[1])
        else:
            _, b64, size = page
            result = adapter.ocr(b64, prompt=OCR_PROMPTS["structured"], image_sizes=[size])

        if not result.get("success"):
            print(f"  ⚠️  Trang {idx} OCR lỗi: {result.get('error')}")
            continue
        try:
            forms.append(to_form_dict(json.loads(_strip_json(result["text"]))))
        except Exception as e:
            print(f"  ⚠️  Trang {idx} không phải JSON hợp lệ: {e}")

    if not forms:
        raise RuntimeError("Không trích xuất được dữ liệu từ file này.")
    return _merge_forms(forms)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_submit = "--submit" in sys.argv
    headed = "--headed" in sys.argv
    if not args:
        print(__doc__)
        return 1

    path = args[0]
    print(f"\n🧾 Xử lý hoá đơn: {path}")
    form = extract_invoice(path)

    issues = form.pop("_issues", [])
    print("\n📋 9 trường đã trích xuất (chuẩn hoá xong):")
    print(json.dumps(form, ensure_ascii=False, indent=2))
    if issues:
        print("\n⚠️  Trường cần kiểm tra tay:")
        for it in issues:
            print(f"   - {it}")

    if not do_submit:
        print("\n💡 Chưa gửi. Thêm cờ --submit để điền lên Google Form (thêm --headed để xem).")
        return 0
    if issues:
        print("\n⛔ Còn trường chưa hợp lệ — KHÔNG tự gửi (maker–checker).")
        return 2

    print("\n🌐 Đang mở trình duyệt điền form...")
    res = submit_invoice_browser(form, headless=not headed,
                                 slow_mo=700 if headed else 0,
                                 shot_dir=_bootstrap.SCREENSHOT_DIR)
    print(res)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
