import sys
import subprocess
import threading
import time
import random
import tkinter as tk
from tkinter import ttk, messagebox
import multiprocessing

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
SINGLE_CORE_NUMBERS = 20_000_000   # single-core merge sort
MULTICORE_DURATION = 60            # seconds
MULTICORE_BATCH_SIZE = 2_000_000   # per batch

# ================= APP CLASS =================
class App:
    def __init__(self, root):
        self.root = root
        root.title("CPU Benchmark")
        root.geometry("700x500")
        root.minsize(600, 400)
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        # ---------------- CONTAINER ----------------
        self.container = tk.Frame(root)
        self.container.grid(row=0, column=0, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        # ---------------- FRAMES ----------------
        self.main_menu = tk.Frame(self.container)
        self.benchmark_frame = tk.Frame(self.container)

        for frame in (self.main_menu, self.benchmark_frame):
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_rowconfigure(0, weight=1)
            frame.grid_columnconfigure(0, weight=1)

        # ================= MAIN MENU =================
        self.main_menu_inner = tk.Frame(self.main_menu)
        self.main_menu_inner.grid(row=0, column=0)
        self.main_menu.grid_rowconfigure(0, weight=1)
        self.main_menu.grid_columnconfigure(0, weight=1)

        tk.Label(self.main_menu_inner, text="Select Benchmark Mode", font=("Arial", 18)).grid(row=0, column=0, pady=10)
        tk.Button(self.main_menu_inner, text="Single-Core Benchmark", width=25, command=self.show_single_core).grid(row=1, column=0, pady=5)
        tk.Button(self.main_menu_inner, text="Multi-Core Benchmark", width=25, command=self.show_multi_core).grid(row=2, column=0, pady=5)
        tk.Button(self.main_menu_inner, text="How It Works", width=25, command=self.show_how_it_works).grid(row=3, column=0, pady=5)

        # ================= BENCHMARK PAGE =================
        self.benchmark_inner = tk.Frame(self.benchmark_frame)
        self.benchmark_inner.grid(row=0, column=0)
        self.benchmark_frame.grid_rowconfigure(0, weight=1)
        self.benchmark_frame.grid_columnconfigure(0, weight=1)

        # Widgets
        self.label = tk.Label(self.benchmark_inner, text="Ready", font=("Arial", 14))
        self.label.grid(row=0, column=0, columnspan=2, pady=10)

        self.progress = ttk.Progressbar(self.benchmark_inner, length=400)
        self.progress.grid(row=1, column=0, pady=5)
        self.percent_label = tk.Label(self.benchmark_inner, text="0%", font=("Arial", 12))
        self.percent_label.grid(row=1, column=1, padx=5)

        self.timer_label = tk.Label(self.benchmark_inner, text="Time: 00:00", font=("Arial", 12))
        self.timer_label.grid(row=2, column=0, columnspan=2, pady=5)

        self.usage_label = tk.Label(self.benchmark_inner, text="CPU: 0%   RAM: 0%", font=("Arial", 12))
        self.usage_label.grid(row=3, column=0, columnspan=2, pady=5)

        self.count_label = tk.Label(self.benchmark_inner, text="", font=("Arial", 12))
        self.count_label.grid(row=4, column=0, columnspan=2, pady=5)

        self.start_btn = tk.Button(self.benchmark_inner, text="Start Benchmark", command=self.start)
        self.start_btn.grid(row=5, column=0, columnspan=2, pady=5)

        self.stop_btn = tk.Button(self.benchmark_inner, text="Force Stop (ESC)", command=self.force_stop)
        self.stop_btn.grid(row=6, column=0, columnspan=2, pady=5)

        self.back_btn = tk.Button(self.benchmark_inner, text="Back to Main Menu", command=self.back_to_menu)
        self.back_btn.grid(row=7, column=0, columnspan=2, pady=5)

        self.result = tk.Label(self.benchmark_inner, text="", font=("Arial", 11))
        self.result.grid(row=8, column=0, columnspan=2, pady=10)

        # Bind ESC to force stop
        root.bind("<Escape>", lambda e: self.force_stop())

        # Timer
        self.timer_running = False
        self.start_time = None

        # Benchmark thread
        self.benchmark_thread = None

        # Benchmark type: "single" or "multi"
        self.benchmark_type = None

        # Show main menu first
        self.show_frame(self.main_menu)

    # ================= FRAME SWITCH =================
    def show_frame(self, frame):
        frame.tkraise()

    # ================= SHOW PAGES =================
    def show_single_core(self):
        self.benchmark_type = "single"
        self.reset_benchmark_ui()
        self.count_label.config(text="")
        self.show_frame(self.benchmark_frame)

    def show_multi_core(self):
        self.benchmark_type = "multi"
        self.reset_benchmark_ui()
        self.count_label.config(text="Batches Completed: 0")
        self.show_frame(self.benchmark_frame)

    # ================= HOW IT WORKS =================
    def show_how_it_works(self):
        explanation = (
            "Single-Core Benchmark:\n\n"
            "Measures the performance of a single CPU core by sorting 20 million numbers using merge sort.\n"
            "- Merge sort is divide-and-conquer: it splits the list into halves until sublists have 1 element, then merges them in order.\n"
            "- Only one CPU core is used.\n"
            "- Displays live progress, CPU/RAM usage, and elapsed time.\n\n"
            "Multi-Core Benchmark:\n\n"
            "Uses all CPU cores to measure multi-core throughput over 60 seconds.\n"
            "- Each core repeatedly sorts batches of 2 million numbers.\n"
            "- Tracks total batches completed by all cores.\n"
            "- Displays CPU/RAM usage, elapsed time, and batches completed live.\n"
            "- Helps identify efficiency and parallel processing capability."
        )
        messagebox.showinfo("How Benchmarks Work", explanation)

    # ================= RESET UI =================
    def reset_benchmark_ui(self):
        self.progress["value"] = 0
        self.percent_label.config(text="0%")
        self.timer_label.config(text="Time: 00:00")
        self.usage_label.config(text="CPU: 0%   RAM: 0%")
        self.label.config(text="Ready")
        self.result.config(text="")
        self.start_btn.config(state=tk.NORMAL)

    # ================= BACK TO MAIN MENU =================
    def back_to_menu(self):
        global cancel_flag
        if self.benchmark_thread and self.benchmark_thread.is_alive():
            cancel_flag = True
            self.label.config(text="Stopping benchmark...")
            self.stop_timer()
            self.result.config(text="Benchmark stopping... returning to main menu.")
        self.start_btn.config(state=tk.NORMAL)
        self.show_frame(self.main_menu)

    # ================= START =================
    def start(self):
        global cancel_flag
        cancel_flag = False
        self.start_btn.config(state=tk.DISABLED)
        self.progress["value"] = 0
        self.percent_label.config(text="0%")
        self.timer_label.config(text="Time: 00:00")
        self.usage_label.config(text="CPU: 0%   RAM: 0%")
        self.result.config(text="")
        self.label.config(text="Starting benchmark...")

        self.benchmark_thread = threading.Thread(target=self.run)
        self.benchmark_thread.start()
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
        threading.Thread(target=self.update_timer, daemon=True).start()

    def stop_timer(self):
        self.timer_running = False

    def update_timer(self):
        while self.timer_running:
            elapsed = int(time.time() - self.start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.timer_label.config(text=f"Time: {minutes:02d}:{seconds:02d}")
            time.sleep(0.5)

    # ================= SINGLE CORE MERGE SORT =================
    def merge_sort(self, arr):
        n = len(arr)
        temp = arr.copy()
        size = 1
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

    # ================= MULTI-CORE WORKER =================
    @staticmethod
    def multicore_worker(batch_counter, duration, batch_size):
        import random, time
        start = time.time()
        while time.time() - start < duration:
            data = [random.randint(0, batch_size) for _ in range(batch_size)]
            data.sort()
            with batch_counter.get_lock():
                batch_counter.value += 1

    # ================= RUN =================
    def run(self):
        global cancel_flag
        try:
            monitor_running = True
            cpu_values = []

            def monitor():
                while monitor_running and not cancel_flag:
                    cpu = psutil.cpu_percent(interval=None)
                    mem = psutil.virtual_memory().percent
                    cpu_values.append(cpu)
                    if len(cpu_values) > 10:
                        cpu_values.pop(0)
                    avg_cpu = sum(cpu_values)/len(cpu_values)
                    self.usage_label.config(text=f"CPU: {avg_cpu:.1f}%   RAM: {mem}%")
                    self.root.update_idletasks()
                    time.sleep(0.2)

            t_monitor = threading.Thread(target=monitor, daemon=True)
            t_monitor.start()

            if self.benchmark_type == "single":
                data = [random.randint(0, SINGLE_CORE_NUMBERS) for _ in range(SINGLE_CORE_NUMBERS)]
                self.label.config(text="Sorting... (CPU heavy)")
                start_time = time.time()
                self.merge_sort(data)
                elapsed = round(time.time() - start_time, 2)
                monitor_running = False
                t_monitor.join()
                self.stop_timer()

                if cancel_flag:
                    self.label.config(text="Cancelled")
                    self.result.config(text=f"Time before cancel: {elapsed:.2f}s")
                else:
                    avg_cpu = sum(cpu_values)/len(cpu_values) if cpu_values else 0
                    mem = psutil.virtual_memory().percent
                    self.progress["value"] = 100
                    self.percent_label.config(text="100%")
                    self.label.config(text="Completed")
                    self.result.config(
                        text=f"Time: {elapsed:.2f}s\nAvg CPU: {avg_cpu:.1f}% RAM: {mem}%"
                    )

            elif self.benchmark_type == "multi":
                self.label.config(text="Running Multi-Core Benchmark...")
                start_time = time.time()

                batch_counter = multiprocessing.Value('i', 0)
                num_cores = multiprocessing.cpu_count()
                processes = []

                for _ in range(num_cores):
                    p = multiprocessing.Process(
                        target=App.multicore_worker, 
                        args=(batch_counter, MULTICORE_DURATION, MULTICORE_BATCH_SIZE)
                    )
                    p.start()
                    processes.append(p)

                while time.time() - start_time < MULTICORE_DURATION and not cancel_flag:
                    self.count_label.config(text=f"Batches Completed: {batch_counter.value}")
                    percent = int((time.time() - start_time) / MULTICORE_DURATION * 100)
                    self.progress["value"] = percent
                    self.percent_label.config(text=f"{percent}%")
                    self.root.update_idletasks()
                    time.sleep(0.2)

                cancel_flag = True
                for p in processes:
                    p.join()
                monitor_running = False
                t_monitor.join()
                self.stop_timer()

                elapsed = round(time.time() - start_time, 2)
                self.progress["value"] = 100
                self.percent_label.config(text="100%")
                self.label.config(text="Completed")
                avg_cpu = sum(cpu_values)/len(cpu_values) if cpu_values else 0
                mem = psutil.virtual_memory().percent
                self.result.config(
                    text=f"Time: {elapsed:.2f}s\nBatches Completed: {batch_counter.value}\nAvg CPU: {avg_cpu:.1f}% RAM: {mem}%"
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
