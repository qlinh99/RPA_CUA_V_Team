# PROJECT_STATE — RPA điền liệu hoá đơn / chứng từ

> Cập nhật: 2026-06-23. Đây là file trạng thái nguồn-sự-thật. Đọc file này đầu mỗi phiên.
> Vị trí: `rpa_hoadon/docs/` (cùng TODO.md, DECISIONS.md, DEMO.md). Code .py vẫn phẳng ở root.

## 1. Mục tiêu dự án

Nghiên cứu & **chứng thực các phương án RPA trong thực tế** (không phải sản phẩm production, không TDD).
Cụ thể: đọc chứng từ (ảnh/PDF) bằng OCR → điền tự động vào nhiều "đích", so sánh các bậc tự động hoá
(thang 5 bậc). Bối cảnh: Vinmec thu ngân, đích thật cuối cùng là OH (Orion Health HIS).

## 2. Trạng thái hiện tại

- **Đầy đủ chức năng + đã đẩy GitHub:** https://github.com/13716/RPA_thu_ngan.git (nhánh `main`).
- Một lệnh `autofill.py` điền 5 đích: Google Form, Excel, Access, app desktop (UIA), Zalo.
- 3 bậc cho web form: POST (Bậc 1) / Playwright (Bậc 3) / CUA Gemini (Bậc 4 fallback).
- Verification (`verify.py`), benchmark số liệu (`benchmark.py`), GUI bấm-nút (`app_gui.py`).
- Hệ thống profile đa-app (`profiles/*.json`) — thêm app = thêm 1 JSON.
- **Form nhiều trang:** POST gắn `pageHistory`; Playwright tự điều hướng "Tiếp" qua từng trang (kể cả trang bìa không ô).

## 3. Công việc đang làm (phiên này)

- Vừa hoàn thiện **điều hướng nhiều trang cho Playwright** + sửa bug chờ `listitem` ở trang bìa
  (đổi sang chờ `[role='button']`). Đang chờ user xác nhận form bệnh nhân 3 trang chạy qua + Gửi OK.
- Đã sửa model Gemini (1.5-flash bị Google gỡ → fallback flash-lite/2.0-flash).
- Đã sửa lỗi múi giờ Excel `--watch` (ghi ngày bằng số sê-ri).

## 4. Các file (trong rpa_hoadon/)

| File | Vai trò |
|------|---------|
| `autofill.py` | Nhạc trưởng: `--form/--excel/--access/--app/--profile/--zalo` + `--doc` + `--submit` |
| `_bootstrap.py` | temp→D:, nạp .env, thêm sys.path (engine OCR ở thư mục cha) |
| `doc_reader.py` | ảnh/PDF → trang (PDF điện tử đọc text pdfplumber, scan thì render+OCR) |
| `ocr_to_form.py` | chuẩn hoá ngày/thuế/số + `to_form_dict` |
| `test_image_processing.py` | **engine OCR** (adapter Gemini/OpenAI/Claude/Ollama) — bản copy trong repo; bản gốc ở thư mục cha |
| `inspect_form.py` | soi Google Form (FB_PUBLIC_LOAD_DATA_) → fields + entry + `pages` |
| `inspect_uia.py` | soi cây UIA app desktop (`--all` in mọi control) |
| `form_filler.py` | Playwright (đa trang) + POST (pageHistory) |
| `fill_invoice_form*.py` | bản Playwright/POST cũ (tiền thân) |
| `cua_fallback.py` | CUA Gemini Vision (Bậc 4) cho web form |
| `excel_target.py` / `excel_com.py` | Excel openpyxl / win32com (`--watch`) |
| `access_filler.py` | Access qua COM (Forms.Controls.Value) |
| `make_access_demo.py` | tạo hoadon_demo.accdb + form demo |
| `desktop_filler.py` | điền app desktop qua pywinauto-UIA (profile-aware) |
| `desktop_profiles.py` + `profiles/*.json` | hệ profile đa-app (access.json, _template.json) |
| `zalo_demo.py` | bộ đồ nghề desktop: get_zalo/wait_ready/force_front/unlock/open_chat/set_clipboard |
| `zalo_send_invoice.py` | OCR → format tin nhắn → gửi vào chat Zalo |
| `verify.py` | đối soát responses ↔ nguồn (verified/mismatch/missing) |
| `benchmark.py` | đo thời gian/tỉ lệ 3 bậc |
| `app_gui.py` | GUI Tkinter bấm-nút (gọi lại autofill) |
| `hoadon_to_form.py` / `form_config.py` | bản chuyên 9 trường hoá đơn (tiền thân) |
| `README.md` (root), `docs/DEMO.md`, `requirements.txt` | tài liệu + cài đặt + kịch bản demo |

