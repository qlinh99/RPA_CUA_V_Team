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

  # điền + gửi (thêm --headed để xem trình duyệt)
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
import datetime as _dt
from pathlib import Path

from core.inspect_form import fetch_form
from core.doc_reader import file_to_pages
from core.ocr_engine import create_ocr_adapter
from core.ocr_to_form import normalize_date
from core import form_filler
from backends import excel_target


def _fid(f: dict) -> str:
    """Khoá định danh trường trong prompt/kết quả OCR (form: entry; excel: colN)."""
    return f.get("id") or f.get("entry") or f["label"]

# các kiểu trường tool biết điền
SUPPORTED = {"text", "paragraph", "date", "radio", "dropdown", "checkbox", "scale"}

# nơi lưu schema form đã soi (đỡ phải soi lại mỗi lần)
CACHE_DIR = Path(__file__).resolve().parent / "form_cache"
LAST_FORM_FILE = CACHE_DIR / "_last_form.txt"   # nhớ form dùng gần nhất

# ── Audit log ─────────────────────────────────────────────────────────────────
_AUDIT_LOG = Path(__file__).resolve().parent / "reports" / "audit.log"


def _audit_log(target: str, doc: str, ok: bool, detail: str = "") -> None:
    """Ghi 1 dòng vào audit.log — không bao giờ raise exception."""
    try:
        _AUDIT_LOG.parent.mkdir(exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "OK  " if ok else "FAIL"
        name = Path(doc).name if doc else "?"
        line = f"{ts} | {status} | {target:<10} | {name:<40} | {detail[:100]}\n"
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


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
    """Soi form mỗi phiên — không dùng cache file."""
    last = load_last_form()
    url = (arg_form or last or "").strip()
    if not url:
        raise SystemExit("⛔ Lần đầu chạy phải cung cấp --form <URL>. Các lần sau có thể bỏ trống để dùng form cũ.")

    if not arg_form:
        print(f"   ↩️  Không truyền --form → dùng FORM CŨ: {url}")

    schema = _inspect_and_cache(url)
    print("   💾 Đã soi form và lưu schema.")
    save_last_form(url)
    return schema


# ── Slug helpers (dùng cho prompt + fallback lookup) ──────────────────────────
def _to_ascii_slug(s: str) -> str:
    """Nhãn/key bất kỳ → ascii slug để so sánh mờ (bỏ dấu tiếng Việt, ký tự đặc biệt)."""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


_SLUG_STOPWORDS = {"va", "cua", "la", "de", "cac", "voi", "tren",
                   "theo", "hoac", "mot", "cung", "trong"}


def _slug_score(key: str, label: str) -> float:
    """Điểm tương đồng [0,1] giữa key CSV slug và nhãn form slug.

    Quy tắc (ưu tiên từ trên xuống):
    1. target slug khớp CHÍNH XÁC với một phần của key (vd: "bhyt" ∈ parts "so_the_bhyt") → 0.8
    2. Mọi phần 'distinctive' (len≥5) của key phải có trong nhãn → nếu không → 0
       (dùng len≥5 thay vì ≥4 để bỏ qua viết tắt 4 chữ như csvc, bhyt)
    3. Score = tỷ lệ phần key khớp nhãn (bỏ stopwords)
    """
    target_slug = _to_ascii_slug(label)
    k_parts_all = set(_to_ascii_slug(key).split("_"))

    # Quy tắc 1: target slug là ĐÚNG MỘT PHẦN của key (ví dụ: bhyt ∈ {so, the, bhyt})
    if target_slug in k_parts_all and len(target_slug) >= 3:
        return 0.8

    k_parts = [p for p in k_parts_all if p and p not in _SLUG_STOPWORDS]
    t_parts = set(target_slug.split("_")) - _SLUG_STOPWORDS
    if not k_parts or not t_parts:
        return 0.0

    # Quy tắc 2: từ đặc trưng len≥5 phải khớp (len≥5 bỏ qua viết tắt 4 chữ như csvc, bhxh)
    distinctive = [p for p in k_parts if len(p) >= 5]
    if distinctive and not all(p in t_parts for p in distinctive):
        return 0.0

    matching = sum(1 for p in k_parts if p in t_parts)
    return matching / len(k_parts)


def _raw_lookup(raw: dict, f: dict):
    """Lấy giá trị từ raw theo thứ tự ưu tiên:
    1. entry ID / id chính xác
    2. Nhãn field (LLM dùng label làm key)
    3. Slug khớp chính xác
    4. Slug khớp mờ (score ≥ 0.5) — bắt trường hợp LLM dùng key CSV ngắn gọn
    """
    # 1. Chính xác theo id/entry
    v = raw.get(_fid(f))
    if v not in (None, "", "null"):
        return v
    # 2. Theo nhãn nguyên bản
    v = raw.get(f["label"])
    if v not in (None, "", "null"):
        return v
    # 3 & 4. Slug match
    target_slug = _to_ascii_slug(f["label"])
    best_score, best_val = 0.0, None
    for k, kv in raw.items():
        if kv in (None, "", "null"):
            continue
        k_slug = _to_ascii_slug(str(k))
        if k_slug == target_slug:           # khớp chính xác → dùng ngay
            return kv
        sc = _slug_score(str(k), f["label"])
        if sc > best_score:
            best_score, best_val = sc, kv
    if best_score >= 0.5:
        return best_val
    return None


def _extract_md_headers(doc_text: str) -> "list[str]":
    """Bóc tên cột từ dòng đầu bảng markdown: '| col1 | col2 | ...'"""
    for line in doc_text.strip().splitlines():
        line = line.strip()
        if line.startswith("|") and "---" not in line:
            return [c.strip() for c in line.strip("|").split("|") if c.strip()]
    return []


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
        # Phát hiện bảng markdown (CSV/Excel) — tên cột có thể là viết tắt snake_case
        md_headers = _extract_md_headers(doc_text)
        if md_headers:
            # Xây bảng ánh xạ: cột CSV → id trường form (để LLM dùng đúng key)
            mappings = []
            for h in md_headers:
                best_f = max(fields, key=lambda f: _slug_score(h, f["label"]), default=None)
                if best_f and _slug_score(h, best_f["label"]) >= 0.4:
                    mappings.append(f'  "{h}" → id="{_fid(best_f)}" ({best_f["label"]})')
            if mappings:
                p += ("\nLƯU Ý — Tài liệu là bảng có cấu trúc, tên cột viết tắt tiếng Việt.\n"
                      "Ánh xạ suy luận (cột → id trường):\n"
                      + "\n".join(mappings)
                      + "\nDùng ĐÚNG id trường (entry.XXXXX) làm key JSON, KHÔNG dùng tên cột.\n")
    p += (
        "\nNếu chứng từ chứa NHIỀU bản ghi (bảng danh sách, nhiều phiếu, nhiều dòng dữ liệu), "
        "trả về JSON array [{...}, {...}]; nếu chỉ 1 bản ghi, trả về JSON object {...}.\n"
        "Chỉ in JSON thuần, không markdown, không giải thích."
    )
    return p


def _strip_json(text: str) -> str:
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    if not t.startswith("{") and not t.startswith("["):
        brace = re.search(r"[\[{].*[\]}]", t, re.S)
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
_ocr_cache: "dict[tuple, list[dict]]" = {}   # cache phiên: tránh OCR lại khi preview→submit


def _cache_key(doc_path: str, fields: "list[dict]") -> tuple:
    import os
    try:
        mtime = os.path.getmtime(doc_path)
    except OSError:
        mtime = 0
    fields_sig = hashlib.md5(
        json.dumps([_fid(f) for f in fields], ensure_ascii=False).encode()
    ).hexdigest()[:8]
    return (doc_path, mtime, fields_sig)


def extract_values(doc_path: str, fields: "list[dict]") -> "list[dict]":
    """OCR doc → danh sách bản ghi (thường 1; bảng/danh sách cho N).
    Kết quả được cache trong phiên — lần 2 (submit) dùng lại lần 1 (preview).
    """
    key = _cache_key(doc_path, fields)
    if key in _ocr_cache:
        print("  ⚡ Dùng kết quả OCR đã cache (bỏ qua OCR lần 2)")
        return _ocr_cache[key]

    pages = file_to_pages(doc_path)
    adapter = create_ocr_adapter()
    single_merged: dict = {}   # gộp các trang đơn-bản-ghi
    multi_records: list = []   # bảng ghi nhiều bản ghi phát hiện từ trang nào đó

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
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)]
            if len(records) > 1:
                print(f"  📋 Trang {idx}: phát hiện {len(records)} bản ghi")
                multi_records.extend(records)
            elif records:
                for k, v in records[0].items():
                    if v not in (None, "", "null") and single_merged.get(k) in (None, "", "null", None):
                        single_merged.setdefault(k, v)
        elif isinstance(data, dict):
            for k, v in data.items():
                if v not in (None, "", "null") and single_merged.get(k) in (None, "", "null", None):
                    single_merged.setdefault(k, v)

    result = multi_records if multi_records else [single_merged]
    if multi_records and single_merged:
        result.insert(0, single_merged)
    _ocr_cache[key] = result
    return result


