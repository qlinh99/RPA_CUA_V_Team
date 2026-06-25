# -*- coding: utf-8 -*-
"""
GIAO DIỆN bấm-nút cho RPA hoá đơn (Tkinter — không cần cài thêm).
Chọn file chứng từ → chọn tab đích → Xem trước / Điền & Nộp.

Chạy:  py -3.11 app_gui.py
"""
import _bootstrap  # .env, temp->D:, sys.path
import os
import sys
import threading
import types
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import autofill

HERE = os.path.dirname(os.path.abspath(__file__))


def build_args(target, doc, extra, submit, headed, watch=True) -> types.SimpleNamespace:
    a = types.SimpleNamespace(
        doc=doc, submit=submit, headed=headed,
        form=None, refresh=False, cua=False,
        excel=None, sheet=None, header_row=1, watch=watch,
        access=False,
    )
    if target == "form":
        a.form = extra or None
    elif target == "excel":
        a.excel = extra or os.path.join(HERE, "data", "bao_cao.xlsx")
    elif target == "access":
        a.access = True
    return a


def dispatch(a) -> int:
    if a.access:
        return autofill.run_access(a)
    if a.excel:
        return autofill.run_excel(a)
    return autofill.run_form(a)


class TkWriter:
    """Chuyển print() của engine vào ô log (an toàn từ thread khác)."""
    def __init__(self, widget):
        self.w = widget

    def write(self, s):
        self.w.after(0, self._ins, s)

    def _ins(self, s):
        self.w.configure(state="normal")
        self.w.insert("end", s)
        self.w.see("end")
        self.w.configure(state="disabled")

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("RPA hoá đơn")
        root.geometry("560x560")
        root.attributes("-topmost", True)
        pad = {"padx": 10, "pady": 6}

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook.Tab", padding=[14, 6], background="#d0d0d0", foreground="#333")
        style.map("TNotebook.Tab",
                  background=[("selected", "#1a6fc4")],
                  foreground=[("selected", "white")])

        # ── 1) Chọn chứng từ ────────────────────────────────────────────
        self.docs = []
        self._set_display = False
        f1 = ttk.Frame(root); f1.pack(fill="x", **pad)
        ttk.Label(f1, text="Chứng từ (ảnh/PDF/Excel/CSV/Word — chọn nhiều):").pack(side="left")
        self.doc_var = tk.StringVar()
        self.doc_var.trace_add("write", self._on_doc_edit)
        ttk.Entry(f1, textvariable=self.doc_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f1, text="Chọn…", command=self.pick_doc).pack(side="left")

        # ── 2) OCR Provider ─────────────────────────────────────────────
        f2 = ttk.Frame(root); f2.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(f2, text="OCR Provider:").pack(side="left")
        self.provider_var = tk.StringVar(
            value=os.environ.get("OCR_PROVIDER", "openai").lower())
        _providers = ["openai", "gemini", "claude", "ollama", "mock"]
        ttk.Combobox(f2, textvariable=self.provider_var, values=_providers,
                     width=10, state="readonly").pack(side="left", padx=6)
        self._provider_hint = ttk.Label(f2, text="", foreground="#555")
        self._provider_hint.pack(side="left")
        self.provider_var.trace_add("write", self._on_provider_change)
        self._on_provider_change()   # hiện hint lần đầu

        # ── 3) Tab đích ─────────────────────────────────────────────────
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="x", **pad)

        # Tab 0 — Hồ sơ bệnh nhân / Gform
        t0 = ttk.Frame(self.nb, padding=(8, 8, 8, 10))
        self.nb.add(t0, text="  Hồ sơ bệnh nhân — Gform  ")
        ttk.Label(t0, text="Form URL (bỏ trống = dùng form cũ):").pack(anchor="w")
        self.form_url = tk.StringVar()
        ttk.Entry(t0, textvariable=self.form_url).pack(fill="x", pady=(3, 0))

        # Tab 1 — Hóa đơn (Excel & Access)
        t1 = ttk.Frame(self.nb, padding=(8, 8, 8, 10))
        self.nb.add(t1, text="  Hóa đơn (Excel & Access)  ")

        row_xl = ttk.Frame(t1); row_xl.pack(fill="x", pady=(0, 4))
        self.use_excel = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_xl, text="Ghi vào Excel:", variable=self.use_excel).pack(side="left")
        self.excel_path = tk.StringVar(value=os.path.join(HERE, "data", "bao_cao.xlsx"))
        ttk.Entry(row_xl, textvariable=self.excel_path).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(row_xl, text="…", width=3, command=self._pick_excel).pack(side="left")

        self.use_access = tk.BooleanVar(value=True)
        ttk.Checkbutton(t1, text="Ghi vào Access (CSDL mặc định)",
                        variable=self.use_access).pack(anchor="w")

        # Trạng thái ẩn — mặc định True, không hiện lên GUI
        self.headed = tk.BooleanVar(value=True)  # luôn hiện trình duyệt Form
        self.watch  = tk.BooleanVar(value=True)  # luôn mở Excel/Access xem điền

        # ── 4) Nút hành động ────────────────────────────────────────────
        f4 = ttk.Frame(root); f4.pack(fill="x", **pad)
        self.btn_prev = ttk.Button(f4, text="Xem trước nội dung",
                                   command=lambda: self.run(False))
        self.btn_prev.pack(side="left", expand=True, fill="x", padx=4)
        self.btn_go = ttk.Button(f4, text="Điền & Nộp ▶",
                                 command=lambda: self.run(True))
        self.btn_go.pack(side="left", expand=True, fill="x", padx=4)

        # ── 5) Log ──────────────────────────────────────────────────────
        self.log = tk.Text(root, height=16, state="disabled", wrap="word",
                           font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, **pad)

    # ── file picker ─────────────────────────────────────────────────────
    def pick_doc(self):
        ps = filedialog.askopenfilenames(
            title="Chọn chứng từ (giữ Ctrl/Shift để chọn nhiều)",
            filetypes=[
                ("Chứng từ", "*.pdf *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff "
                             "*.xlsx *.xlsm *.xls *.csv *.tsv *.docx *.doc *.txt *.md *.json"),
                ("Ảnh/PDF",  "*.pdf *.jpg *.jpeg *.png"),
                ("Dữ liệu",  "*.xlsx *.xlsm *.xls *.csv *.tsv *.docx *.doc"),
                ("Tất cả",   "*.*")])
        if not ps:
            return
        self.docs = list(ps)
        self._set_display = True
        if len(self.docs) == 1:
            self.doc_var.set(self.docs[0])
        else:
            names = ", ".join(os.path.basename(p) for p in self.docs)
            self.doc_var.set(f"{len(self.docs)} file: {names}")
        self._set_display = False

    def _pick_excel(self):
        p = filedialog.askopenfilename(
            title="Chọn file Excel báo cáo",
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Tất cả", "*.*")])
        if p:
            self.excel_path.set(p)

    def _on_provider_change(self, *_):
        hints = {
            "openai":  "GPT-4o-mini  (cần OPENAI_API_KEY)",
            "gemini":  "gemini-2.5-pro  (cần GEMINI_API_KEY)",
            "claude":  "Claude Haiku  (cần ANTHROPIC_API_KEY)",
            "ollama":  "LLaVA local  (cần ollama serve)",
            "mock":    "giả lập — không gọi API",
        }
        self._provider_hint.configure(
            text=hints.get(self.provider_var.get(), ""))

    def _on_doc_edit(self, *_):
        if not self._set_display:
            self.docs = []

    def _resolve_docs(self):
        if self.docs:
            return list(self.docs)
        p = self.doc_var.get().strip()
        return [p] if p else []

    # ── chạy ────────────────────────────────────────────────────────────
    def run(self, submit):
        docs = self._resolve_docs()
        bad  = [d for d in docs if not os.path.exists(d)]
        if not docs or bad:
            msg = "Hãy chọn file chứng từ hợp lệ." if not docs \
                else "Không tìm thấy file:\n" + "\n".join(bad)
            messagebox.showwarning("Thiếu file", msg)
            return

        tab = self.nb.index("current")  # 0 = Gform, 1 = Hóa đơn

        if tab == 1 and not self.use_excel.get() and not self.use_access.get():
            messagebox.showwarning("Chưa chọn đích",
                                   "Hãy tích chọn ít nhất Excel hoặc Access.")
            return

        if submit and not messagebox.askyesno(
                "Xác nhận",
                f"ĐIỀN & NỘP thật {len(docs)} chứng từ?\n(Xem trước thì bấm Hủy.)"):
            return

        # đóng gói params — đọc widget ở luồng chính trước khi spawn thread
        if tab == 0:
            params = ("form",
                      self.form_url.get().strip(),
                      submit, self.headed.get(), self.watch.get())
        else:
            params = ("invoice",
                      {"excel":  (self.use_excel.get(),  self.excel_path.get().strip()),
                       "access": self.use_access.get()},
                      submit, self.headed.get(), self.watch.get())

        provider = self.provider_var.get()
        self.btn_prev.configure(state="disabled")
        self.btn_go.configure(state="disabled")
        self.log.configure(state="normal"); self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        threading.Thread(target=self._worker, args=(docs, params, provider), daemon=True).start()

    def _worker(self, docs, params, provider):
        os.environ["OCR_PROVIDER"] = provider   # áp dụng trước khi bất kỳ OCR call nào
        target, extra, submit, headed, watch = params
        old = sys.stdout
        sys.stdout = TkWriter(self.log)
        codes = []
        try:
            for i, doc in enumerate(docs, 1):
                print(f"\n{'='*48}\n[{i}/{len(docs)}] {os.path.basename(doc)}\n{'='*48}")

                if target == "invoice":
                    rc_list = []
                    if extra["excel"][0]:   # use_excel
                        a = build_args("excel", doc, extra["excel"][1], submit, headed, watch)
                        try:
                            rc_list.append(dispatch(a))
                        except Exception as e:
                            import traceback
                            print("\n⛔ LỖI Excel:", e, "\n", traceback.format_exc())
                            rc_list.append(1)
                    if extra["access"]:     # use_access
                        a = build_args("access", doc, "", submit, headed, watch)
                        try:
                            rc_list.append(dispatch(a))
                        except Exception as e:
                            import traceback
                            print("\n⛔ LỖI Access:", e, "\n", traceback.format_exc())
                            rc_list.append(1)
                    rc = 0 if rc_list and all(c == 0 for c in rc_list) else 1
                else:
                    a = build_args(target, doc, extra, submit, headed, watch)
                    try:
                        rc = dispatch(a)
                    except Exception as e:
                        import traceback
                        print("\n⛔ LỖI:", e, "\n", traceback.format_exc())
                        rc = 1

                codes.append(rc)
                print(f"--- xong [{i}/{len(docs)}] (mã {rc}) ---")

            ok = sum(1 for c in codes if c == 0)
            print(f"\n=== TỔNG KẾT: {ok}/{len(docs)} thành công "
                  f"(mã != 0: {[c for c in codes if c != 0] or 'không'}) ===")
        finally:
            sys.stdout = old
            self.root.after(0, self._done)

    def _done(self):
        self.btn_prev.configure(state="normal")
        self.btn_go.configure(state="normal")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
