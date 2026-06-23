# Kịch bản DEMO cho mentor — RPA điền liệu hoá đơn

Thời lượng ~7–10 phút. Chỉ demo phần CHẠY CHẮC (bỏ CUA — chỉ nói là fallback).

## A. Chuẩn bị TRƯỚC demo (10 phút)

- [ ] `cd D:\python\ocr_vsf\rpa_hoadon`
- [ ] **Kiểm OCR còn chạy** (Gemini còn quota): chạy thử 1 lệnh xem-trước (mục B1). Nếu báo quota → đổi key trong `..\.env` hoặc chờ reset.
- [ ] **Internet** OK + mở được form `https://forms.gle/wJonukeJG9MN7bbB6`.
- [ ] **Access**: chạy `py -3.11 make_access_demo.py` để mở sẵn form (rồi đóng lại — lệnh demo sẽ tự mở).
- [ ] **Zalo** (nếu demo): đăng nhập sẵn, biết tên "My Documents" (gửi cho chính mình cho an toàn).
- [ ] **Tải sẵn 1 file responses .csv** từ form (phòng khi mạng chậm) cho phần verify.
- [ ] Chọn 2 hoá đơn rõ: `HD03_vat_tu_dien_nuoc.pdf`, `HD08_van_phong_pham.pdf`.
- [ ] Mở sẵn: thư mục `screenshots\`, 1 file dashboard `..\dashboard-ban-chat-cong-nghe.html` (nói kiến trúc).
- [ ] **Phòng hờ:** chụp sẵn vài ảnh kết quả (form đã gửi, dòng Excel/Access) đề phòng sự cố.

## B. Luồng demo (theo thứ tự)

### B1. Mở đầu + OCR (xem trước, không gửi) — 1.5 phút
> "Hoá đơn giấy/PDF nhập tay rất chậm và dễ sai. Tool tự OCR rồi điền vào nhiều hệ thống."

```powershell
py -3.11 autofill.py --form "https://forms.gle/wJonukeJG9MN7bbB6" --doc "..\Interns_Assignment\sample_documents\hoa_don\HD03_vat_tu_dien_nuoc.pdf"
```
→ Chỉ vào 9 trường trích xuất đúng. Nói: "PDF điện tử đọc text thẳng, ảnh/scan thì OCR Gemini. Có chuẩn hoá ngày/số/thuế."

### B2. Điền Google Form thật (Playwright, hiện trình duyệt) — 1.5 phút
```powershell
py -3.11 autofill.py --form "https://forms.gle/wJonukeJG9MN7bbB6" --doc "..\Interns_Assignment\sample_documents\hoa_don\HD03_vat_tu_dien_nuoc.pdf" --submit --headed
```
→ Trình duyệt tự mở, điền, bấm Gửi, chụp screenshot bằng chứng. Trực quan nhất.

### B3. CÙNG dữ liệu — đích khác (sức mạnh kiến trúc) — 2 phút
```powershell
# Excel: mỗi hoá đơn = 1 dòng
py -3.11 autofill.py --excel bao_cao.xlsx --doc "..\...\HD03_vat_tu_dien_nuoc.pdf" --submit --watch

# App desktop (Access qua COM) — giống OH thật
py -3.11 autofill.py --access --doc "..\...\HD08_van_phong_pham.pdf" --submit
```
→ Nói: "Một nguồn OCR, đổi 1 cờ là đổi đích. Excel/Access có API → Bậc 1 (COM). App không API như OH → Bậc 3 (pywinauto-UIA, đã chứng minh trên Zalo)."

### B4. Verification — maker-checker — 1.5 phút
```powershell
py -3.11 verify.py --responses "C:\Users\hello\Downloads\... (Responses).csv"
```
→ Báo cáo `verified / mismatch / missing`. Nói: **"Đã submit chưa chắc đúng — chỉ verified mới tính."** (Cho xem ví dụ dòng CUA chỉ điền 1 ô → mismatch.)

### B5. So sánh 3 bậc (số đo thực) — 1 phút
> POST 1.4s · Playwright 7.2s · CUA 48s (1/2). "POST nhanh nhất; Playwright có bằng chứng screenshot; CUA chậm + xác suất → chỉ làm fallback khi UI không có selector."

### B6. Kết — 30 giây
> Kiến trúc 4 mảnh (soi → OCR → trích → điền), thang 5 bậc, fallback CUA, verification.
> Hướng OH: chờ mạng Vingroup để soi UIA; OH có SOAP middle-tier → nên hỏi IT quyền API (Bậc 1).

## C. Câu hỏi mentor hay hỏi (chuẩn bị sẵn)

- **Vì sao không dùng API?** → Đa số hệ đích (OH) không mở API; tool đi UI. Có API (Excel/Access) thì dùng luôn (Bậc 1).
- **Sai OCR thì sao?** → Trường thiếu/không hợp lệ → `_issues` → KHÔNG tự gửi (maker-checker) + verify đối soát.
- **CUA để làm gì nếu kém?** → Fallback cho app không selector (canvas/Citrix) hoặc UI đổi layout; có verification gác.
- **Bảo mật?** → mật khẩu/key trong `.env` (demo); thật thì vault. Chỉ UAT, audit log.

## D. Lệnh dự phòng nếu sự cố

- OCR quota cạn giữa chừng → dùng kết quả đã chạy ở B1 (đã cache trong phiên) hoặc ảnh chụp.
- Form/mạng lỗi → chuyển sang demo Excel/Access (offline được).
- Mở ảnh bằng chứng: `screenshots\*.png`.
