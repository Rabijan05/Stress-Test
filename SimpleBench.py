
import json
import math
import multiprocessing
import os
import platform
import queue
import random
import socket
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

APP_NAME = "SimpleBench"
APP_VERSION = "2.0"
HISTORY_FILE = os.path.expanduser("~/.simplebench_history.json")

# Safer defaults for laptops; user can change them in the UI.
DEFAULT_SINGLE_CORE_NUMBERS = 2_000_000
DEFAULT_MULTICORE_DURATION = 30
DEFAULT_MULTICORE_BATCH_SIZE = 500_000


def ensure_psutil():
    try:
        import psutil  # type: ignore
        return psutil
    except ImportError as exc:
        raise RuntimeError(
            "This app requires psutil. Install it with: python3 -m pip install psutil"
        ) from exc


PSUTIL = ensure_psutil()


def score_single_core(items: int, seconds: float) -> int:
    """Normalized single-core score using n log2(n) work."""
    if seconds <= 0 or items <= 1:
        return 0
    work_units = items * math.log2(items)
    return int(work_units / seconds / 100_000)


def score_multi_core(batches: int, effective_batch_size: int, seconds: float) -> int:
    """Throughput score based on total items processed per second."""
    if seconds <= 0 or batches <= 0 or effective_batch_size <= 0:
        return 0
    items_per_second = (batches * effective_batch_size) / seconds
    return int(items_per_second / 1_000)


