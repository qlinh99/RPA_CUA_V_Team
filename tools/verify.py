# -*- coding: utf-8 -*-
"""
VERIFICATION (maker-checker / R4): đối soát Google Form responses với dữ liệu NGUỒN.
"Đã submit" chưa phải "đã đúng" — chỉ bản ghi qua đối soát mới tính là verified.

Đọc:
  --responses : CSV responses của form. Có thể là:
       · file .csv tải về (Form → Responses → ⋮ → Download .csv), HOẶC
       · URL Google Sheet export, vd https://docs.google.com/spreadsheets/d/<ID>/export?format=csv
  --source    : CSV nguồn đúng (mặc định ground_truth.csv của bài tập)

Báo cáo: với mỗi hoá đơn nguồn -> verified / mismatch (kèm trường lệch) / missing. + cảnh báo trùng.

Chạy:
  py -3.11 verify.py --responses responses.csv
  py -3.11 verify.py --responses "https://docs.google.com/.../export?format=csv"
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _bootstrap  # .env, sys.path
import csv
import io
import argparse
import unicodedata

from core.ocr_to_form import normalize_date, normalize_vat, normalize_amount

DEFAULT_SOURCE = (Path(__file__).resolve().parent.parent.parent /
                  "Interns_Assignment" / "intern_assignments" / "answer_key" / "ground_truth.csv")

# (nhãn, cột nguồn ground_truth, nhãn cột trong responses, kiểu so sánh)
FIELD_MAP = [
    ("Số hoá đơn",        "so_hoa_don",      "Số hoá đơn",            "text"),
    ("Ký hiệu",           "ky_hieu",         "Ký hiệu hoá đơn",       "text"),
    ("Ngày lập",          "ngay_lap",        "Ngày lập",              "date"),
    ("Tên NCC",           "ten_nguoi_ban",   "Tên nhà cung cấp",      "text"),
    ("MST",               "mst_nguoi_ban",   "MST nhà cung cấp",      "digits"),
    ("Tiền trước thuế",   "cong_tien_hang",  "Tiền trước thuế",       "amount"),
    ("Thuế suất",         "thue_suat_pct",   "Thuế suất GTGT",        "vat"),
    ("Tổng thanh toán",   "tong_thanh_toan", "Tổng tiền thanh toán",  "amount"),
]
KEY_SRC, KEY_RESP = "so_hoa_don", "Số hoá đơn"   # khớp theo số hoá đơn


def _norm(kind: str, v) -> str:
    s = "" if v is None else str(v).strip()
    if kind == "date":
        return normalize_date(s) or s
    if kind == "vat":
        return normalize_vat(s) or s
    if kind == "amount":
        return normalize_amount(s) or ""
    if kind == "digits":
        return "".join(ch for ch in s if ch.isdigit())
    # text: NFC, gộp khoảng trắng, bỏ hoa/thường
    s = unicodedata.normalize("NFC", s).lower()
    return " ".join(s.split())


def _read_csv(src: str) -> list[dict]:
    if src.startswith("http"):
        import urllib.request
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", errors="replace")
    else:
        text = Path(src).read_text(encoding="utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _find_resp_col(headers, label):
    """Cột response khớp nhãn (chứa nhãn, không phân biệt hoa/thường)."""
    tl = label.lower()
    for h in headers:
        if tl in (h or "").lower():
            return h
    return None


def reconcile(source: list[dict], responses: list[dict]) -> dict:
    resp_headers = responses[0].keys() if responses else []
    col = {label: _find_resp_col(resp_headers, label) for _, _, label, _ in FIELD_MAP}
    key_col = _find_resp_col(resp_headers, KEY_RESP)

    # gom responses theo số hoá đơn (chuẩn hoá)
    by_key: dict[str, list[dict]] = {}
    for r in responses:
        k = _norm("text", r.get(key_col, "")) if key_col else ""
        by_key.setdefault(k, []).append(r)

    rows, n_ver, n_mis, n_missing, n_dup = [], 0, 0, 0, 0
    for srec in source:
        key = _norm("text", srec.get(KEY_SRC, ""))
        matches = by_key.get(key, [])
        if not matches:
            rows.append((srec.get(KEY_SRC), "missing", []))
            n_missing += 1
            continue
        if len(matches) > 1:
            n_dup += 1
        r = matches[-1]                       # bản nộp gần nhất
        diffs = []
        for label, scol, rlabel, kind in FIELD_MAP:
            a = _norm(kind, srec.get(scol, ""))
            b = _norm(kind, r.get(col.get(rlabel) or "", ""))
            if a != b:
                diffs.append((label, srec.get(scol, ""), r.get(col.get(rlabel) or "", "")))
        if diffs:
            rows.append((srec.get(KEY_SRC), "mismatch", diffs))
            n_mis += 1
        else:
            rows.append((srec.get(KEY_SRC), "verified", []))
            n_ver += 1

    return {"rows": rows, "verified": n_ver, "mismatch": n_mis,
            "missing": n_missing, "dup": n_dup, "total": len(source)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Đối soát Form responses với nguồn (maker-checker).")
    ap.add_argument("--responses", required=True, help="CSV responses (file .csv hoặc URL export)")
    ap.add_argument("--source", default=str(DEFAULT_SOURCE), help="CSV nguồn đúng (mặc định ground_truth.csv)")
    args = ap.parse_args()

    source = _read_csv(args.source)
    responses = _read_csv(args.responses)
    print(f"📥 Nguồn: {len(source)} hoá đơn  |  Responses: {len(responses)} dòng\n")

    rep = reconcile(source, responses)
    icon = {"verified": "✅", "mismatch": "⚠️", "missing": "⛔"}
    for key, status, diffs in rep["rows"]:
        print(f"{icon[status]} {key}  [{status}]")
        for label, src_v, resp_v in diffs:
            print(f"      • {label}: nguồn={src_v!r}  ≠  form={resp_v!r}")

    print(f"\n===== BÁO CÁO ĐỐI SOÁT =====")
    print(f"  verified : {rep['verified']}/{rep['total']}")
    print(f"  mismatch : {rep['mismatch']}")
    print(f"  missing  : {rep['missing']}")
    if rep["dup"]:
        print(f"  ⚠️ trùng : {rep['dup']} hoá đơn có >1 lần nộp")
    print("  → Chỉ 'verified' mới tính là điền đúng & đủ.")
    return 0 if rep["mismatch"] == 0 and rep["missing"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