def _normalize_record(raw: dict, fields: "list[dict]") -> "tuple[list, list]":
    """Chuẩn hoá 1 bản ghi raw → (items, issues).
    Dùng _raw_lookup thay raw.get() để xử lý LLM trả key CSV/nhãn thay vì entry ID."""
    items, issues, optional_empty = [], [], []
    for f in fields:
        val, err = normalize_value(_raw_lookup(raw, f), f)
        items.append({**f, "value": val})
        if val in (None, "", []):
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


def _extract_items(doc, fields: "list[dict]") -> "list[tuple[list, list]]":
    """OCR hoặc đọc dict → list[(items, issues)] — 1 phần tử nếu đơn bản ghi, N nếu nhiều.
    doc: str đường dẫn file.
    """
    print(f"\n🧾 OCR chứng từ: {doc}")
    raws = extract_values(doc, fields)
    if len(raws) > 1:
        print(f"  📋 Tổng: {len(raws)} bản ghi trong chứng từ")
    return [_normalize_record(raw, fields) for raw in raws]


def _remap_items(merged_items: "list[dict]", target_fields: "list[dict]") -> "list[dict]":
    """Ánh xạ merged_items sang target_fields theo nhãn, giữ nguyên value đã trích xuất."""
    val_by_label = {it["label"]: it["value"] for it in merged_items}
    return [{**f, "value": val_by_label.get(f["label"])} for f in target_fields]