class BenchmarkWorker:
    """Runs benchmarks off the main thread/process and reports UI-safe events."""

    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue
        self.cancel_event = threading.Event()
        self.thread = None
        self.monitor_thread = None
        self.monitor_stop = threading.Event()
        self.cpu_samples = []
        self.multi_stop_event = None
        self.processes = []
        self.batch_counter = None

    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, benchmark_type: str, single_numbers: int, multi_duration: int, multi_batch: int):
        if self.is_running():
            return

        self.cancel_event.clear()
        self.monitor_stop.clear()
        self.cpu_samples = []
        self.thread = threading.Thread(
            target=self._run,
            args=(benchmark_type, single_numbers, multi_duration, multi_batch),
            daemon=True,
        )
        self.thread.start()

    def cancel(self):
        self.cancel_event.set()
        if self.multi_stop_event is not None:
            self.multi_stop_event.set()

    def _monitor_usage(self):
        while not self.monitor_stop.is_set() and not self.cancel_event.is_set():
            try:
                cpu = PSUTIL.cpu_percent(interval=0.25)
                mem = PSUTIL.virtual_memory().percent
                self.cpu_samples.append(cpu)
                if len(self.cpu_samples) > 20:
                    self.cpu_samples.pop(0)
                avg_cpu = sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0.0
                self.event_queue.put(("usage", avg_cpu, mem))
            except Exception as exc:
                self.event_queue.put(("error", f"Resource monitor failed: {exc}"))
                break

    def _run(self, benchmark_type: str, single_numbers: int, multi_duration: int, multi_batch: int):
        self.monitor_thread = threading.Thread(target=self._monitor_usage, daemon=True)
        self.monitor_thread.start()

        try:
            if benchmark_type == "single":
                self._run_single(single_numbers)
            elif benchmark_type == "multi":
                self._run_multi(multi_duration, multi_batch)
            else:
                raise ValueError(f"Unknown benchmark type: {benchmark_type}")
        except MemoryError:
            self.event_queue.put((
                "error",
                "The benchmark used more memory than your Mac could comfortably provide. "
                "Try a smaller workload.",
            ))
        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
        finally:
            self.monitor_stop.set()
            if self.monitor_thread is not None:
                self.monitor_thread.join(timeout=1.0)
            self.event_queue.put(("done",))

    def _run_single(self, numbers_count: int):
        self.event_queue.put(("status", "Generating random data for the single-core test..."))
        start_generation = time.perf_counter()
        data = [random.randint(0, numbers_count) for _ in range(numbers_count)]
        generation_time = time.perf_counter() - start_generation

        self.event_queue.put(("status", "Running single-core merge sort..."))
        start_sort = time.perf_counter()
        completed_passes = self._merge_sort_iterative(data)
        elapsed = time.perf_counter() - start_sort

        cancelled = self.cancel_event.is_set()
        avg_cpu = sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0.0
        mem = PSUTIL.virtual_memory().percent

        self.event_queue.put((
            "single_result",
            {
                "cancelled": cancelled,
                "sort_time": elapsed,
                "generation_time": generation_time,
                "avg_cpu": avg_cpu,
                "ram": mem,
                "items": numbers_count,
                "batches": completed_passes,
                "score": score_single_core(numbers_count, elapsed),
            },
        ))

    def _merge_sort_iterative(self, arr):
        n = len(arr)
        temp = arr.copy()
        size = 1
        total_passes = max(1, math.ceil(math.log2(max(1, n))))
        completed_passes = 0

        while size < n and not self.cancel_event.is_set():
            for left in range(0, n, 2 * size):
                if self.cancel_event.is_set():
                    break
                mid = min(left + size, n)
                right = min(left + 2 * size, n)
                self._merge(arr, temp, left, mid, right)

            arr[:] = temp[:]
            size *= 2
            completed_passes += 1
            percent = int((completed_passes / total_passes) * 100)
            self.event_queue.put(("progress", min(percent, 100)))
            self.event_queue.put(("batches", completed_passes))

        return completed_passes

    def _merge(self, arr, temp, left, mid, right):
        i, j, k = left, mid, left

        while i < mid and j < right:
            if self.cancel_event.is_set():
                return
            if arr[i] <= arr[j]:
                temp[k] = arr[i]
                i += 1
            else:
                temp[k] = arr[j]
                j += 1
            k += 1

        while i < mid:
            temp[k] = arr[i]
            i += 1
            k += 1

        while j < right:
            temp[k] = arr[j]
            j += 1
            k += 1

    @staticmethod
    def _multicore_worker(batch_counter, stop_event, batch_size: int):
        rng = random.Random()
        effective_size = max(10_000, min(batch_size, 250_000))

        while not stop_event.is_set():
            data = [rng.randint(0, effective_size) for _ in range(effective_size)]
            if stop_event.is_set():
                break
            data.sort()
            if stop_event.is_set():
                break
            with batch_counter.get_lock():
                batch_counter.value += 1

    def _run_multi(self, duration_seconds: int, batch_size: int):
        self.event_queue.put(("status", "Starting multi-core benchmark across all CPU cores..."))

        cpu_count = multiprocessing.cpu_count()
        self.multi_stop_event = multiprocessing.Event()
        self.batch_counter = multiprocessing.Value("i", 0)
        self.processes = []

        for _ in range(cpu_count):
            process = multiprocessing.Process(
                target=self._multicore_worker,
                args=(self.batch_counter, self.multi_stop_event, batch_size),
                daemon=True,
            )
            process.start()
            self.processes.append(process)

        start = time.perf_counter()
        cancelled = False
        effective_batch_size = max(10_000, min(batch_size, 250_000))

        try:
            while True:
                elapsed = time.perf_counter() - start
                if elapsed >= duration_seconds:
                    break
                if self.cancel_event.is_set():
                    cancelled = True
                    break

                progress = int((elapsed / duration_seconds) * 100)
                batches = self.batch_counter.value if self.batch_counter is not None else 0
                self.event_queue.put(("progress", progress))
                self.event_queue.put(("batches", batches))
                time.sleep(0.2)
        finally:
            self.event_queue.put(("status", "Stopping worker processes..."))
            self.multi_stop_event.set()
            for process in self.processes:
                process.join(timeout=0.5)
                if process.is_alive():
                    self.event_queue.put(("status", "Force ending remaining worker processes..."))
                    process.terminate()
                    process.join(timeout=0.5)
                    if process.is_alive():
                        try:
                            process.kill()
                        except AttributeError:
                            pass
                        process.join(timeout=0.2)

        total_elapsed = time.perf_counter() - start
        avg_cpu = sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0.0
        mem = PSUTIL.virtual_memory().percent
        batches = self.batch_counter.value if self.batch_counter is not None else 0
        score = score_multi_core(batches, effective_batch_size, total_elapsed)

        self.event_queue.put(("progress", 100 if not cancelled else min(99, int((total_elapsed / duration_seconds) * 100))))
        self.event_queue.put((
            "multi_result",
            {
                "cancelled": cancelled,
                "elapsed": total_elapsed,
                "avg_cpu": avg_cpu,
                "ram": mem,
                "batches": batches,
                "cores": cpu_count,
                "batch_size": batch_size,
                "effective_batch_size": effective_batch_size,
                "duration": duration_seconds,
                "score": score,
            },
        ))


class MacBenchmarkApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("960x710")
        self.root.minsize(840, 620)
        self.root.configure(bg="#ECECEC")

        try:
            self.root.tk.call("tk", "scaling", 1.25)
        except tk.TclError:
            pass

        self.app_icon = None
        self.last_single_result = None
        self.last_multi_result = None
        self.machine_name_var = tk.StringVar(value=self._default_machine_name())

        self._configure_style()
        self._create_app_icon()
        self._configure_menu()

        self.event_queue = queue.Queue()
        self.worker = BenchmarkWorker(self.event_queue)
        self.timer_running = False
        self.timer_started_at = 0.0
        self.benchmark_type = "single"
        self.selected_preset = "balanced"

        self.single_numbers_var = tk.StringVar(value=str(DEFAULT_SINGLE_CORE_NUMBERS))
        self.multi_duration_var = tk.StringVar(value=str(DEFAULT_MULTICORE_DURATION))
        self.multi_batch_var = tk.StringVar(value=str(DEFAULT_MULTICORE_BATCH_SIZE))

        self.status_var = tk.StringVar(value="Ready")
        self.percent_var = tk.StringVar(value="0%")
        self.timer_var = tk.StringVar(value="Time: 00:00")
        self.usage_var = tk.StringVar(value="CPU: 0.0%   RAM: 0.0%")
        self.batches_var = tk.StringVar(value="Batches Completed: 0")
        self.result_var = tk.StringVar(value="Choose a benchmark mode to begin.")
        self.score_var = tk.StringVar(value="Single Score: —    Multi Score: —    Overall: —")

        self._build_ui()
        self._bind_shortcuts()
        self._apply_preset("balanced")
        self._set_mode("single")
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _default_machine_name(self):
        host = socket.gethostname().strip()
        if host:
            return host
        return platform.node() or "My Mac"

    def _configure_style(self):
        style = ttk.Style()
        available = style.theme_names()
        if "aqua" in available:
            style.theme_use("aqua")
        elif "clam" in available:
            style.theme_use("clam")

        style.configure("Title.TLabel", font=("SF Pro Display", 24, "bold"))
        style.configure("Section.TLabelframe.Label", font=("SF Pro Text", 12, "bold"))
        style.configure("Body.TLabel", font=("SF Pro Text", 12))
        style.configure("Metric.TLabel", font=("SF Mono", 12))
        style.configure("Result.TLabel", font=("SF Pro Text", 12), justify="left")
        style.configure("Score.TLabel", font=("SF Pro Text", 12, "bold"))

    def _create_app_icon(self):
        # A simple generated icon so the app has a Dock/window icon at runtime.
        size = 128
        img = tk.PhotoImage(width=size, height=size)

        # background
        bg = "#111827"
        for x in range(size):
            for y in range(size):
                img.put(bg, (x, y))

        # rounded-ish blue block
        for x in range(14, 114):
            for y in range(14, 114):
                color = "#0A84FF" if 18 <= x <= 110 and 18 <= y <= 110 else "#2563EB"
                img.put(color, (x, y))

        # simple white S shape
        for x in range(34, 94):
            for y in range(28, 42):
                img.put("#FFFFFF", (x, y))
        for x in range(34, 48):
            for y in range(28, 64):
                img.put("#FFFFFF", (x, y))
        for x in range(34, 94):
            for y in range(56, 70):
                img.put("#FFFFFF", (x, y))
        for x in range(80, 94):
            for y in range(56, 100):
                img.put("#FFFFFF", (x, y))
        for x in range(34, 94):
            for y in range(86, 100):
                img.put("#FFFFFF", (x, y))

        self.app_icon = img
        try:
            self.root.iconphoto(True, self.app_icon)
        except Exception:
            pass

    def _configure_menu(self):
        menubar = tk.Menu(self.root)

        app_menu = tk.Menu(menubar, tearoff=0)
        app_menu.add_command(label=f"About {APP_NAME}", command=self._show_about)
        app_menu.add_separator()
        app_menu.add_command(label="View Score History", command=self._show_history)
        app_menu.add_command(label="Build macOS App", command=self._show_build_instructions)
        app_menu.add_separator()
        app_menu.add_command(label="Quit", command=self._on_close, accelerator="⌘Q")
        menubar.add_cascade(label=APP_NAME, menu=app_menu)

        benchmark_menu = tk.Menu(menubar, tearoff=0)
        benchmark_menu.add_command(label="Single-Core Mode", command=lambda: self._set_mode("single"), accelerator="⌘1")
        benchmark_menu.add_command(label="Multi-Core Mode", command=lambda: self._set_mode("multi"), accelerator="⌘2")
        benchmark_menu.add_separator()
        benchmark_menu.add_command(label="Start Benchmark", command=self.start_benchmark, accelerator="⌘R")
        benchmark_menu.add_command(label="Stop Benchmark", command=self.stop_benchmark, accelerator="Esc")
        benchmark_menu.add_separator()
        benchmark_menu.add_command(label="Save Current Result", command=self._save_current_result)
        menubar.add_cascade(label="Benchmark", menu=benchmark_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="How It Works", command=self._show_how_it_works)
        help_menu.add_command(label="Scoring", command=self._show_scoring_info)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="A Mac-friendly desktop benchmark for single-core merge sort and multi-core throughput.",
            style="Body.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        mode_card = ttk.LabelFrame(outer, text="Benchmark Mode", padding=14, style="Section.TLabelframe")
        mode_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        mode_card.columnconfigure(0, weight=1)
        mode_card.columnconfigure(1, weight=1)

        self.single_mode_btn = tk.Button(
            mode_card, text="Single-Core Benchmark",
            command=lambda: self._set_mode("single"), **self._button_base_config()
        )
        self.single_mode_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.multi_mode_btn = tk.Button(
            mode_card, text="Multi-Core Benchmark",
            command=lambda: self._set_mode("multi"), **self._button_base_config()
        )
        self.multi_mode_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        main = ttk.Frame(outer)
        main.grid(row=2, column=0, sticky="nsew")
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(main, text="Controls", padding=16, style="Section.TLabelframe")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(1, weight=1)

        ttk.Label(left, text="Machine name:", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        self.machine_entry = ttk.Entry(left, textvariable=self.machine_name_var)
        self.machine_entry.grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(left, text="Items to sort (single-core):", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        self.single_entry = ttk.Entry(left, textvariable=self.single_numbers_var)
        self.single_entry.grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(left, text="Duration in seconds (multi-core):", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        self.multi_duration_entry = ttk.Entry(left, textvariable=self.multi_duration_var)
        self.multi_duration_entry.grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(left, text="Batch size per core (multi-core):", style="Body.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        self.multi_batch_entry = ttk.Entry(left, textvariable=self.multi_batch_var)
        self.multi_batch_entry.grid(row=3, column=1, sticky="ew", pady=6)

        presets = ttk.Frame(left)
        presets.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 14))
        presets.columnconfigure((0, 1, 2), weight=1)
        self.light_preset_btn = tk.Button(presets, text="Light", command=lambda: self._apply_preset("light"), **self._button_base_config())
        self.light_preset_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.balanced_preset_btn = tk.Button(presets, text="Balanced", command=lambda: self._apply_preset("balanced"), **self._button_base_config())
        self.balanced_preset_btn.grid(row=0, column=1, sticky="ew", padx=6)
        self.stress_preset_btn = tk.Button(presets, text="Stress", command=lambda: self._apply_preset("stress"), **self._button_base_config())
        self.stress_preset_btn.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        ttk.Separator(left).grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)

        ttk.Button(left, text="Start Benchmark", command=self.start_benchmark).grid(row=6, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(left, text="Stop Benchmark", command=self.stop_benchmark).grid(row=7, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(left, text="Save Current Result", command=self._save_current_result).grid(row=8, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(left, text="View History", command=self._show_history).grid(row=9, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(left, text="How It Works", command=self._show_how_it_works).grid(row=10, column=0, columnspan=2, sticky="ew", pady=6)

        right = ttk.LabelFrame(main, text="Live Status", padding=16, style="Section.TLabelframe")
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)

        ttk.Label(right, textvariable=self.status_var, style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.progress = ttk.Progressbar(right, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew")
        ttk.Label(right, textvariable=self.percent_var, style="Metric.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 6))
        ttk.Label(right, textvariable=self.timer_var, style="Metric.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Label(right, textvariable=self.usage_var, style="Metric.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Label(right, textvariable=self.batches_var, style="Metric.TLabel").grid(row=5, column=0, sticky="w", pady=6)

        ttk.Separator(right).grid(row=6, column=0, sticky="ew", pady=14)
        ttk.Label(right, text="Scores", style="Body.TLabel").grid(row=7, column=0, sticky="w")
        ttk.Label(right, textvariable=self.score_var, style="Score.TLabel", wraplength=300).grid(row=8, column=0, sticky="nw", pady=(6, 10))

        ttk.Separator(right).grid(row=9, column=0, sticky="ew", pady=14)
        ttk.Label(right, text="Results", style="Body.TLabel").grid(row=10, column=0, sticky="w")
        ttk.Label(right, textvariable=self.result_var, style="Result.TLabel", wraplength=300).grid(row=11, column=0, sticky="nw", pady=(6, 0))

    def _button_base_config(self):
        return {
            "font": ("SF Pro Text", 11),
            "bg": "#F4F4F4",
            "activebackground": "#E7E7E7",
            "relief": "solid",
            "bd": 1,
            "highlightthickness": 3,
            "highlightbackground": "#C8C8C8",
            "highlightcolor": "#C8C8C8",
            "padx": 10,
            "pady": 8,
            "cursor": "hand2",
        }

    def _set_button_selected(self, button: tk.Button, selected: bool):
        outline = "#0A84FF" if selected else "#C8C8C8"
        bg = "#EAF3FF" if selected else "#F4F4F4"
        button.configure(highlightbackground=outline, highlightcolor=outline, bg=bg, activebackground=bg)

    def _refresh_selection_outlines(self):
        self._set_button_selected(self.single_mode_btn, self.benchmark_type == "single")
        self._set_button_selected(self.multi_mode_btn, self.benchmark_type == "multi")
        self._set_button_selected(self.light_preset_btn, self.selected_preset == "light")
        self._set_button_selected(self.balanced_preset_btn, self.selected_preset == "balanced")
        self._set_button_selected(self.stress_preset_btn, self.selected_preset == "stress")

    def _bind_shortcuts(self):
        self.root.bind("<Escape>", lambda _event: self.stop_benchmark())
        self.root.bind("<Command-q>", lambda _event: self._on_close())
        self.root.bind("<Command-r>", lambda _event: self.start_benchmark())
        self.root.bind("<Command-1>", lambda _event: self._set_mode("single"))
        self.root.bind("<Command-2>", lambda _event: self._set_mode("multi"))

    def _apply_preset(self, preset: str):
        self.selected_preset = preset
        if preset == "light":
            self.single_numbers_var.set("500000")
            self.multi_duration_var.set("15")
            self.multi_batch_var.set("150000")
        elif preset == "balanced":
            self.single_numbers_var.set(str(DEFAULT_SINGLE_CORE_NUMBERS))
            self.multi_duration_var.set(str(DEFAULT_MULTICORE_DURATION))
            self.multi_batch_var.set(str(DEFAULT_MULTICORE_BATCH_SIZE))
        elif preset == "stress":
            self.single_numbers_var.set("5000000")
            self.multi_duration_var.set("60")
            self.multi_batch_var.set("1000000")

        self._refresh_selection_outlines()

    def _set_mode(self, mode: str):
        self.benchmark_type = mode
        if mode == "single":
            self.status_var.set("Ready for single-core benchmark")
            self.result_var.set("This mode sorts one large list using a single CPU core.")
            self.batches_var.set("Batches Completed: 0")
        else:
            self.status_var.set("Ready for multi-core benchmark")
            self.result_var.set("This mode uses all available CPU cores for repeated sorting work.")
            self.batches_var.set("Batches Completed: 0")

        self._refresh_selection_outlines()
        self._update_score_text()

    def _show_about(self):
        single = self.last_single_result["score"] if self.last_single_result else "—"
        multi = self.last_multi_result["score"] if self.last_multi_result else "—"
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\n\n"
            f"Designed to run as a desktop app on macOS.\n"
            f"System: {platform.system()} {platform.release()}\n"
            f"Python: {platform.python_version()}\n"
            f"CPU Cores: {multiprocessing.cpu_count()}\n"
            f"Last Single Score: {single}\n"
            f"Last Multi Score: {multi}",
        )

    def _show_build_instructions(self):
        steps = (
            "To turn this into a real macOS .app on your Mac:\n\n"
            "1. Open Terminal in the folder containing SimpleBench.py\n"
            "2. Install dependencies:\n"
            "   python3 -m pip install psutil pyinstaller\n\n"
            "3. Build the app:\n"
            "   python3 -m PyInstaller --windowed --name SimpleBench SimpleBench.py\n\n"
            "4. Your app will appear in the dist folder as:\n"
            "   dist/SimpleBench.app\n\n"
            "For a prettier custom app icon, build again with:\n"
            "   python3 -m PyInstaller --windowed --name SimpleBench --icon SimpleBench.icns SimpleBench.py"
        )
        messagebox.showinfo("Build macOS App", steps)

    def _show_how_it_works(self):
        messagebox.showinfo(
            "How It Works",
            "Single-Core Benchmark\n\n"
            "Creates one large random list and sorts it with iterative merge sort using a single CPU core.\n\n"
            "Multi-Core Benchmark\n\n"
            "Starts one worker process per CPU core. Each worker repeatedly generates and sorts a batch of random numbers until the timer ends.\n\n"
            "Mac Tips\n\n"
            "Use Light or Balanced presets first on fanless or thin laptops. Stress mode is much heavier on thermals, memory, and battery.",
        )

    def _show_scoring_info(self):
        messagebox.showinfo(
            "Scoring",
            "Single Score\n\n"
            "Based on n·log2(n) work divided by single-core sort time. Higher is better.\n\n"
            "Multi Score\n\n"
            "Based on total items processed per second across all cores. Higher is better.\n\n"
            "Overall\n\n"
            "The geometric mean of the current single and multi scores. Use it only after both tests finish.",
        )

    def _validate_positive_int(self, value: str, label: str) -> int:
        try:
            parsed = int(value.replace("_", "").replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"{label} must be a whole number.") from exc
        if parsed <= 0:
            raise ValueError(f"{label} must be greater than 0.")
        return parsed

    def start_benchmark(self):
        if self.worker.is_running():
            messagebox.showinfo(APP_NAME, "A benchmark is already running.")
            return

        try:
            single_numbers = self._validate_positive_int(self.single_numbers_var.get(), "Single-core item count")
            multi_duration = self._validate_positive_int(self.multi_duration_var.get(), "Multi-core duration")
            multi_batch = self._validate_positive_int(self.multi_batch_var.get(), "Multi-core batch size")
        except ValueError as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        if single_numbers > 10_000_000:
            if not messagebox.askyesno(
                "Large Workload",
                "Sorting more than 10,000,000 items can use a lot of memory and may make your Mac feel unresponsive. Continue?",
            ):
                return

        if multi_batch > 2_000_000:
            if not messagebox.askyesno(
                "Large Workload",
                "A multi-core batch size above 2,000,000 is very heavy on memory and CPU. Continue?",
            ):
                return

        self.progress["value"] = 0
        self.percent_var.set("0%")
        self.timer_var.set("Time: 00:00")
        self.usage_var.set("CPU: 0.0%   RAM: 0.0%")
        self.result_var.set("Benchmark in progress...")
        self.batches_var.set("Batches Completed: 0")
        self.status_var.set("Starting benchmark...")

        self.timer_started_at = time.perf_counter()
        self.timer_running = True
        self._tick_timer()
        self.worker.start(self.benchmark_type, single_numbers, multi_duration, multi_batch)

    def stop_benchmark(self):
        if not self.worker.is_running():
            return
        self.worker.cancel()
        self.status_var.set("Stopping benchmark... waiting for worker processes to exit")

    def _tick_timer(self):
        if not self.timer_running:
            return
        elapsed = int(time.perf_counter() - self.timer_started_at)
        minutes, seconds = divmod(elapsed, 60)
        self.timer_var.set(f"Time: {minutes:02d}:{seconds:02d}")
        self.root.after(250, self._tick_timer)

    def _poll_events(self):
        try:
            while True:
                event = self.event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _handle_event(self, event):
        event_type = event[0]

        if event_type == "status":
            self.status_var.set(event[1])
        elif event_type == "progress":
            percent = max(0, min(100, int(event[1])))
            self.progress["value"] = percent
            self.percent_var.set(f"{percent}%")
        elif event_type == "usage":
            avg_cpu, mem = event[1], event[2]
            self.usage_var.set(f"CPU: {avg_cpu:.1f}%   RAM: {mem:.1f}%")
        elif event_type == "batches":
            self.batches_var.set(f"Batches Completed: {event[1]}")
        elif event_type == "single_result":
            result = event[1]
            self.timer_running = False
            self.last_single_result = result
            self._update_score_text()
            if result["cancelled"]:
                self.status_var.set("Single-core benchmark cancelled")
                self.result_var.set(
                    f"Cancelled after sorting started.\n"
                    f"Data generation: {result['generation_time']:.2f}s\n"
                    f"Elapsed sort time: {result['sort_time']:.2f}s\n"
                    f"Batches completed: {result['batches']}\n"
                    f"Single score: {result['score']}"
                )
            else:
                self.progress["value"] = 100
                self.percent_var.set("100%")
                self.status_var.set("Single-core benchmark complete")
                self.result_var.set(
                    f"Items sorted: {result['items']:,}\n"
                    f"Data generation: {result['generation_time']:.2f}s\n"
                    f"Sort time: {result['sort_time']:.2f}s\n"
                    f"Batches completed: {result['batches']}\n"
                    f"Average CPU: {result['avg_cpu']:.1f}%\n"
                    f"RAM in use: {result['ram']:.1f}%\n"
                    f"Single score: {result['score']}"
                )
                self._save_result_to_history("single", result)
        elif event_type == "multi_result":
            result = event[1]
            self.timer_running = False
            self.last_multi_result = result
            self._update_score_text()
            if result["cancelled"]:
                self.status_var.set("Multi-core benchmark cancelled")
            else:
                self.status_var.set("Multi-core benchmark complete")
                self._save_result_to_history("multi", result)
            self.result_var.set(
                f"CPU cores used: {result['cores']}\n"
                f"Runtime: {result['elapsed']:.2f}s\n"
                f"Batches completed: {result['batches']}\n"
                f"Requested batch size: {result['batch_size']:,}\n"
                f"Effective batch size: {result['effective_batch_size']:,}\n"
                f"Average CPU: {result['avg_cpu']:.1f}%\n"
                f"RAM in use: {result['ram']:.1f}%\n"
                f"Multi score: {result['score']}"
            )
        elif event_type == "error":
            self.timer_running = False
            self.status_var.set("Benchmark failed")
            self.result_var.set(event[1])
            messagebox.showerror(APP_NAME, event[1])
        elif event_type == "done":
            self.timer_running = False

    def _current_overall_score(self):
        if not self.last_single_result or not self.last_multi_result:
            return None
        s1 = self.last_single_result.get("score", 0)
        s2 = self.last_multi_result.get("score", 0)
        if s1 <= 0 or s2 <= 0:
            return None
        return int(math.sqrt(s1 * s2))

    def _update_score_text(self):
        single_score = self.last_single_result["score"] if self.last_single_result else "—"
        multi_score = self.last_multi_result["score"] if self.last_multi_result else "—"
        overall = self._current_overall_score()
        overall_text = overall if overall is not None else "—"
        self.score_var.set(f"Single Score: {single_score}    Multi Score: {multi_score}    Overall: {overall_text}")

    def _load_history(self):
        if not os.path.exists(HISTORY_FILE):
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def _save_history(self, rows):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not save history:\n{exc}")

    def _save_result_to_history(self, benchmark_type, result):
        rows = self._load_history()
        rows.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "machine_name": self.machine_name_var.get().strip() or self._default_machine_name(),
            "type": benchmark_type,
            "score": result.get("score", 0),
            "system": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "cpu_cores": multiprocessing.cpu_count(),
            "avg_cpu": round(float(result.get("avg_cpu", 0.0)), 1),
            "ram": round(float(result.get("ram", 0.0)), 1),
            "details": result,
        })
        self._save_history(rows)

    def _save_current_result(self):
        saved = False
        if self.last_single_result and not self.last_single_result.get("cancelled"):
            self._save_result_to_history("single", self.last_single_result)
            saved = True
        if self.last_multi_result and not self.last_multi_result.get("cancelled"):
            self._save_result_to_history("multi", self.last_multi_result)
            saved = True
        if saved:
            messagebox.showinfo(APP_NAME, "Current completed result(s) saved to history.")
        else:
            messagebox.showinfo(APP_NAME, "There is no completed benchmark result to save yet.")

    def _show_history(self):
        rows = self._load_history()
        win = tk.Toplevel(self.root)
        win.title(f"{APP_NAME} Score History")
        win.geometry("980x480")
        if self.app_icon is not None:
            try:
                win.iconphoto(True, self.app_icon)
            except Exception:
                pass

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        ttk.Label(frame, text=f"{APP_NAME} Score History", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="Use these saved scores to compare machines over time.", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 10))

        columns = ("timestamp", "machine", "type", "score", "cores", "cpu", "ram", "system")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        tree.grid(row=2, column=0, sticky="nsew")

        headings = {
            "timestamp": "Timestamp",
            "machine": "Machine",
            "type": "Test",
            "score": "Score",
            "cores": "Cores",
            "cpu": "Avg CPU %",
            "ram": "RAM %",
            "system": "System",
        }
        widths = {
            "timestamp": 160,
            "machine": 160,
            "type": 80,
            "score": 90,
            "cores": 70,
            "cpu": 90,
            "ram": 80,
            "system": 180,
        }
        for key in columns:
            tree.heading(key, text=headings[key])
            tree.column(key, width=widths[key], anchor="center" if key not in ("machine", "system", "timestamp") else "w")

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        for row in reversed(rows):
            tree.insert("", "end", values=(
                row.get("timestamp", ""),
                row.get("machine_name", ""),
                row.get("type", ""),
                row.get("score", ""),
                row.get("cpu_cores", ""),
                row.get("avg_cpu", ""),
                row.get("ram", ""),
                row.get("system", ""),
            ))

        best_single = max((r for r in rows if r.get("type") == "single"), key=lambda r: r.get("score", 0), default=None)
        best_multi = max((r for r in rows if r.get("type") == "multi"), key=lambda r: r.get("score", 0), default=None)

        summary_text = "Best Single: "
        summary_text += f"{best_single['machine_name']} ({best_single['score']})" if best_single else "—"
        summary_text += "    |    Best Multi: "
        summary_text += f"{best_multi['machine_name']} ({best_multi['score']})" if best_multi else "—"

        ttk.Label(frame, text=summary_text, style="Score.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 0))

    def _on_close(self):
        if self.worker.is_running():
            should_close = messagebox.askyesno(
                APP_NAME,
                "A benchmark is still running. Stop it and quit?",
            )
            if not should_close:
                return
            self.worker.cancel()
            self.root.after(300, self.root.destroy)
            return
        self.root.destroy()


def main():
    multiprocessing.freeze_support()
    if sys.platform == "darwin":
        try:
            multiprocessing.set_start_method("spawn", force=True)
        except RuntimeError:
            pass

    root = tk.Tk()
    app = MacBenchmarkApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
