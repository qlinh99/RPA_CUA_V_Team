# -*- coding: utf-8 -*-
"""
Cầu nối OCR -> Google Form.

Nhận kết quả OCR (JSON "structured" từ ocr_scripts/test_image_processing.py
hoặc dict theo cột ground_truth.csv) và chuyển thành dict đúng định dạng mà
fill_invoice_form.submit_invoice() yêu cầu, gồm:
  - chuẩn hoá ngày  -> DD/MM/YYYY
  - chuẩn hoá thuế  -> '0%' | '5%' | '8%' | '10%'
  - chuẩn hoá số    -> chuỗi chỉ gồm chữ số (bỏ '.', ',', '₫', 'VND' ...)

Dùng:
    from ocr_to_form import to_form_dict, parse_ocr_text
    form = to_form_dict(ocr_json)          # ocr_json: dict
    form = parse_ocr_text(result["text"])  # khi OCR trả chuỗi JSON
"""
from __future__ import annotations
import json
import re
import unicodedata

VAT_ALLOWED = {"0%", "5%", "8%", "10%"}

# Mỗi trường form -> danh sách khoá nguồn có thể gặp (structured JSON & ground_truth.csv)
FIELD_ALIASES: dict[str, list[str]] = {
    "so_hoa_don":      ["invoice_no", "so_hoa_don", "invoiceNumber", "so_hd"],
    "ky_hieu":         ["serial", "ky_hieu", "invoice_symbol"],
    "ngay_lap":        ["issue_date", "ngay_lap", "date"],
    "ten_ncc":         ["seller.name", "ten_nguoi_ban", "ten_ncc", "seller_name"],
    "mst_ncc":         ["seller.tax_code", "mst_nguoi_ban", "mst_ncc", "seller_tax_code"],
    "dien_giai":       ["dien_giai", "description", "noi_dung"],   # thường phải tự ghép từ line_items
    "tien_truoc_thue": ["subtotal", "cong_tien_hang", "tien_truoc_thue", "amount_before_tax"],
    "thue_suat":       ["vat_rate", "thue_suat_pct", "thue_suat", "vat"],
    "tong_thanh_toan": ["total", "tong_thanh_toan", "total_payment", "grand_total"],
}


