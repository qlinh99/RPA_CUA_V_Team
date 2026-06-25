# -*- coding: utf-8 -*-
"""
CẤU HÌNH FORM ĐÍCH — đổi form chỉ cần sửa DUY NHẤT file này.

Mỗi trường mô tả bằng:
  key     : tên trường trong dict OCR (phải khớp 9 khoá của ocr_to_form)
  label   : nhãn câu hỏi hiển thị trên form  (Playwright tìm ô theo nhãn này)
  entry   : id 'entry.xxxx' của Google Form  (POST không-trình-duyệt dùng cái này)
  type    : 'text' | 'paragraph' | 'date' | 'radio' | 'dropdown'
  options : (chỉ radio/dropdown) danh sách lựa chọn hợp lệ

➜ Lấy 'entry' và 'type' của form MỚI bằng:  py -3.11 inspect_form.py <URL form>
  rồi dán kết quả vào FIELDS bên dưới.
"""

# ── ID & URL của form ─────────────────────────────────────────────────────────
FORM_ID = "1FAIpQLSchJOa6msF40lWqoe9sGcjxP6S5gPjakK4WLNZmzv1kL1-j5w"
FORM_URL = f"https://docs.google.com/forms/d/e/{FORM_ID}/viewform"
POST_URL = f"https://docs.google.com/forms/d/e/{FORM_ID}/formResponse"

# nhãn nút gửi (khớp NFC, không phân biệt hoa/thường)
SUBMIT_LABELS = ("gửi", "submit")

# ── 9 trường, ĐÚNG THỨ TỰ câu hỏi trên form ───────────────────────────────────
FIELDS = [
    {"key": "so_hoa_don",      "label": "Số hoá đơn",        "entry": "entry.1638666668", "type": "text"},
    {"key": "ky_hieu",         "label": "Ký hiệu hoá đơn",   "entry": "entry.1407583201", "type": "text"},
    {"key": "ngay_lap",        "label": "Ngày lập",          "entry": "entry.113387208",  "type": "date"},
    {"key": "ten_ncc",         "label": "Tên nhà cung cấp",  "entry": "entry.2047361539", "type": "text"},
    {"key": "mst_ncc",         "label": "MST nhà cung cấp",  "entry": "entry.1840115105", "type": "text"},
    {"key": "dien_giai",       "label": "Diễn giải",         "entry": "entry.1186320033", "type": "paragraph"},
    {"key": "tien_truoc_thue", "label": "Tiền trước thuế",   "entry": "entry.1384960656", "type": "text"},
    {"key": "thue_suat",       "label": "Thuế suất GTGT",    "entry": "entry.99458547",   "type": "radio",
     "options": ["0%", "5%", "8%", "10%"]},
    {"key": "tong_thanh_toan", "label": "Tổng tiền thanh toán", "entry": "entry.727872323", "type": "text"},
]
