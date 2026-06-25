# -*- coding: utf-8 -*-
"""
SOI CÂY UIA của một app Windows — để biết tên/ID từng ô nhập trước khi điền.
Tương đương Accessibility Insights nhưng bằng Python (pywinauto-UIA).

Cài: py -3.11 -m pip install pywinauto

Dùng:
    # 1) Liệt kê các cửa sổ đang mở (lấy đúng title để soi):
    py -3.11 inspect_uia.py

    # 2) Soi 1 cửa sổ theo title (khớp 1 phần, không phân biệt hoa/thường):
    py -3.11 inspect_uia.py "Tên cửa sổ app"

In ra mọi control TƯƠNG TÁC ĐƯỢC (ô nhập, combobox, checkbox, radio, nút) kèm:
  ControlType | AutomationId | Name | có ValuePattern? (điền set-value được không)
và sinh sẵn khối CONTROLS để dán vào desktop_config (sẽ viết sau).
"""
import sys


def list_windows():
    from pywinauto import Desktop
    print("📋 Các cửa sổ cấp cao đang mở (lấy 'title' để soi):\n")
    seen = set()
    for w in Desktop(backend="uia").windows():
        try:
            t = w.window_text()
            if t and t not in seen:
                seen.add(t)
                print(f"   • {t}")
        except Exception:
            pass
    print('\n→ Chạy lại: py -3.11 inspect_uia.py "<một phần title>"')


# kiểu control quan tâm -> kiểu trường trong tool
CTRL_MAP = {
    "Edit": "text", "Document": "paragraph", "ComboBox": "dropdown",
    "CheckBox": "checkbox", "RadioButton": "radio", "Button": "button",
}


def _slug(s: str) -> str:
    import re, unicodedata
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "field"


def inspect(title: str, show_all: bool = False):
    from pywinauto import Desktop
    win = Desktop(backend="uia").window(title_re=f"(?i).*{title}.*")
    win.wait("exists", timeout=10)
    print(f"\n🪟 Cửa sổ: {win.window_text()}\n")

    if show_all:
        # In MỌI control (không lọc) — để tìm ô soạn tin / control lạ
        print(f"{'#':<4}{'TYPE':<16}{'VIS':<4}{'AUTO_ID':<26}NAME")
        print("-" * 90)
        for i, ctrl in enumerate(win.descendants(), 1):
            info = ctrl.element_info
            try:
                vis = "Y" if ctrl.is_visible() else "."
            except Exception:
                vis = "?"
            print(f"{i:<4}{str(info.control_type)[:15]:<16}{vis:<4}"
                  f"{(info.automation_id or '')[:25]:<26}{(info.name or '')[:40]}")
        return

    print(f"{'#':<3}{'TYPE':<11}{'VALUE?':<7}{'AUTO_ID':<24}NAME")
    print("-" * 80)

    rows = []
    for ctrl in win.descendants():
        info = ctrl.element_info
        ct = info.control_type
        if ct not in CTRL_MAP:
            continue
        has_value = False
        try:
            has_value = hasattr(ctrl, "get_value") or "Value" in ctrl.legacy_properties().get("Value", "")
        except Exception:
            pass
        try:
            has_value = bool(ctrl.iface_value) if hasattr(ctrl, "iface_value") else has_value
        except Exception:
            pass
        rows.append({
            "type": CTRL_MAP[ct],
            "auto_id": info.automation_id or "",
            "name": info.name or "",
            "value": has_value,
        })

    for i, r in enumerate(rows, 1):
        print(f"{i:<3}{r['type']:<11}{'✔' if r['value'] else '':<7}{r['auto_id'][:23]:<24}{r['name']}")

    # khối CONTROLS gợi ý (chỉ ô nhập/chọn, bỏ button)
    inputs = [r for r in rows if r["type"] != "button"]
    print("\n" + "=" * 80)
    print("➜ Khối CONTROLS gợi ý — sửa 'key' cho khớp 9 trường OCR, bỏ ô không cần:")
    print("=" * 80)
    print("CONTROLS = [")
    for r in inputs:
        ident = f'"auto_id": "{r["auto_id"]}"' if r["auto_id"] else f'"name": "{r["name"]}"'
        print(f'    {{"key": "{_slug(r["name"]) or "TODO"}", {ident}, "type": "{r["type"]}"}},')
    print("]")
    print("\n💡 Ô nào AUTO_ID trống thì định danh bằng Name (hoặc thứ tự). "
          "Gửi output này cho tôi để viết backend điền desktop.")


def main() -> int:
    try:
        import pywinauto  # noqa
    except ImportError:
        print("❌ Chưa cài pywinauto. Chạy: py -3.11 -m pip install pywinauto")
        return 1
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_all = "--all" in sys.argv
    if not pos:
        list_windows()
    else:
        inspect(pos[0], show_all=show_all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
