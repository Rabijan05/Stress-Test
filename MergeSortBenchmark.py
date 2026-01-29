import sys
import subprocess
import threading
import time
import random
import tkinter as tk
from tkinter import ttk, messagebox

# ================= DEPENDENCY CHECK =================
def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import psutil
except ImportError:
    try:
        install("psutil")
        import psutil
    except:
        messagebox.showerror("Missing Dependency",
                             "Please run: python -m pip install psutil")
        sys.exit(1)

# ================= GLOBAL FLAGS =================
cancel_flag = False
TOTAL_NUMBERS = 20_000_000

# ================= GUI APP =================
class App:
    def __init__(self, root):
        self.root = root
        root.title("20 Million Merge Sort Benchmark")
        root.geometry("650x420")

        self.label = tk.Label(root, text="Ready", font=("Arial", 14))
        self.label.pack(pady=10)

        # Progress bar + % label
        frame = tk.Frame(root)
        frame.pack(pady=10)
        self.progress = ttk.Progressbar(frame, length=400)
        self.progress.pack(side=tk.LEFT)
        self.percent_label = tk.Label(frame, text="0%", font=("Arial", 12))
        self.percent_label.pack(side=tk.LEFT, padx=10)

        # Timer label
        self.timer_label = tk.Label(root, text="Time: 00:00", font=("Arial", 12))
        self.timer_label.pack(pady=5)

        # CPU / RAM label
        self.usage_label = tk.Label(root, text="CPU: 0%   RAM: 0%", font=("Arial", 12))
        self.usage_label.pack(pady=5)

        # Buttons
        self.start_btn = tk.Button(root, text="Start Benchmark", command=self.start)
        self.start_btn.pack(pady=5)
        self.stop_btn = tk.Button(root, text="Force Stop (ESC)", command=self.force_stop)
        self.stop_btn.pack(pady=5)

        # Result label
        self.result = tk.Label(root, text="", font=("Arial", 11))
        self.result.pack(pady=10)

        # Bind ESC to force stop
        root.bind("<Escape>", lambda e: self.force_stop())

        # Timer thread
        self.timer_running = False
        self.start_time = None

    # ================= START =================
    def start(self):
        global cancel_flag
        cancel_flag = False
        self.start_btn.config(state=tk.DISABLED)
        self.progress["value"] = 0
        self.percent_label.config(text="0%")
        self.usage_label.config(text="CPU: 0%   RAM: 0%")
        self.timer_label.config(text="Time: 00:00")
        self.result.config(text="")
        self.label.config(text="Generating numbers...")

        threading.Thread(target=self.run).start()
        self.start_timer()

    # ================= FORCE STOP =================
    def force_stop(self):
        global cancel_flag
        cancel_flag = True
        self.label.config(text="Stopping...")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_timer()

    # ================= TIMER =================
    def start_timer(self):
        self.start_time = time.time()
        self.timer_running = True
        threading.Thread(target=self.update_timer).start()

    def stop_timer(self):
        self.timer_running = False

    def update_timer(self):
        while self.timer_running:
            elapsed = int(time.time() - self.start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.timer_label.config(text=f"Time: {minutes:02d}:{seconds:02d}")
            time.sleep(0.5)

    # ================= ITERATIVE MERGE SORT =================
    def merge_sort(self, arr):
        n = len(arr)
        temp = arr.copy()
        size = 1

        # Count total passes for progress
        total_passes = 0
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
        i, j, k = l, m, l
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
            temp[k] = arr[i]; i += 1; k += 1
        while j < r:
            temp[k] = arr[j]; j += 1; k += 1

    # ================= RUN =================
    def run(self):
        global cancel_flag
        try:
            data = [random.randint(0, TOTAL_NUMBERS) for _ in range(TOTAL_NUMBERS)]
            self.label.config(text="Sorting... (CPU heavy)")

            start_time = time.time()

            # CPU/RAM monitor
            monitor_running = True
            cpu_values = []

            def monitor():
                while monitor_running and not cancel_flag:
                    cpu = psutil.cpu_percent(interval=0.5)
                    mem = psutil.virtual_memory().percent
                    cpu_values.append(cpu)
                    self.usage_label.config(text=f"CPU: {cpu}%   RAM: {mem}%")
                    self.root.update_idletasks()

            t_monitor = threading.Thread(target=monitor)
            t_monitor.start()

            # Run merge sort
            self.merge_sort(data)

            # Stop monitor thread
            monitor_running = False
            t_monitor.join()
            self.stop_timer()

            elapsed = round(time.time() - start_time, 2)

            if cancel_flag:
                self.label.config(text="Cancelled")
                self.result.config(text=f"Time before cancel: {elapsed:.2f}s")
            else:
                avg_cpu = sum(cpu_values)/len(cpu_values) if cpu_values else 0
                mem = psutil.virtual_memory().percent
                bottleneck = "No major bottleneck detected"
                if avg_cpu > 85:
                    bottleneck = "CPU intensive task detected"
                if mem > 80:
                    bottleneck = "Memory intensive task detected"

                self.progress["value"] = 100
                self.percent_label.config(text="100%")
                self.label.config(text="Completed")
                self.result.config(
                    text=f"Time: {elapsed:.2f}s\nAvg CPU: {avg_cpu:.1f}% RAM: {mem}%\n{bottleneck}"
                )

        except Exception as e:
            messagebox.showerror("Error", str(e))
        finally:
            self.start_btn.config(state=tk.NORMAL)

# ================= RUN APP =================
if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
