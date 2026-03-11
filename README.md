# QuickBench

A desktop CPU benchmark for macOS, Windows, and Linux built with Python and tkinter.

Tests both single-core and multi-core performance using merge sort — a real-world algorithm that exercises integer operations, memory allocation, and cache behaviour.

![QuickBench screenshot](MAC%20Build/QB.png)

---

## Features

- **Single-Core Benchmark** — sorts a large list on one core, measures raw clock speed
- **Multi-Core Benchmark** — runs parallel workers across all CPU cores for a set duration
- **Live Status** — real-time CPU %, RAM %, timer, and batch counter while running
- **Score History** — saves every result locally so you can track changes over time
- **System Info** — detects CPU, GPU, RAM, and platform automatically
- **Cross-platform** — macOS (Apple Silicon + Intel), Windows, and Linux

---

## Run from source

**Requirements:** Python 3.9+ and psutil

```bash
pip install psutil
python3 QuickBench.py
```

On first launch, if any required packages are missing the app will offer to install them automatically.

---

## Build the macOS .app and .dmg

All build files are in the `MAC Build/` folder.

**Requirements:** macOS with Python 3.9+ installed

```bash
cd 'MAC Build'
chmod +x build_mac.sh
./build_mac.sh
```

The script will automatically:
1. Install `pyinstaller` and `pillow` via pip (build tools only)
2. Generate `QB.icns` from `QB.png`
3. Build a self-contained `QuickBench.app` (no Python installation needed to run it)
4. Package it as `QuickBench.dmg` with a drag-to-Applications installer

The finished `QuickBench.dmg` will appear in the `MAC Build/` folder.

**To install from the DMG:**
1. Double-click `QuickBench.dmg`
2. Drag QuickBench → Applications
3. First launch: right-click → Open → Open (macOS security prompt, once only)

---

## Download

Pre-built releases are available on the [Releases](../../releases) page.

---

## License

MIT — see [LICENSE](LICENSE)
