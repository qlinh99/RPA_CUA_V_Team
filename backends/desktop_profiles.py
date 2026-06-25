# -*- coding: utf-8 -*-
"""
Quản lý PROFILE cho các app desktop đích. Mỗi app = 1 file JSON trong profiles/.
Thêm app mới: copy profiles/_template.json → <ten>.json, điền (lấy auto_id bằng inspect_uia.py).

  list_profiles()      -> ['access', ...]
  load_profile(name)   -> dict {name, method, window_title, exe, fields, submit, amount_keys}
  schema(profile)      -> [{id, label, type}] cho autofill (id = key)
"""
from __future__ import annotations
import json
from pathlib import Path

DIR = Path(__file__).resolve().parent / "profiles"


def list_profiles() -> list[str]:
    if not DIR.exists():
        return []
    return sorted(p.stem for p in DIR.glob("*.json") if not p.stem.startswith("_"))


def load_profile(name: str) -> dict:
    p = DIR / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"Không thấy profile '{name}'. Có: {list_profiles() or '(chưa có)'}. "
            f"Tạo mới: copy profiles/_template.json -> profiles/{name}.json")
    prof = json.loads(p.read_text(encoding="utf-8"))
    # bỏ các khoá ghi chú (_help, _xxx_note)
    return {k: v for k, v in prof.items() if not k.startswith("_")}


def schema(profile: dict) -> list[dict]:
    """Schema cho autofill: id = key (OCR trích theo label)."""
    return [{"id": f["key"], "label": f["label"], "type": f.get("type", "text")}
            for f in profile["fields"]]