# ── helpers truy cập khoá lồng nhau ("seller.name") ────────────────────────────
def _get(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _first(d: dict, keys: list[str]):
    for k in keys:
        v = _get(d, k) if "." in k else d.get(k)
        if v not in (None, "", []):
            return v
    return None


# ── chuẩn hoá NGÀY -> DD/MM/YYYY ───────────────────────────────────────────────
def normalize_date(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # bắt 3 cụm số trong chuỗi (kể cả "ngày 05 tháng 05 năm 2026")
    nums = re.findall(r"\d+", s)
    if len(nums) < 3:
        return None
    # ISO YYYY-MM-DD  vs  DD/MM/YYYY  -> phân biệt bằng cụm 4 chữ số đứng đầu
    if len(nums[0]) == 4:
        y, m, d = nums[0], nums[1], nums[2]
    else:
        d, m, y = nums[0], nums[1], nums[2]
    try:
        d, m, y = int(d), int(m), int(y)
    except ValueError:
        return None
    if y < 100:           # '26' -> 2026
        y += 2000
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    return f"{d:02d}/{m:02d}/{y:04d}"


# ── chuẩn hoá THUẾ SUẤT -> '0%'|'5%'|'8%'|'10%' ───────────────────────────────
def normalize_vat(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    # các nhãn không chịu thuế / không kê khai -> coi như 0%
    if any(k in s for k in ("kct", "không chịu", "khong chiu", "kkknt", "không kê", "khong ke")):
        return "0%"
    m = re.search(r"\d+(?:[.,]\d+)?", s)
    if not m:
        return None
    val = float(m.group(0).replace(",", "."))
    if val <= 1:          # 0.08 -> 8
        val *= 100
    val = int(round(val))
    cand = f"{val}%"
    return cand if cand in VAT_ALLOWED else None


# ── chuẩn hoá SỐ TIỀN -> chuỗi chỉ gồm chữ số ─────────────────────────────────
def normalize_amount(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return str(int(round(raw)))
    s = str(raw)
    s = unicodedata.normalize("NFKC", s)
    digits = re.sub(r"[^\d]", "", s)   # bỏ '.', ',', khoảng trắng, '₫', 'đ', 'VND'
    return digits or None


# ── ghép diễn giải từ line_items nếu nguồn không có sẵn 'dien_giai' ────────────
def _build_dien_giai(src: dict) -> str | None:
    items = src.get("line_items")
    if isinstance(items, list) and items:
        descs = [str(it.get("description")).strip()
                 for it in items if isinstance(it, dict) and it.get("description")]
        if descs:
            return "; ".join(descs)
    # fallback: loại chứng từ + tên người bán
    parts = [src.get("invoice_type") or src.get("loai_chung_tu"),
             _first(src, FIELD_ALIASES["ten_ncc"])]
    parts = [str(p).strip() for p in parts if p]
    return " - ".join(parts) if parts else None


def to_form_dict(src: dict, *, strict: bool = False) -> dict:
    """
    src: dict OCR (structured JSON) hoặc dict theo cột ground_truth.csv.
    strict=True -> raise nếu thiếu/không hợp lệ trường bắt buộc.
    Trả về dict có thêm khoá '_issues' liệt kê các trường cần kiểm tra tay.
    """
    out: dict = {}
    issues: list[str] = []

    out["so_hoa_don"]      = _first(src, FIELD_ALIASES["so_hoa_don"])
    out["ky_hieu"]         = _first(src, FIELD_ALIASES["ky_hieu"])
    out["ten_ncc"]         = _first(src, FIELD_ALIASES["ten_ncc"])
    out["mst_ncc"]         = _first(src, FIELD_ALIASES["mst_ncc"])

    out["ngay_lap"]        = normalize_date(_first(src, FIELD_ALIASES["ngay_lap"]))
    out["thue_suat"]       = normalize_vat(_first(src, FIELD_ALIASES["thue_suat"]))
    out["tien_truoc_thue"] = normalize_amount(_first(src, FIELD_ALIASES["tien_truoc_thue"]))
    out["tong_thanh_toan"] = normalize_amount(_first(src, FIELD_ALIASES["tong_thanh_toan"]))

    dg = _first(src, FIELD_ALIASES["dien_giai"]) or _build_dien_giai(src)
    out["dien_giai"] = str(dg).strip() if dg else None

    # các trường text giữ nguyên (chỉ strip)
    for k in ("so_hoa_don", "ky_hieu", "ten_ncc", "mst_ncc"):
        if out[k] is not None:
            out[k] = str(out[k]).strip()

    # kiểm tra thiếu / không hợp lệ
    for k, v in out.items():
        if v in (None, ""):
            issues.append(f"{k}: thiếu hoặc OCR không đọc được")
    if out["thue_suat"] is None and _first(src, FIELD_ALIASES["thue_suat"]) is not None:
        issues.append("thue_suat: giá trị không thuộc {0%,5%,8%,10%} -> cần xác nhận tay")

    out["_issues"] = issues
    if strict and issues:
        raise ValueError("Dữ liệu form chưa hợp lệ:\n  - " + "\n  - ".join(issues))
    return out


def parse_ocr_text(text: str, *, strict: bool = False) -> dict:
    """
    Nhận chuỗi text OCR (có thể bọc trong ```json ... ```), bóc JSON rồi chuyển.
    """
    if not text:
        raise ValueError("OCR text rỗng")
    t = text.strip()
    # bóc fence ```json ... ```
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    # nếu vẫn lẫn chữ, lấy đoạn { ... } ngoài cùng
    if not t.startswith("{"):
        brace = re.search(r"\{.*\}", t, re.S)
        if brace:
            t = brace.group(0)
    data = json.loads(t)
    return to_form_dict(data, strict=strict)


# ── self-test nhanh ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    mau_structured = {
        "serial": "1C26TSV",
        "invoice_no": "00002154",
        "issue_date": "2026-05-05",
        "seller": {"name": "CÔNG TY TNHH CHUYỂN PHÁT NHANH SAO VIỆT", "tax_code": "0101230004"},
        "line_items": [{"description": "Dịch vụ chuyển phát nhanh nội thành"}],
        "subtotal": 5585000,
        "vat_rate": "10%",
        "vat_amount": 558500,
        "total": 6143500,
    }
    from pprint import pprint
    pprint(to_form_dict(mau_structured))
    # vài case chuẩn hoá biên
    print(normalize_date("ngày 05 tháng 5 năm 2026"))   # 05/05/2026
    print(normalize_date("2026-05-05"))                  # 05/05/2026
    print(normalize_vat("0.08"), normalize_vat("KCT"), normalize_vat("8 %"))  # 8% 0% 8%
    print(normalize_amount("6.143.500 ₫"))               # 6143500