def _submit_form_record(schema: dict, items: list, args, browser=None) -> int:
    """Gửi 1 bản ghi. browser: trình duyệt tái sử dụng (multi-record, None = tự tạo)."""
    pages = schema.get("pages", 1)
    if args.cua:
        from backends import cua_fallback
        print("\n🤖 CUA Gemini điền form (nhìn pixel)...")
        if pages > 1:
            print("   ⚠️  CUA chưa điều hướng nhiều trang — chỉ điền trang 1.")
        res = cua_fallback.cua_fill_web(schema["view_url"], items, headless=not args.headed)
        print(res)
        return 0 if res["ok"] else 1
    extra = f" (form {pages} trang — tự bấm 'Tiếp')" if pages > 1 else ""
    print(f"\n🌐 Bậc 3 — Playwright điền form{extra}...")
    shot = re.sub(r"[^0-9A-Za-z_-]", "_", str(items[0].get("value") or "form"))[:40]
    res = form_filler.fill_and_submit_browser(
        schema["view_url"], items, headless=not args.headed,
        slow_mo=200 if args.headed else 0, shot_name=shot,
        browser=browser,
    )
    if not res["ok"]:
        if browser is not None:
            # shared browser đang có sync_playwright() → không thể lồng thêm
            # Giải pháp: mở browser riêng tách biệt (browser=None tự tạo context mới)
            print(f"\n⚠️  Playwright thất bại ({res['error'][:60]})")
            print("   🔄 Thử lại với browser riêng (tách khỏi shared context)...")
            retry = form_filler.fill_and_submit_browser(
                schema["view_url"], items,
                headless=not args.headed,
                slow_mo=200 if args.headed else 0,
                shot_name=shot + "_retry",
                browser=None,
            )
            if retry["ok"]:
                res = retry
            else:
                print(f"   ⛔ Thử lại cũng thất bại: {retry['error'][:60]}")
        else:
            print(f"\n⚠️  Playwright thất bại ({res['error'][:60]}) → FALLBACK CUA Gemini...")
            from backends import cua_fallback
            res = cua_fallback.cua_fill_web(schema["view_url"], items, headless=not args.headed)
    print(res)
    doc_name = getattr(args, "doc", "?")
    _audit_log("gform", doc_name, res["ok"],
               res.get("error", "") or f"screenshot={res.get('screenshot','')}")
    return 0 if res["ok"] else 1


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

    all_records = _extract_items(args.doc, fields)
    n = len(all_records)
    if n > 1:
        print(f"\n📋 {n} bản ghi → sẽ gửi {n} lần")

    if not args.submit:
        print(f"\n💡 Chưa gửi ({n} bản ghi). Thêm --submit để điền lên form.")
        return 0

    codes = []

    def _run_records(shared_browser=None):
        for i, (items, issues) in enumerate(all_records, 1):
            if n > 1:
                print(f"\n  ══ Bản ghi {i}/{n} ══")
            if issues:
                print(f"⛔ Bản ghi {i}: còn trường không hợp lệ — bỏ qua.")
                codes.append(2)
                continue
            codes.append(_submit_form_record(schema, items, args, browser=shared_browser))

    if n > 1 and not args.cua:
        print(f"\n♻️  Tái sử dụng browser cho {n} bản ghi")
        with form_filler.browser_context(
            headless=not args.headed,
            slow_mo=200 if args.headed else 0,
        ) as shared_browser:
            _run_records(shared_browser)
    else:
        _run_records()

    ok = sum(1 for c in codes if c == 0)
    if n > 1:
        print(f"\n✅ {ok}/{n} bản ghi gửi thành công")
    return 0 if ok == n else 1



