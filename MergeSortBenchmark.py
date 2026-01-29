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

TOTAL_NUMBERS = 20_000_000

# ================= GUI APP =================

class App:

    def __init__(self, root):
        self.root = root
        root.title("20 Million Merge Sort Benchmark")
        root.geometry("600x350")

        self.label = tk.Label(root, text="Ready", font=("Arial", 14))
        self.label.pack(pady=10)

        frame = tk.Frame(root)
        frame.pack(pady=10)

        self.progress = ttk.Progressbar(frame, length=400)
        self.progress.pack(side=tk.LEFT)

        self.percent_label = tk.Label(frame, text="0%", font=("Arial", 12))
        self.percent_label.pack(side=tk.LEFT, padx=10)

        self.start_btn = tk.Button(root, text="Start Benchmark", command=self.start)
        self.start_btn.pack(pady=5)

        self.stop_btn = tk.Button(root, text="Force Stop (ESC)", command=self.force_stop)
        self.stop_btn.pack(pady=5)

        self.result = tk.Label(root, text="", font=("Arial", 11))
        self.result.pack(pady=10)

        root.bind("<Escape>", lambda e: self.force_stop())

    # ================= START =================
    def start(self):
        global cancel_flag
        cancel_flag = False
        self.start_btn.config(state=tk.DISABLED)
        self.progress["value"] = 0
        self.percent_label.config(text="0%")
        self.result.config(text="")
        self.label.config(text="Generating numbers...")

        threading.Thread(target=self.run).start()

    # ================= FORCE STOP =================
    def force_stop(self):
        global cancel_flag
        cancel_flag = True
        self.label.config(text="Stopping...")
        self.start_btn.config(state=tk.NORMAL)

    # ================= ITERATIVE MERGE SORT WITH PROGRESS =================
    def merge_sort(self, arr):
        n = len(arr)
        temp = arr.copy()
        size = 1
        total_passes = 0

        # Count total passes
        s = 1
        while s < n:
            total_passes += 1
            s *= 2

        done = 0

        while size < n and not cancel_flag:
            for left in range(0, n, 2*size):
                mid = min(left+size, n)
                right = min(left+2*size, n)
                self.merge(arr, temp, left, mid, right)
            arr[:] = temp[:]
            size *= 2
            done += 1
            percent = int((done/total_passes)*100)
            self.progress["value"] = percent
            self.percent_label.config(text=f"{percent}%")
            self.root.update_idletasks()

    def merge(self, arr, temp, l, m, r):
        i = l
        j = m
        k = l
        while i < m and j < r:
            if cancel_flag:
                return
            if arr[i] <= arr[j]:
                temp[k] = arr[i]
                i += 1
            else:
                temp[k] = arr[j]
                j += 1
            k += 1
        while i < m:
            temp[k] = arr[i]
            i += 1
            k += 1
        while j < r:
            temp[k] = arr[j]
            j += 1
            k += 1

    # ================= MAIN RUN =================
    def run(self):
        try:
            data = [random.randint(0, TOTAL_NUMBERS) for _ in range(TOTAL_NUMBERS)]

            self.label.config(text="Sorting...")
            start_time = time.time()

            self.merge_sort(data)

            if cancel_flag:
                self.label.config(text="Cancelled")
                self.start_btn.config(state=tk.NORMAL)
                return

            elapsed = round(time.time() - start_time, 2)
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent

            bottleneck = "No major bottleneck detected"
            if cpu > 85:
                bottleneck = "CPU intensive task detected"
            if mem > 80:
                bottleneck = "Memory intensive task detected"

            self.progress["value"] = 100
            self.percent_label.config(text="100%")
            self.label.config(text="Completed")
            self.result.config(text=f"Time: {elapsed}s\nCPU: {cpu}% RAM: {mem}%\n{bottleneck}")

        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.start_btn.config(state=tk.NORMAL)

# ================= RUN =================
root = tk.Tk()
App(root)
root.mainloop()
