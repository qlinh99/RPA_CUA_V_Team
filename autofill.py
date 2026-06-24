# -*- coding: utf-8 -*-
"""
TOOL HỢP NHẤT — điền BẤT KỲ Google Form nào từ BẤT KỲ chứng từ (ảnh/PDF) nào.

Luồng:
  nhận FORM  ─► soi form, lấy các trường cần điền (nhãn/kiểu/lựa chọn)
  nhận DOC   ─► OCR (ảnh hoặc PDF)
             ─► bảo LLM trích ĐÚNG những trường form cần từ chứng từ
             ─► chuẩn hoá theo kiểu trường (ngày, lựa chọn...)
             ─► điền vào form (trình duyệt) hoặc gửi POST

Không gắn cứng loại chứng từ — chính FORM quyết định cần trích xuất gì.

CÁCH CHẠY (Python 3.11):
  # xem form cần gì + OCR trích được gì, KHÔNG gửi:
  py -3.11 autofill.py --form <URL_FORM> --doc "đường_dẫn\\chungtu.pdf"

  # điền + gửi (thêm --headed để xem trình duyệt; --post để dùng HTTP thay trình duyệt)
  py -3.11 autofill.py --form <URL> --doc "...\\anh.jpg" --submit --headed
"""
from __future__ import annotations
import _bootstrap  # temp->D:, .env, sys.path
import sys
import re
import json
import hashlib
import argparse
import unicodedata
from pathlib import Path

from inspect_form import fetch_form
from doc_reader import file_to_pages
from test_image_processing import create_ocr_adapter
from ocr_to_form import normalize_date
import form_filler
import excel_target


def _fid(f: dict) -> str:
    """Khoá định danh trường trong prompt/kết quả OCR (form: entry; excel: colN)."""
    return f.get("id") or f.get("entry") or f["label"]

# các kiểu trường tool biết điền
SUPPORTED = {"text", "paragraph", "date", "radio", "dropdown", "checkbox", "scale"}

# nơi lưu schema form đã soi (đỡ phải soi lại mỗi lần)
CACHE_DIR = Path(__file__).resolve().parent / "form_cache"
LAST_FORM_FILE = CACHE_DIR / "_last_form.txt"   # nhớ form dùng gần nhất