def run_access(args) -> int:
    from backends import desktop_filler, access_filler
    fields = desktop_filler.schema()
    print(f"\n🗄️  Microsoft Access ({len(fields)} ô) — điền qua COM")
    all_records = _extract_items(args.doc, fields)
    if not args.submit:
        print(f"\n💡 Chưa điền ({len(all_records)} bản ghi). Thêm --submit để điền vào form Access.")
        return 0
    codes = []
    for i, (items, issues) in enumerate(all_records, 1):
        if len(all_records) > 1:
            print(f"\n  ══ Bản ghi {i}/{len(all_records)} ══")
        if issues:
            print(f"⛔ Bản ghi {i}: còn trường không hợp lệ — bỏ qua.")
            codes.append(2); continue
        values = {it["id"]: it["value"] for it in items}
        out = access_filler.fill_access(values, submit=True)
        ok_ac = bool(out)
        print("\n✅ Đã điền vào form Access." if ok_ac
              else "\n⚠️  Access: không có trường nào được ghi.")
        _audit_log("access", args.doc, ok_ac,
                   "" if ok_ac else "fill_access trả dict rỗng")
        codes.append(0 if ok_ac else 1)
    print("Kiểm bảng HoaDon để đối chiếu.")
    return 0 if all(c == 0 for c in codes) else 1


def run_invoice(args) -> int:
    """Excel + Access với 1 lần OCR duy nhất (tránh kết quả khác nhau giữa 2 đích)."""
    from backends import desktop_filler, access_filler

    # ── Thu thập fields từng đích ────────────────────────────────────
    sheet_name, excel_fields = None, []
    if args.excel:
        print(f"\n📊 Báo cáo Excel: {args.excel}  (sheet: {args.sheet or 'mặc định'})")
        sheet_name, excel_fields = excel_target.inspect_excel(
            args.excel, args.sheet, args.header_row)
        print(f"   Sheet '{sheet_name}'  ({len(excel_fields)} cột)")

    access_fields = []
    if args.access:
        access_fields = desktop_filler.schema()
        print(f"\n🗄️  Microsoft Access ({len(access_fields)} ô) — điền qua COM")

    # ── Gộp fields theo nhãn → OCR 1 lần ───────────────────────────
    seen, merged = set(), []
    for f in excel_fields + access_fields:
        if f["label"] not in seen:
            merged.append(f)
            seen.add(f["label"])

    all_records = _extract_items(args.doc, merged)
    n = len(all_records)

    if not args.submit:
        print(f"\n💡 Chưa ghi ({n} bản ghi). Thêm --submit để ghi vào các đích.")
        return 0

    # ── Ghi vào từng đích ───────────────────────────────────────────
    codes = []
    for i, (merged_items, issues) in enumerate(all_records, 1):
        if n > 1:
            print(f"\n  ══ Bản ghi {i}/{n} ══")

        # [X1] Không bỏ qua issues như trước (_issues) — chặn nếu có lỗi bắt buộc
        if issues:
            print(f"⛔ Bản ghi {i}: còn trường không hợp lệ — bỏ qua.")
            for iss in issues:
                print(f"   - {iss}")
            _audit_log("invoice", args.doc, False, f"bản ghi {i}: {issues[0]}")
            codes.append(2)
            continue

        if excel_fields:
            xl_values = {it["id"]: it["value"]
                         for it in _remap_items(merged_items, excel_fields)}
            if args.watch:
                from backends import excel_com
                row = excel_com.append_row_visible(
                    args.excel, args.sheet, args.header_row,
                    excel_fields, xl_values, delay=0.6)
            else:
                row = excel_target.append_row(
                    args.excel, args.sheet, args.header_row, excel_fields, xl_values)
            print(f"\n✅ Excel: dòng {row} trong '{sheet_name}'")
            _audit_log("excel", args.doc, True, f"dòng {row} / {sheet_name}")
            codes.append(0)

        if access_fields:
            ac_values = {it["id"]: it["value"]
                         for it in _remap_items(merged_items, access_fields)}
            out = access_filler.fill_access(ac_values, submit=True)
            ok_ac = bool(out)
            print("\n✅ Access: Đã điền." if ok_ac else "\n⚠️  Access: không có trường nào được ghi.")
            _audit_log("access", args.doc, ok_ac,
                       "" if ok_ac else "fill_access trả dict rỗng")
            codes.append(0 if ok_ac else 1)

    return 0 if all(c == 0 for c in codes) else 1


