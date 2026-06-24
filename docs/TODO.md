# TODO — RPA điền liệu hoá đơn

> Cập nhật: 2026-06-23.

## Đang chờ / đang làm

- (trống — form 3 trang đã chạy qua + Gửi OK, xem mục Đã xong)

## Ưu tiên cao (chứng thực nghiên cứu)

- [ ] **Dashboard HTML tổng hợp so sánh 3 bậc** (như dashboard-*.html team có).
      Số liệu đo: POST ~1.4s 3/3 · Playwright ~7.2s 3/3 · CUA ~48s 1/2 · OCR chung ~7s/bản ghi.
      Thêm cột verified sau khi user chạy verify.py.
- [ ] **Thí nghiệm R6:** đổi nhãn 1 câu trong form ("Số hoá đơn"→"Số HĐ") → chạy `--form` (Playwright gãy)
      vs `--cua` (vẫn tìm được) → bằng chứng "đắt giá nhất" cho trade-off Bậc 3 vs 4.
- [ ] **User chạy `verify.py`** trên responses tải về → lấy tỉ lệ verified từng bậc.

## Ưu tiên trung bình

- [ ] Hỗ trợ kiểu form `grid` + `scale` (linear scale) trong form_filler + cua + POST.
- [ ] Xử lý form **rẽ nhánh** (skip-logic) → `pageHistory` theo đúng đường đi.
- [ ] Bộ **pytest** cho hàm thuần (normalize_date/vat/amount, to_form_dict, verify.reconcile, _coerce ngày,
      _match_option, _strip_json) — bắt hồi quy (vd lỗi múi giờ Excel đã gặp).
- [ ] Dọn trùng `hoadon_to_form.py` (rpa_hoadon vs thư mục cha) — gom 1 bản.

## Ưu tiên thấp / tương lai

- [ ] **CUA desktop** (Gemini computer-use + pyautogui) cho app UIA gãy — hoàn thiện flowchart.
- [ ] Nâng GUI Tkinter → PySide6 (frameless góc màn hình như mockup) — tuỳ chọn.
- [ ] Widget tray icon.

## Chặn (cần điều kiện ngoài)

- [ ] **Soi OH thật + tạo `profiles/oh.json`** — CẦN máy trong mạng/VPN Vingroup.
- [ ] Hỏi IT Vingroup về **quyền SOAP API của OH** (Bậc 1, tốt hơn UI).

## Đã xong (gần đây)

- [x] **Form bệnh nhân 3 trang chạy qua + Gửi OK** (đã kiểm chứng: ảnh "đã được ghi lại").
      Sửa ô **ngày+giờ**: điền cả Giờ/Phút (mặc định 08:00) — trước đó bỏ trống giờ → "Thời gian
      không hợp lệ" chặn Gửi. Thêm `_confirm_submitted`: chống báo `ok:True` giả khi form bị chặn.
- [x] **GUI gửi nhiều ảnh/PDF một lúc** (app_gui: askopenfilenames + lặp dispatch + tổng kết).
- [x] **Sắp xếp repo**: docs/ + reports/, code .py giữ phẳng ở root.
- [x] autofill.py hợp nhất 5 đích + CLI gọn (epilog, nhóm tham số).
- [x] CUA Gemini fallback (web) + tự fallback khi Playwright gãy + `--cua`.
- [x] verify.py (R4) + benchmark.py (đo số liệu).
- [x] Hệ profile đa-app (desktop_profiles + profiles/*.json).
- [x] GUI Tkinter (app_gui.py) + tick watch/POST + dropdown profile.
- [x] Đóng gói GitHub (requirements, .gitignore, README) — đã push.
- [x] Form nhiều trang: POST pageHistory + Playwright điều hướng "Tiếp" + fix chờ trang bìa.
- [x] Fix model Gemini (1.5-flash gỡ) + fix múi giờ Excel --watch + Zalo.exe tự dò.
- [x] Access COM: thêm bản ghi mới (GoToRecord acNewRec) thay vì đè dòng đầu.
