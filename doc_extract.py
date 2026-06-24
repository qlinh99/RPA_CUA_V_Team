# -*- coding: utf-8 -*-
"""
Trích xuất ĐỘNG: đọc bất kỳ chứng từ (ảnh/PDF) -> JSON gồm MỌI cặp nhãn→giá trị
tài liệu có, KHÔNG khoá vào schema hoá đơn 9 trường. Tự đoán loại tài liệu.

Dùng cho Zalo (gửi tin theo đúng nội dung ảnh) hoặc xem trước tự do.
Tái dùng doc_reader.file_to_pages + engine OCR (create_ocr_adapter).

Chạy thử:
    py -3.11 doc_extract.py "..\\...\\anh_bat_ky.png"
"""
from __future__ import annotations
import _bootstrap  # .env, temp->D:, sys.path
import json
import re

from doc_reader import file_to_pages
from test_image_processing import create_ocr_adapter

DYNAMIC_PROMPT = (
    "Bạn là trợ lý trích xuất dữ liệu chứng từ. Hãy ĐỌC tài liệu và trả về DUY NHẤT một JSON "
    "(không giải thích, không bọc trong ```).\n"
    "JSON gồm 2 khoá:\n"
    '  "loai_tai_lieu": tên ngắn gọn loại chứng từ (vd "Hóa đơn GTGT", '
    '"Phiếu thông tin bệnh nhân", "Phiếu thu", "Giấy giới thiệu").\n'
    '  "truong": object chứa MỌI cặp "nhãn": "giá trị" đọc được trên tài liệu, GIỮ NGUYÊN '
    "nhãn tiếng Việt đúng như hiển thị. Bỏ ô trống. Số tiền/ngày giữ nguyên định dạng gốc.\n"
)
TEXT_NOTE = "\n\nĐây là VĂN BẢN trích từ PDF điện tử, hãy trích JSON từ nó:\n----------\n"


def _strip_json(text: str) -> str:
    t = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    if not t.startswith("{"):
        brace = re.search(r"\{.*\}", t, re.S)
        if brace:
            t = brace.group(0)
    return t


def _coerce_fields(d: dict) -> dict:
    """Lấy object trường dù model trả 'truong' lồng hay phẳng."""
    if isinstance(d.get("truong"), dict):
        return d["truong"]
    return {k: v for k, v in d.items()
            if k != "loai_tai_lieu" and not isinstance(v, (dict, list))}


def extract_dynamic(path: str) -> dict:
    """-> {'loai_tai_lieu': str, 'truong': {nhãn: giá trị, ...}}. Gộp mọi trang."""
    pages = file_to_pages(path)
    adapter = create_ocr_adapter()
    doc_type = ""
    fields: dict = {}
    for idx, page in enumerate(pages, 1):
        if page[0] == "text":
            res = adapter.ocr([], prompt=DYNAMIC_PROMPT + TEXT_NOTE + page[1])
        else:
            _, b64, size = page
            res = adapter.ocr(b64, prompt=DYNAMIC_PROMPT, image_sizes=[size])
        if not res.get("success"):
            print(f"  ⚠️  Trang {idx} OCR lỗi: {res.get('error')}")
            continue
        try:
            d = json.loads(_strip_json(res["text"]))
        except Exception as e:
            print(f"  ⚠️  Trang {idx} không phải JSON hợp lệ: {e}")
            continue
        doc_type = doc_type or (d.get("loai_tai_lieu") or "")
        for k, v in _coerce_fields(d).items():
            k = str(k).strip()
            if k and v not in (None, "", []) and k not in fields:
                fields[k] = v
    if not fields:
        raise RuntimeError("Không trích xuất được dữ liệu từ file này.")
    return {"loai_tai_lieu": doc_type, "truong": fields}


def format_message(data: dict) -> str:
    """Tin nhắn nhiều dòng theo ĐÚNG nội dung tài liệu (không khuôn cố định)."""
    title = (data.get("loai_tai_lieu") or "Chứng từ").strip()
    lines = [f"📄 {title.upper()}"]
    for k, v in data["truong"].items():
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        lines.append(f"• {k}: {v}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Dùng: py -3.11 doc_extract.py <ảnh|pdf>")
        raise SystemExit(1)
    data = extract_dynamic(sys.argv[1])
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("\n--- TIN NHẮN ---")
    print(format_message(data))