def run_excel(args) -> int:
    print(f"\n📊 Báo cáo Excel: {args.excel}  (sheet: {args.sheet or 'mặc định'})")
    sheet_name, fields = excel_target.inspect_excel(args.excel, args.sheet, args.header_row)
    print(f"   Sheet '{sheet_name}'  ({len(fields)} cột)")

    all_records = _extract_items(args.doc, fields)
    if not args.submit:
        print(f"\n💡 Chưa ghi ({len(all_records)} bản ghi). Thêm --submit để thêm dòng vào báo cáo.")
        return 0
    rows_added = []
    for i, (items, _issues) in enumerate(all_records, 1):
        if len(all_records) > 1:
            print(f"\n  ══ Bản ghi {i}/{len(all_records)} ══")
        values = {it["id"]: it["value"] for it in items}
        if args.watch:
            print("\n👁️  Mở Excel để xem điền trực tiếp (win32com)...")
            from backends import excel_com
            row = excel_com.append_row_visible(args.excel, args.sheet, args.header_row,
                                               fields, values, delay=0.6)
        else:
            row = excel_target.append_row(args.excel, args.sheet, args.header_row, fields, values)
        print(f"\n✅ Đã thêm vào dòng {row} của '{sheet_name}'")
        _audit_log("excel", args.doc, True, f"dòng {row} / {sheet_name}")
        rows_added.append(row)
    if len(rows_added) > 1:
        print(f"\n✅ Tổng: {len(rows_added)} dòng thêm vào '{sheet_name}' trong {args.excel}")
    return 0


EPILOG = """\
VÍ DỤ (mặc định CHỈ trích xuất xem trước; thêm --submit mới thực sự ghi/gửi):

  Google Form : py -3.11 autofill.py --form "https://forms.gle/XXX" --doc hd.pdf --submit
                py -3.11 autofill.py --doc hd2.pdf --submit          (dùng lại form cũ)
  Excel       : py -3.11 autofill.py --excel bao_cao.xlsx --doc hd.pdf --submit [--watch]
  Access      : py -3.11 autofill.py --access --doc hd.pdf --submit
Chọn ĐÚNG 1 đích. Không có đích + không có form cũ -> báo lỗi.
"""


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="autofill.py",
        description="Tool RPA: OCR chứng từ (ảnh/PDF) -> điền vào 1 đích "
                    "(Google Form / Excel / Access).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--doc", required=True, help="Đường dẫn ảnh hoặc PDF chứng từ (BẮT BUỘC)")

    g = ap.add_argument_group("Đích (chọn 1)")
    g.add_argument("--form", default=None,
                   help="URL Google Form. Bỏ trống = dùng form cũ; URL khác = tự soi lại")
    g.add_argument("--excel", default=None, help="File .xlsx báo cáo (mỗi chứng từ = 1 dòng)")
    g.add_argument("--access", action="store_true", help="Form Microsoft Access (qua COM)")

    f = ap.add_argument_group("Tuỳ chọn theo đích")
    f.add_argument("--headed", action="store_true", help="(Form) hiện trình duyệt + chạy chậm")
    f.add_argument("--refresh", action="store_true", help="(Form) ép soi lại form")
    f.add_argument("--sheet", default=None, help="(Excel) tên sheet")
    f.add_argument("--header-row", type=int, default=1, dest="header_row", help="(Excel) dòng tiêu đề")
    f.add_argument("--watch", action="store_true", help="(Excel) mở Excel thật xem điền (win32com)")
    f.add_argument("--cua", action="store_true",
                   help="(Form) ép dùng CUA Gemini (nhìn pixel) thay Playwright")

    ap.add_argument("--submit", action="store_true",
                    help="Thực sự ghi/gửi (mặc định chỉ trích xuất xem trước)")
    args = ap.parse_args()

    if args.access:
        return run_access(args)
    if args.excel:
        return run_excel(args)
    return run_form(args)


if __name__ == "__main__":
    raise SystemExit(main())
