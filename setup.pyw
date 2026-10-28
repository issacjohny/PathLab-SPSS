"""One-time, menu-driven dependency setup for the selected SPSS Python runtime.

No administrator access or SPSS installation-directory writes are required.
Analysis code does not download or install anything.
"""
from __future__ import annotations

import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def dependency_folder(major, minor):
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    return base / "PathLab" / ("python-%s.%s" % (major, minor))


def main():
    root = tk.Tk()
    root.title("PathLab for SPSS — Dr. B. Issac Johny")
    root.geometry("720x540")
    root.minsize(650, 500)
    panel = ttk.Frame(root, padding=22)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="PathLab for SPSS", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    ttk.Label(panel, text="Developed by Dr. B. Issac Johny\nProfessor\nGnanam School of Business, Thanjavur",
              font=("Segoe UI", 10), wraplength=660).pack(anchor="w", pady=(2, 12))
    ttk.Label(panel, text="One-time calculation-library setup", font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 16))
    ttk.Label(panel, text="Choose the Python supplied with your SPSS installation. Close SPSS before setup.\n"
                         "Libraries are downloaded from PyPI into your own PathLab folder.\n"
                         "Your data and SPSS installation files are not changed.", wraplength=660).pack(anchor="w")
    location = tk.StringVar(value=str(Path(sys.executable).with_name("python.exe")))
    field = ttk.Frame(panel)
    field.pack(fill="x", pady=(15, 10))
    ttk.Entry(field, textvariable=location).pack(side="left", fill="x", expand=True)

    def browse():
        selected = filedialog.askopenfilename(title="Select SPSS Python3/python.exe", filetypes=[("Python executable", "python.exe"), ("Programs", "*.exe")])
        if selected:
            location.set(selected)
    ttk.Button(field, text="Browse…", command=browse).pack(side="right", padx=(8, 0))
    log = tk.Text(panel, height=10, wrap="word", font=("Consolas", 9), state="disabled")
    log.pack(fill="both", expand=True, pady=8)
    messages = queue.Queue()
    button = ttk.Button(panel, text="Install calculation libraries")
    button.pack(anchor="e", pady=(8, 0))

    def worker(executable):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            version = subprocess.check_output([executable, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], creationflags=flags, text=True).strip()
            major, minor = [int(item) for item in version.split(".")]
            if major != 3 or minor < 8:
                raise ValueError("Select the Python 3.8 or newer supplied with SPSS 27 or later.")
            destination = dependency_folder(major, minor)
            destination.mkdir(parents=True, exist_ok=True)
            requirements = Path(__file__).resolve().with_name("requirements.txt")
            command = [executable, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                       "--target", str(destination), "--upgrade", "-r", str(requirements)]
            messages.put(("text", "Installing for Python %s in %s\n" % (version, destination)))
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
            for line in process.stdout:
                messages.put(("text", line))
            if process.wait() != 0:
                raise RuntimeError("Library installation did not finish. Review the log and try again.")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(destination)
            subprocess.check_call([executable, "-c", "import numpy,pandas,scipy,statsmodels,matplotlib;from statsmodels.tools.sm_exceptions import PerfectSeparationWarning"], env=environment, creationflags=flags)
            messages.put(("done", "Libraries installed. In SPSS, choose Extensions → Install Local Extension Bundle,\n"
                                    "select PathLab-0.2.2.spe from the release folder, then restart SPSS.\n"
                                    "Open Analyze → PathLab: Mediation and Moderation."))
        except Exception as error:
            messages.put(("error", str(error)))

    def install():
        if not Path(location.get()).is_file():
            messagebox.showerror("Choose SPSS Python", "Browse to Python3/python.exe in your SPSS installation.")
            return
        button.configure(state="disabled")
        threading.Thread(target=worker, args=(location.get(),), daemon=True).start()

    def poll():
        try:
            while True:
                kind, content = messages.get_nowait()
                log.configure(state="normal")
                log.insert("end", content + ("\n" if kind != "text" else ""))
                log.see("end")
                log.configure(state="disabled")
                if kind in ("done", "error"):
                    button.configure(state="normal")
                    (messagebox.showinfo if kind == "done" else messagebox.showerror)("PathLab setup", content)
        except queue.Empty:
            pass
        root.after(150, poll)
    button.configure(command=install)
    root.after(150, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
