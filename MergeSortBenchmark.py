import sys
import os
import subprocess
import threading
import time
import platform
import random
import tkinter as tk
from tkinter import ttk, messagebox

# ================= DEPENDENCY CHECK =================

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

missing = []

try:
    import psutil
except:
    missing.append("psutil")

if missing:
    for pkg in missing:
        try:
            install(pkg)
        except:
            print(f"\nMissing dependency: {pkg}")
            print(f"Run:\npython3 -m pip install {pkg}")
            sys.exit(1)

import psutil

# ================= GLOBAL FLAGS =================

cancel_flag = False

# ================= MERGE SORT =================

def merge_sort(arr):
    if cancel_flag or len(arr) <= 1:
        return arr

    mid = len(arr) // 2
    left = merge_sort(arr[:mid])
    right = merge_sort(arr[mid:])

    return merge(left, right)

def merge(left, right):
    result = []
    i = j = 0

    while i < len(left) and j < len(right):
        if cancel_flag:
            return []
        if left[i] < right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1

    result.extend(left[i:])
    result.extend(right[j:])
    return result

# ================= GUI APP =================

class App:

    def __init__(self, root):
        self.root = root
        root.title("20 Million Merge Sort Benchmark")
        root.geometry("500x320")

        self.label = tk.Label(root, text="Ready", font=("Arial", 14))
        self.label.pack(pady=10)

        self.progress = ttk.Progressbar(root, length=400)
        self.progress.pack(pady=10)

        self.start_btn = tk.Button(root, text="Start Benchmark", command=self.start)
        self.start_btn.pack(pady=5)

        self.stop_btn = tk.Button(root, text="Force Stop (ESC)", command=self.force_stop)
        self.stop_btn.pack(pady=5)

        self.result = tk.Label(root, text="")
        self.result.pack(pady=10)

        root.bind("<Escape>", lambda e: self.force_stop())

    # ================= START =================

    def start(self):
        global cancel_flag
        cancel_flag = False

        self.start_btn.config(state=tk.DISABLED)
        self.result.config(text="")
        self.progress["value"] = 0
        self.label.config(text="Generating numbers...")

        threading.Thread(target=self.run).start()

    # ================= FORCE STOP =================

    def force_stop(self):
        global cancel_flag
        cancel_flag = True
        self.label.config(text="Stopping...")
        self.start_btn.config(state=tk.NORMAL)

    # ================= MAIN WORK =================

    def run(self):
        try:
            size = 20_000_000

            data = [random.randint(0, size) for _ in range(size)]

            start_time = time.time()

            self.label.config(text="Sorting... (CPU heavy)")
            merge_sort(data)

            if cancel_flag:
                self.label.config(text="Cancelled")
                return

            elapsed = round(time.time() - start_time, 2)

            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent

            bottleneck = "CPU" if cpu > mem else "Memory"

            self.result.config(
                text=f"Completed in {elapsed}s\nCPU: {cpu}%  RAM: {mem}%\nLikely bottleneck: {bottleneck}"
            )

            self.label.config(text="Finished")

        except Exception as e:
            messagebox.showerror("Error", str(e))

        finally:
            self.progress["value"] = 100
            self.start_btn.config(state=tk.NORMAL)

# ================= RUN =================

root = tk.Tk()
App(root)
root.mainloop()