def _cache_path(url: str) -> Path:
    key = hashlib.md5(url.strip().encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{key}.json"


def load_schema(url: str) -> "dict | None":
    p = _cache_path(url)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_schema(url: str, schema: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    _cache_path(url).write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")


def load_last_form() -> "str | None":
    if LAST_FORM_FILE.exists():
        return LAST_FORM_FILE.read_text(encoding="utf-8").strip() or None
    return None


def save_last_form(url: str) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    LAST_FORM_FILE.write_text(url.strip(), encoding="utf-8")


def _inspect_and_cache(url: str) -> dict:
    title, fields, view_url, pages = fetch_form(url)
    schema = {
        "title": title,
        "fields": fields,
        "view_url": view_url,
        "post_url": re.sub(r"/viewform.*$", "/formResponse", view_url),
        "pages": pages,
    }
    save_schema(url, schema)
    return schema


def resolve_schema(arg_form: "str | None", refresh: bool = False) -> dict:
    """
    Quyết định dùng form nào + có cần soi lại không.
      - arg_form trống     -> dùng FORM CŨ (form gần nhất), không soi lại.
      - arg_form == cũ     -> dùng schema đã lưu.
      - arg_form ĐỔI       -> soi lại lấy trường mới.
      - --refresh          -> ép soi lại.
    """
    last = load_last_form()
    url = (arg_form or last or "").strip()
    if not url:
        raise SystemExit("⛔ Lần đầu chạy phải cung cấp --form <URL>. Các lần sau có thể bỏ trống để dùng form cũ.")

    if not arg_form:
        print(f"   ↩️  Không truyền --form → dùng FORM CŨ: {url}")

    changed = bool(arg_form) and bool(last) and arg_form.strip() != last
    cached = None if (refresh or changed) else load_schema(url)
    if cached and "pages" not in cached:        # cache cũ (trước khi thêm đếm trang) -> soi lại
        cached = None

    if cached:
        print("   ⚡ Form không đổi → dùng schema đã lưu (bỏ qua soi form).")
        schema = cached
    else:
        if changed:
            print("   🔄 Form THAY ĐỔI so với lần trước → soi lại lấy các trường mới.")
        elif refresh:
            print("   🔄 --refresh → soi lại form.")
        schema = _inspect_and_cache(url)
        print("   💾 Đã soi form và lưu schema.")

    save_last_form(url)
    return schema


# ── prompt động: sinh từ chính các trường của form ────────────────────────────
def build_prompt(fields: "list[dict]", doc_text: "str | None") -> str:
    lines = []
    for f in fields:
        d = f'- id="{_fid(f)}" | nhãn="{f["label"]}" | kiểu={f["type"]}'
        if f["type"] == "date":
            d += " | ĐỊNH DẠNG NGÀY: DD/MM/YYYY"
        if f.get("options"):
            d += f' | CHỌN ĐÚNG 1 trong: {f["options"]}'
        lines.append(d)
    schema = "\n".join(lines)
    p = (
        "Bạn nhận một chứng từ (hoá đơn / biểu mẫu / giấy tờ). Hãy TRÍCH XUẤT giá trị "
        "cho đúng các trường dưới đây và CHỈ trả về JSON dạng {id: giá_trị}.\n"
        "Trường nào không có thông tin LIÊN QUAN trong chứng từ thì để null.\n\n"
        f"CÁC TRƯỜNG CẦN TRÍCH:\n{schema}\n\n"
        "Quy tắc:\n"
        "- Chép chính xác con số (không tự tính lại, không làm tròn); ngày theo DD/MM/YYYY; "
        "trường có lựa chọn phải trả đúng một trong các option cho sẵn; giữ nguyên dấu tiếng Việt.\n"
        "- Với trường MÔ TẢ/DIỄN GIẢI/NỘI DUNG/HÀNG HOÁ–DỊCH VỤ: nếu chứng từ không có ô ghi sẵn, "
        "hãy TỔNG HỢP từ BẢNG KÊ hàng hoá/dịch vụ — liệt kê tên các mặt hàng/dịch vụ, nối bằng '; '. "
        "Chỉ để null khi thật sự không có dòng hàng nào. KHÔNG bịa thông tin không có trong chứng từ.\n"
    )
    if doc_text is not None:
        p += f"\nNỘI DUNG VĂN BẢN CHỨNG TỪ:\n----------\n{doc_text}\n"
    p += "\nChỉ in JSON thuần, không markdown, không giải thích."
    return p


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


# ── chuẩn hoá giá trị theo kiểu trường ────────────────────────────────────────
def _skeleton(s) -> str:
    s = unicodedata.normalize("NFC", str(s)).lower()
    return re.sub(r"[^0-9a-zđ%]", "", s)


def _match_option(val, options: list) -> "str | None":
    if val is None:
        return None
    sv = _skeleton(val)
    for o in options:               # khớp chính xác sau khi chuẩn hoá
        if _skeleton(o) == sv:
            return o
    sv2 = sv.rstrip("%")
    for o in options:               # khớp lỏng (bỏ %): '10' ~ '10%'
        if _skeleton(o).rstrip("%") == sv2 and sv2:
            return o
    return None


def normalize_value(val, field: dict):
    """Trả (giá_trị_đã_chuẩn, ghi_chú_lỗi|None)."""
    if val in (None, "", "null"):
        return None, None
    t = field["type"]
    if t == "date":
        nd = normalize_date(val)
        return nd, (None if nd else f"ngày '{val}' không đọc được")
    if t in ("radio", "dropdown", "scale", "checkbox"):
        opts = field.get("options") or []
        if t == "checkbox" and isinstance(val, list):
            matched = [_match_option(v, opts) for v in val]
            matched = [m for m in matched if m]
            return (matched or None), (None if matched else f"không khớp lựa chọn {opts}")
        m = _match_option(val, opts)
        return m, (None if m else f"'{val}' không khớp lựa chọn {opts}")
    return str(val).strip(), None


# ── OCR chứng từ theo schema của form ─────────────────────────────────────────
def extract_values(doc_path: str, fields: "list[dict]") -> dict:
    pages = file_to_pages(doc_path)
    adapter = create_ocr_adapter()
    merged: dict = {}
    for idx, page in enumerate(pages, 1):
        if page[0] == "text":
            result = adapter.ocr([], prompt=build_prompt(fields, page[1]))
        else:
            _, b64, size = page
            result = adapter.ocr(b64, prompt=build_prompt(fields, None), image_sizes=[size])
        if not result.get("success"):
            print(f"  ⚠️  Trang {idx} OCR lỗi: {result.get('error')}")
            continue
        try:
            data = json.loads(_strip_json(result["text"]))
        except Exception as e:
            print(f"  ⚠️  Trang {idx} không phải JSON: {e}")
            continue
        for k, v in data.items():            # gộp: lấy giá trị hợp lệ đầu tiên
            if v not in (None, "", "null") and merged.get(k) in (None, "", "null", None):
                merged.setdefault(k, v)
    return merged


def _extract_items(doc: str, fields: "list[dict]"):
    """OCR chứng từ + chuẩn hoá -> (items có 'value', danh sách issues)."""
    print(f"\n🧾 OCR chứng từ: {doc}")
    raw = extract_values(doc, fields)
    items, issues, optional_empty = [], [], []
    for f in fields:
        val, err = normalize_value(raw.get(_fid(f)), f)
        items.append({**f, "value": val})
        if val in (None, "", []):
            # CHỈ chặn nếu trường BẮT BUỘC; trường tùy chọn để trống là hợp lệ.
            if f.get("required"):
                issues.append(f"{f['label']}: BẮT BUỘC nhưng trống"
                              + (f" ({err})" if err else ""))
            else:
                optional_empty.append(f["label"])
        elif err:
            issues.append(f"{f['label']}: {err}")
    print("\n📋 Giá trị trích xuất:")
    for it in items:
        req = " *" if it.get("required") else ""
        print(f"   • {it['label']:<24}{req} = {it['value']!r}")
    if optional_empty:
        print("\nℹ️  Trường tùy chọn để trống (bỏ qua, không chặn): "
              + ", ".join(optional_empty))
    if issues:
        print("\n⚠️  Cần kiểm tra tay (chặn gửi):")
        for i in issues:
            print(f"   - {i}")
    return items, issues


def run_form(args) -> int:
    print(f"\n🔎 Form: {args.form or '(dùng form cũ)'}")
    schema = resolve_schema(args.form, refresh=args.refresh)
    fields = schema["fields"]
    print(f"   {schema['title']}  ({len(fields)} trường)")

    skipped = [f for f in fields if f["type"] not in SUPPORTED]
    fields = [f for f in fields if f["type"] in SUPPORTED]
    for f in skipped:
        warn = " ⚠️ BẮT BUỘC → Google sẽ chặn gửi!" if f.get("required") else ""
        print(f"   ⏭️  Bỏ qua trường kiểu '{f['type']}' (chưa hỗ trợ): {f['label']}{warn}")

    items, issues = _extract_items(args.doc, fields)

    if not args.submit:
        print("\n💡 Chưa gửi. Thêm --submit để điền lên form.")
        return 0
    if issues:
        print("\n⛔ Còn trường trống/không hợp lệ — KHÔNG tự gửi (maker–checker).")
        return 2

    pages = schema.get("pages", 1)
    if args.post:
        print(f"\n📮 Gửi bằng HTTP POST... ({pages} trang)")
        return 0 if form_filler.submit_post(schema["post_url"], items, pages=pages) else 1

    # Ép CUA ngay (Bậc 4) nếu --cua
    if args.cua:
        import cua_fallback
        print("\n🤖 CUA Gemini điền form (nhìn pixel)...")
        if pages > 1:
            print("   ⚠️  CUA chưa điều hướng nhiều trang — chỉ điền trang 1.")
        res = cua_fallback.cua_fill_web(schema["view_url"], items, headless=not args.headed)
        print(res)
        return 0 if res["ok"] else 1

    extra = f" (form {pages} trang — tự bấm 'Tiếp')" if pages > 1 else ""
    print(f"\n🌐 Bậc 3 — Playwright điền form{extra}...")
    shot = re.sub(r"[^0-9A-Za-z_-]", "_", (items[0]["value"] or "form"))[:40]
    res = form_filler.fill_and_submit_browser(
        schema["view_url"], items, headless=not args.headed,
        slow_mo=700 if args.headed else 0, shot_name=shot,
    )
    if not res["ok"]:
        print(f"\n⚠️  Playwright thất bại ({res['error'][:60]}) → FALLBACK Bậc 4 CUA Gemini...")
        import cua_fallback
        res = cua_fallback.cua_fill_web(schema["view_url"], items, headless=not args.headed)
    print(res)
    return 0 if res["ok"] else 1


def run_app(args) -> int:
    import desktop_filler as D
    fields = D.schema()
    if not fields:
        print("⛔ Chưa cấu hình FIELDS trong desktop_filler.py.")
        print("   Soi app:  py -3.11 inspect_uia.py \"<tên app>\" --all  rồi điền auto_id.")
        return 1
    print(f"\n🖥️  App desktop: '{D.WINDOW_TITLE}'  ({len(fields)} ô)")
    items, issues = _extract_items(args.doc, fields)

    if not args.submit:
        print("\n💡 Chưa điền. Thêm --submit để điền vào app.")
        return 0
    if issues:
        print("\n⛔ Còn trường trống/không hợp lệ — KHÔNG tự điền (maker–checker).")
        return 2

    values = {it["id"]: it["value"] for it in items}
    D.fill_desktop(values, submit=True)
    print("\n✅ Đã điền vào app desktop (kiểm cột [✓]/[≠] để đối chiếu).")
    return 0


def run_profile(args) -> int:
    import desktop_profiles
    try:
        prof = desktop_profiles.load_profile(args.profile)
    except FileNotFoundError as e:
        print(f"⛔ {e}")
        return 1
    fields = desktop_profiles.schema(prof)
    method = prof.get("method", "uia")
    print(f"\n🖥️  App: {prof.get('name', args.profile)}  ({len(fields)} ô, bậc={method.upper()})")
    items, issues = _extract_items(args.doc, fields)

    if not args.submit:
        print("\n💡 Chưa điền. Thêm --submit để điền vào app.")
        return 0
    if issues:
        print("\n⛔ Còn trường trống/không hợp lệ — KHÔNG tự điền (maker–checker).")
        return 2

    values = {it["id"]: it["value"] for it in items}
    if method == "com":
        import access_filler
        access_filler.fill_access(values, profile=prof)
    else:
        import desktop_filler
        desktop_filler.fill_desktop(values, submit=True, profile=prof)
    print("\n✅ Đã điền vào app theo profile.")
    return 0


def run_zalo(args) -> int:
    if not args.to:
        print('⛔ Cần --to "Tên người" để gửi Zalo. VD: --zalo --to "My Documents"')
        return 1
    import zalo_send_invoice as Z
    return Z.run(args.to, args.doc, do_send=args.submit)   # --submit = thực sự gửi


def run_access(args) -> int:
    import desktop_filler
    import access_filler
    fields = desktop_filler.schema()
    print(f"\n🗄️  Microsoft Access ({len(fields)} ô) — điền qua COM")
    items, issues = _extract_items(args.doc, fields)
    if not args.submit:
        print("\n💡 Chưa điền. Thêm --submit để điền vào form Access.")
        return 0
    if issues:
        print("\n⛔ Còn trường trống/không hợp lệ — KHÔNG tự điền (maker–checker).")
        return 2
    values = {it["id"]: it["value"] for it in items}
    access_filler.fill_access(values, submit=True)
    print("\n✅ Đã điền vào form Access. Kiểm bảng HoaDon để đối chiếu.")
    return 0


def run_excel(args) -> int:
    print(f"\n📊 Báo cáo Excel: {args.excel}  (sheet: {args.sheet or 'mặc định'})")
    sheet_name, fields = excel_target.inspect_excel(args.excel, args.sheet, args.header_row)
    print(f"   Sheet '{sheet_name}'  ({len(fields)} cột)")

    items, _issues = _extract_items(args.doc, fields)

    if not args.submit:
        print("\n💡 Chưa ghi. Thêm --submit để thêm dòng vào báo cáo.")
        return 0

    values = {it["id"]: it["value"] for it in items}
    if args.watch:
        print("\n👁️  Mở Excel để xem điền trực tiếp (win32com)...")
        import excel_com
        row = excel_com.append_row_visible(args.excel, args.sheet, args.header_row,
                                           fields, values, delay=0.6)
    else:
        row = excel_target.append_row(args.excel, args.sheet, args.header_row, fields, values)
    print(f"\n✅ Đã thêm dữ liệu vào dòng {row} của '{sheet_name}' trong {args.excel}")
    return 0


EPILOG = """\
VÍ DỤ (mặc định CHỈ trích xuất xem trước; thêm --submit mới thực sự ghi/gửi):

  Google Form : py -3.11 autofill.py --form "https://forms.gle/XXX" --doc hd.pdf --submit
                py -3.11 autofill.py --doc hd2.pdf --submit          (dùng lại form cũ)
  Excel       : py -3.11 autofill.py --excel bao_cao.xlsx --doc hd.pdf --submit [--watch]
  Access      : py -3.11 autofill.py --access --doc hd.pdf --submit
  App desktop : py -3.11 autofill.py --app --doc hd.pdf --submit     (cấu hình desktop_filler.py)
  Zalo        : py -3.11 autofill.py --zalo --to "My Documents" --doc hd.pdf --submit

Chọn ĐÚNG 1 đích. Không có đích + không có form cũ -> báo lỗi.
"""


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="autofill.py",
        description="Tool RPA: OCR chứng từ (ảnh/PDF) -> điền vào 1 đích "
                    "(Google Form / Excel / Access / App desktop / Zalo).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--doc", required=True, help="Đường dẫn ảnh hoặc PDF chứng từ (BẮT BUỘC)")

    g = ap.add_argument_group("Đích (chọn 1)")
    g.add_argument("--form", default=None,
                   help="URL Google Form. Bỏ trống = dùng form cũ; URL khác = tự soi lại")
    g.add_argument("--excel", default=None, help="File .xlsx báo cáo (mỗi chứng từ = 1 dòng)")
    g.add_argument("--access", action="store_true", help="Form Microsoft Access (qua COM)")
    g.add_argument("--app", action="store_true", help="App desktop qua UIA (app không có API, vd OH)")
    g.add_argument("--profile", default=None, help="Điền theo profile app trong profiles/<tên>.json (đa-app)")
    g.add_argument("--zalo", action="store_true", help="Gửi hoá đơn vào chat Zalo của người --to")

    f = ap.add_argument_group("Tuỳ chọn theo đích")
    f.add_argument("--post", action="store_true", help="(Form) gửi HTTP POST thay vì trình duyệt")
    f.add_argument("--headed", action="store_true", help="(Form) hiện trình duyệt + chạy chậm")
    f.add_argument("--refresh", action="store_true", help="(Form) ép soi lại form")
    f.add_argument("--sheet", default=None, help="(Excel) tên sheet")
    f.add_argument("--header-row", type=int, default=1, dest="header_row", help="(Excel) dòng tiêu đề")
    f.add_argument("--watch", action="store_true", help="(Excel) mở Excel thật xem điền (win32com)")
    f.add_argument("--to", default=None, help="(Zalo) tên người nhận trong danh bạ")
    f.add_argument("--cua", action="store_true",
                   help="(Form) ép dùng CUA Gemini (nhìn pixel) thay Playwright")

    ap.add_argument("--submit", action="store_true",
                    help="Thực sự ghi/gửi (mặc định chỉ trích xuất xem trước)")
    args = ap.parse_args()

    if args.profile:
        return run_profile(args)
    if args.zalo:
        return run_zalo(args)
    if args.access:
        return run_access(args)
    if args.app:
        return run_app(args)
    if args.excel:
        return run_excel(args)
    return run_form(args)


if __name__ == "__main__":
    raise SystemExit(main())