## 5. Kiến trúc hiện tại

```
① SOI ĐÍCH → schema trường   (inspect_form / inspect_uia / excel header / profile JSON)
② ĐỌC + OCR                  (doc_reader + test_image_processing/Gemini)   ┐ dùng chung
③ TRÍCH XUẤT theo schema     (autofill._extract_items + ocr_to_form)        ┘
④ ĐIỀN                       (form_filler / excel_* / access_filler / desktop_filler / zalo)
+ Verification (verify.py) gác sau; maker-checker chặn submit nếu trường thiếu.
```
- Đổi đích = thay mảnh ① + ④. Mảnh ②③ không đổi.
- Bậc theo "thang 5 bậc": API/COM (Bậc 1) → UI tất định (Bậc 3) → CUA (Bậc 4 fallback).

## 6. Tham số quan trọng

- **Chạy bằng `py -3.11`** (Python 3.11 ở `C:\Users\hello\AppData\Local\Programs\Python\Python311`).
  Lệnh `python` trỏ venv hermes (THIẾU lib) — KHÔNG dùng.
- **`.env` ở thư mục cha** `D:\python\ocr_vsf\.env`: `OCR_PROVIDER=gemini`, `GEMINI_API_KEY=...`,
  `ZALO_PASSWORD=...` (tuỳ chọn `ZALO_EXE=...`). KHÔNG commit.
- Model Gemini: `gemini-2.5-flash` (chính) → fallback `gemini-2.5-flash-lite` → `gemini-2.0-flash`.
- Form demo hoá đơn: `https://forms.gle/wJonukeJG9MN7bbB6` (9 trường).
- Form bệnh nhân nhiều trang (test): `.../1FAIpQLSfi8zjzpp9o9UD1ZZVwdJp7XsNqhuQrAWhIOxXwG6SxT5-FhA` (3 trang).
- Zalo auto_id: `passcode` (mã khoá), `contact-search-input` (tìm kiếm), `richInput` (ô soạn tin, đọc Name).
- Access: điền qua COM, control định danh bằng `Name` (vd `txtSoHoaDon`), lưu bằng Shift+Enter.
- Multi-page: `pages = 1 + số page-break`; POST gửi `pageHistory=0,1,...,pages-1`.

## 7. Bug / hạn chế đang tồn tại

- **CUA toạ độ kém:** Gemini định vị ~1/9 ô đúng trên form → chỉ dùng làm fallback, không thay Playwright.
- **Kiểu form chưa hỗ trợ:** `grid`, `scale (code18)` bị bỏ qua. Nếu bắt buộc → chặn sang trang (Playwright) / thiếu (POST).
- **Form rẽ nhánh:** `pageHistory` tuyến tính có thể không khớp form có skip-logic.
- **Access COM:** cần đóng Access trước khi chạy (tránh khoá file); GoToRecord acNewRec để thêm dòng mới.
- **OCR quota Gemini free** có giới hạn theo ngày → chạy nhiều (CUA/benchmark) dễ cạn.
- **OH chưa soi được:** máy không vào domain/VPN Vingroup (DNS `svm-ent-uat.vingroup.local` fail).
- **Chưa có test tự động** (không theo TDD) — chỉ self-test trong `__main__` + chạy tay.
- **Trùng `hoadon_to_form.py`** (rpa_hoadon + thư mục cha); zalo_send_invoice import bản cha do sys.path.

## 8. Ràng buộc hệ thống

- **Windows-only** (pywinauto, win32com, win32clipboard, win32gui).
- **Ổ C: đầy** → `_bootstrap` ép temp sang `D:\python\ocr_vsf\rpa_hoadon\_tmp`.
- **Không tải Chromium** → Playwright dùng Chrome sẵn có (`channel="chrome"`).
- Excel/Access phải **đóng** trước khi điền qua COM.
- Tiếng Việt: nút "Gửi" dạng tổ hợp NFD → so khớp sau khi NFC.

## 9. Bước tiếp theo (xem TODO.md cho chi tiết)

1. Xác nhận form bệnh nhân 3 trang chạy qua đủ + Gửi OK (đang chờ user test).
2. Dựng dashboard HTML tổng hợp so sánh 3 bậc (số liệu: POST 1.4s 3/3 · Playwright 7.2s 3/3 · CUA 48s 1/2).
3. Thí nghiệm R6 (đổi nhãn form → Playwright gãy vs CUA thích nghi).
4. (tuỳ) hỗ trợ kiểu `grid`/`scale`; CUA desktop; bộ pytest cho hàm thuần.
5. Khi có mạng Vingroup: soi OH → tạo `profiles/oh.json`.
