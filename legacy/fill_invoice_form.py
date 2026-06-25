# -*- coding: utf-8 -*-
"""
Bậc 1 — gửi 1 hoá đơn lên Google Form bằng HTTP POST (KHÔNG mở trình duyệt).
Nhanh, ổn định. Đọc cấu hình trường từ form_config.py.

    from fill_invoice_form import submit_invoice
    submit_invoice(form_dict)
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests

from . import form_config as cfg


def _build_payload(inv: dict) -> dict:
    payload: dict = {}
    for f in cfg.FIELDS:
        val = inv.get(f["key"])
        if val in (None, ""):
            continue
        if f["type"] == "date":
            d, m, y = str(val).split("/")          # 'DD/MM/YYYY'
            payload[f"{f['entry']}_day"] = int(d)
            payload[f"{f['entry']}_month"] = int(m)
            payload[f"{f['entry']}_year"] = int(y)
        else:
            payload[f["entry"]] = str(val)
    return payload


def submit_invoice(inv: dict) -> bool:
    r = requests.post(cfg.POST_URL, data=_build_payload(inv), timeout=15)
    ok = r.status_code in (200, 302)
    print(f"[{'OK' if ok else 'FAIL'}] {inv.get('so_hoa_don')} -> HTTP {r.status_code}")
    return ok


if __name__ == "__main__":
    mau = {
        "so_hoa_don": "POST-0001", "ky_hieu": "1C25TAA", "ngay_lap": "18/06/2026",
        "ten_ncc": "Cong ty TNHH ABC", "mst_ncc": "0312345678",
        "dien_giai": "Test POST", "tien_truoc_thue": "1000000",
        "thue_suat": "8%", "tong_thanh_toan": "1080000",
    }
    submit_invoice(mau)
