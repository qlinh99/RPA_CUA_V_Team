# -*- coding: utf-8 -*-
"""
SOI 1 GOOGLE FORM: in ra mọi câu hỏi (nhãn, kiểu, entry id, lựa chọn) và
sinh sẵn khối FIELDS để dán vào form_config.py.

Dùng:
    py -3.11 inspect_form.py https://forms.gle/xxxx
    py -3.11 inspect_form.py "https://docs.google.com/forms/d/e/<ID>/viewform"

Cơ chế: Google nhúng cấu trúc form trong biến JS FB_PUBLIC_LOAD_DATA_.
Script tải HTML form (urllib, tự theo redirect forms.gle) rồi bóc biến đó —
KHÔNG cần trình duyệt, không cần API.
"""
import json
import re
import sys
import unicodedata
import urllib.request

# mã kiểu câu hỏi của Google Forms -> tên dùng trong form_config
TYPE_MAP = {
    0: "text", 1: "paragraph", 2: "radio", 3: "dropdown",
    4: "checkbox", 5: "scale", 7: "grid", 9: "date", 10: "time", 13: "file",
}


def _slug(name: str) -> str:
    """Biến nhãn tiếng Việt thành key gợi ý (ascii, gạch dưới)."""
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "field"


def fetch_form(url: str):
    """Trả về (title, fields, view_url, pages). pages = số trang/section của form."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        view_url = resp.geturl()
        html = resp.read().decode("utf-8", errors="replace")

    m = re.search(r"FB_PUBLIC_LOAD_DATA_ = (.*?);</script>", html, re.S)
    if not m:
        raise RuntimeError("Không tìm thấy FB_PUBLIC_LOAD_DATA_ — URL có đúng là Google Form công khai?")
    data = json.loads(m.group(1))

    title = data[1][8] if len(data[1]) > 8 else ""
    questions = data[1][1] or []
    pages = 1 + sum(1 for q in questions if q[3] == 8)   # mỗi 'page-break' (type 8) = +1 trang
    out = []
    for q in questions:
        name = q[1]
        type_code = q[3]
        entries = q[4] if len(q) > 4 else None
        if not entries:                      # mục mô tả/ảnh/page-break, không có ô nhập
            continue
        for e in entries:
            eid = f"entry.{e[0]}"
            required = bool(e[2]) if len(e) > 2 else False
            options = [o[0] for o in e[1]] if e[1] else None
            out.append({
                "label": name,
                "type": TYPE_MAP.get(type_code, f"code{type_code}"),
                "entry": eid,
                "required": required,
                "options": options,
            })
    return title, out, view_url, pages


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    url = sys.argv[1]
    title, fields, _view_url, _pages = fetch_form(url)

    print(f"\n📋 Form: {title}")
    print(f"   URL : {url}")
    print(f"   Số ô: {len(fields)}\n")
    print(f"{'#':<3}{'TYPE':<10}{'REQ':<5}{'ENTRY':<20}LABEL / OPTIONS")
    print("-" * 78)
    for i, f in enumerate(fields, 1):
        req = "★" if f["required"] else ""
        print(f"{i:<3}{f['type']:<10}{req:<5}{f['entry']:<20}{f['label']}")
        if f["options"]:
            print(f"{'':<38}options = {f['options']}")

    # sinh sẵn khối FIELDS để dán vào form_config.py
    print("\n" + "=" * 78)
    print("➜ DÁN khối dưới vào FIELDS trong form_config.py rồi sửa 'key' cho khớp")
    print("  9 khoá OCR (so_hoa_don, ky_hieu, ngay_lap, ten_ncc, mst_ncc, dien_giai,")
    print("  tien_truoc_thue, thue_suat, tong_thanh_toan):")
    print("=" * 78)
    print("FIELDS = [")
    for f in fields:
        line = (f'    {{"key": "{_slug(f["label"])}", "label": "{f["label"]}", '
                f'"entry": "{f["entry"]}", "type": "{f["type"]}"')
        if f["options"]:
            line += f', "options": {f["options"]}'
        line += "},"
        print(line)
    print("]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
