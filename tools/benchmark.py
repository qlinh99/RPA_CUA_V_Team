# -*- coding: utf-8 -*-
"""
ĐO SỐ LIỆU 3 bậc điền Google Form trên cùng bộ hoá đơn.
OCR 1 lần/hoá đơn (chung), rồi đo RIÊNG thời gian ĐIỀN từng bậc + tỉ lệ thành công.

Bậc:
  post       = Bậc 1 — HTTP POST (không trình duyệt)
  playwright = Bậc 3 — Playwright (DOM)
  cua        = Bậc 4 — CUA Gemini (nhìn pixel)

Chạy:
  py -3.11 benchmark.py --form "https://forms.gle/XXX" ^
     --docs "..\Interns_Assignment\sample_documents\hoa_don\*.pdf" --tiers post,playwright --limit 3
  (thêm cua vào --tiers để đo Bậc 4 — chậm + tốn token, nên ít hoá đơn)

LƯU Ý: mỗi lần điền là 1 dòng THẬT nộp vào form. Sau đó dùng verify.py để lấy tỉ lệ verified.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _bootstrap
import glob
import time
import argparse
import statistics as st

import autofill
from core import form_filler


def _fill(tier: str, schema: dict, items: list) -> bool:
    if tier == "post":
        return form_filler.submit_post(schema["post_url"], items)
    if tier == "playwright":
        r = form_filler.fill_and_submit_browser(schema["view_url"], items,
                                                headless=True, shot_name="bench")
        return r["ok"]
    if tier == "cua":
        from backends import cua_fallback
        r = cua_fallback.cua_fill_web(schema["view_url"], items, headless=True)
        return r["ok"]
    raise ValueError(tier)


def main() -> int:
    ap = argparse.ArgumentParser(description="Đo 3 bậc điền form.")
    ap.add_argument("--form", required=True)
    ap.add_argument("--docs", required=True, help="glob tới ảnh/PDF, vd \"...\\hoa_don\\*.pdf\"")
    ap.add_argument("--tiers", default="post,playwright", help="post,playwright,cua")
    ap.add_argument("--limit", type=int, default=3, help="số hoá đơn tối đa")
    args = ap.parse_args()

    docs = sorted(glob.glob(args.docs))[: args.limit]
    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    if not docs:
        print("⛔ Không thấy hoá đơn khớp --docs")
        return 1

    schema = autofill.resolve_schema(args.form)
    fields = [f for f in schema["fields"] if f["type"] in autofill.SUPPORTED]
    print(f"📋 Form '{schema['title']}' · {len(fields)} trường · {len(docs)} hoá đơn · bậc: {tiers}\n")

    # OCR 1 lần/hoá đơn (chung cho mọi bậc)
    prepared = []
    for d in docs:
        t0 = time.perf_counter()
        items, issues = autofill._extract_items(d, fields)
        ocr_t = time.perf_counter() - t0
        prepared.append((d, items, issues, ocr_t))

    ocr_avg = st.mean(p[3] for p in prepared)
    results = {t: {"times": [], "ok": 0, "n": 0} for t in tiers}

    for tier in tiers:
        print(f"\n===== BẬC: {tier} =====")
        for d, items, issues, _ot in prepared:
            name = d.split("\\")[-1].split("/")[-1]
            if issues:
                print(f"  ⏭️  {name}: thiếu trường, bỏ qua")
                continue
            t0 = time.perf_counter()
            try:
                ok = _fill(tier, schema, items)
            except Exception as e:
                ok = False
                print(f"  ✗ {name}: lỗi {e}")
            dt = time.perf_counter() - t0
            results[tier]["times"].append(dt)
            results[tier]["ok"] += int(ok)
            results[tier]["n"] += 1
            print(f"  {'✓' if ok else '✗'} {name}: {dt:.1f}s")

    print(f"\n\n===== BẢNG SỐ LIỆU (OCR chung ~{ocr_avg:.1f}s/hoá đơn) =====")
    print(f"{'Bậc':<12}{'n':<4}{'TG điền TB':<12}{'min–max':<14}{'Thành công'}")
    print("-" * 56)
    label = {"post": "1 POST", "playwright": "3 Playwright", "cua": "4 CUA"}
    for t in tiers:
        r = results[t]
        if not r["times"]:
            continue
        avg = st.mean(r["times"])
        lo, hi = min(r["times"]), max(r["times"])
        print(f"{label.get(t,t):<12}{r['n']:<4}{avg:>6.1f}s     {lo:>4.1f}–{hi:<4.1f}s   {r['ok']}/{r['n']}")
    print("\n→ Tải responses rồi chạy verify.py để có tỉ lệ VERIFIED (đúng & đủ) từng bậc.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
