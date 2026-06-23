# -*- coding: utf-8 -*-
"""
GIAO DIỆN bấm-nút cho RPA hoá đơn (Tkinter — không cần cài thêm).
Chọn file hoá đơn → chọn đích → Xem trước / Điền & Nộp. Gọi lại engine autofill.py.

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
import desktop_profiles

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS = [("Google Form", "form"), ("Excel", "excel"), ("Access", "access"),
           ("App desktop", "profile"), ("Zalo", "zalo")]
EXTRA = {  # nhãn + giá trị mặc định cho ô tham số phụ theo đích
    "form":    ("Form URL (bỏ trống = form cũ)", ""),
    "excel":   ("File Excel", os.path.join(HERE, "bao_cao.xlsx")),
    "access":  ("(Access không cần tham số)", ""),
    "profile": ("Chọn app (profiles/*.json) — thêm app = thêm 1 JSON", ""),
    "zalo":    ("Gửi tới (tên trong Zalo)", "My Documents"),
}


def build_args(target, doc, extra, submit, headed, watch=False, post=False) -> types.SimpleNamespace:
    a = types.SimpleNamespace(
        doc=doc, submit=submit, headed=headed,
        form=None, post=post, refresh=False, cua=False,
        excel=None, sheet=None, header_row=1, watch=watch,
        access=False, app=False, profile=None, zalo=False, to=None,
    )
    if target == "form":
        a.form = extra or None
    elif target == "excel":
        a.excel = extra or os.path.join(HERE, "bao_cao.xlsx")
    elif target == "access":
        a.access = True
    elif target == "profile":
        a.profile = extra or None
    elif target == "zalo":
        a.zalo = True
        a.to = extra or None
    return a


def dispatch(a) -> int:
    if a.profile:
        return autofill.run_profile(a)
    if a.zalo:
        return autofill.run_zalo(a)
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

        # 1) file hoá đơn
        f1 = ttk.Frame(root); f1.pack(fill="x", **pad)
        ttk.Label(f1, text="Hoá đơn (ảnh/PDF):").pack(side="left")
        self.doc_var = tk.StringVar()
        ttk.Entry(f1, textvariable=self.doc_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f1, text="Chọn…", command=self.pick_doc).pack(side="left")

        # 2) đích
        f2 = ttk.LabelFrame(root, text="Điền vào"); f2.pack(fill="x", **pad)
        self.target = tk.StringVar(value="form")
        for label, val in TARGETS:
            ttk.Radiobutton(f2, text=label, value=val, variable=self.target,
                            command=self.on_target).pack(side="left", padx=8, pady=4)

        # 3) tham số phụ + headed
        f3 = ttk.Frame(root); f3.pack(fill="x", **pad)
        self.extra_label = tk.StringVar()
        ttk.Label(f3, textvariable=self.extra_label).pack(anchor="w")
        self.extra_var = tk.StringVar()
        self.extra_entry = ttk.Combobox(f3, textvariable=self.extra_var)
        self.extra_entry.pack(fill="x", pady=3)
        self.headed = tk.BooleanVar(value=True)
        ttk.Checkbutton(f3, text="Hiện trình duyệt (Form)", variable=self.headed).pack(anchor="w")
        self.watch = tk.BooleanVar(value=False)
        ttk.Checkbutton(f3, text="Mở Excel xem điền (Excel)", variable=self.watch).pack(anchor="w")
        self.post = tk.BooleanVar(value=False)
        ttk.Checkbutton(f3, text="Gửi nhanh không trình duyệt — POST (Form; form nhiều trang tự dùng)",
                        variable=self.post).pack(anchor="w")

        # 4) nút
        f4 = ttk.Frame(root); f4.pack(fill="x", **pad)
        self.btn_prev = ttk.Button(f4, text="Xem trước (OCR)", command=lambda: self.run(False))
        self.btn_prev.pack(side="left", expand=True, fill="x", padx=4)
        self.btn_go = ttk.Button(f4, text="Điền & Nộp ▶", command=lambda: self.run(True))
        self.btn_go.pack(side="left", expand=True, fill="x", padx=4)

        # 5) log
        self.log = tk.Text(root, height=16, state="disabled", wrap="word",
                           font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, **pad)

        self.on_target()

    def pick_doc(self):
        p = filedialog.askopenfilename(
            title="Chọn hoá đơn",
            filetypes=[("Ảnh/PDF", "*.pdf *.jpg *.jpeg *.png"), ("Tất cả", "*.*")])
        if p:
            self.doc_var.set(p)

    def on_target(self):
        t = self.target.get()
        lbl, default = EXTRA[t]
        self.extra_label.set(lbl)
        if t == "profile":
            profs = desktop_profiles.list_profiles()
            self.extra_entry.configure(values=profs, state="readonly")
            self.extra_var.set(profs[0] if profs else "")
        elif t == "access":
            self.extra_entry.configure(values=[], state="disabled")
            self.extra_var.set("")
        else:
            self.extra_entry.configure(values=[], state="normal")
            self.extra_var.set(default)

    def run(self, submit):
        doc = self.doc_var.get().strip()
        if not doc or not os.path.exists(doc):
            messagebox.showwarning("Thiếu file", "Hãy chọn file hoá đơn hợp lệ.")
            return
        if submit and not messagebox.askyesno(
                "Xác nhận", "ĐIỀN & NỘP thật vào đích đã chọn?\n(Xem trước thì bấm Hủy.)"):
            return
        a = build_args(self.target.get(), doc, self.extra_var.get().strip(),
                       submit, self.headed.get(), self.watch.get(), self.post.get())
        self.btn_prev.configure(state="disabled")
        self.btn_go.configure(state="disabled")
        self.log.configure(state="normal"); self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        threading.Thread(target=self._worker, args=(a,), daemon=True).start()

    def _worker(self, a):
        old = sys.stdout
        sys.stdout = TkWriter(self.log)
        try:
            rc = dispatch(a)
            print(f"\n=== Kết thúc (mã {rc}) ===")
        except Exception as e:
            import traceback
            print("\n⛔ LỖI:", e)
            print(traceback.format_exc())
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
