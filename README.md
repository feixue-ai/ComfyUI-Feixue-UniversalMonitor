# ComfyUI-Feixue-UniversalMonitor — ComfyUI Hardware Monitor / ComfyUI Monitor

<p align="center">
  <strong>Feixue Universal Monitor</strong> — AMD-focused · Cross-platform · 5 Colors × 5 Styles · Real-time Hardware Monitor for ComfyUI
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ComfyUI-Compatible-brightgreen" alt="ComfyUI Compatible" />
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-blue" alt="Platform" />
  <img src="https://img.shields.io/badge/GPU-AMD_Optimized-orange" alt="GPU Support" />
  <img src="https://img.shields.io/badge/Version-3.40.8-red" alt="Version" />
  <img src="https://img.shields.io/badge/Styles-5_Colors_%C3%97_5_Styles-blueviolet" alt="25 Combinations" />
</p>

<p align="center">
  <a href="https://feixue-ai.github.io/ComfyUI-Feixue-UniversalMonitor/?demo">🖥️ Live Preview (Live Demo)</a>
</p>

<p align="center">
  <strong>English:</strong> A real-time ComfyUI hardware monitor widget. Track GPU utilization, VRAM, CPU, RAM, swap, temperature, disk I/O, and network speed right inside ComfyUI. Zero pip dependency on Windows; zero ROCm dependency on Linux AMD. If this project helps your workflow, please consider giving us a ⭐ — it means a lot!
</p>

<p align="center">
  <strong>中文：</strong>飞雪监测器是一款 ComfyUI 实时硬件监测插件，在 ComfyUI 界面内悬浮显示 GPU/显存/CPU/内存/SWAP/温度/磁盘/网络。Windows 零 pip 依赖，Linux AMD 零 ROCm 依赖。如果觉得有用，欢迎 <a href="https://github.com/feixue-ai/ComfyUI-Feixue-UniversalMonitor">点个 ⭐</a> 支持我们！
</p>

---

## Preview

![Feixue Universal Monitor Premium UI v3.40.8](screenshot.png)

> The screenshot above shows the Premium UI **Neu** style monitor bar — a white neumorphic design with medical-instrument-style recessed windows, precise groove bases, and soft embossed shadows. It displays six real-time metrics: GPU / VRAM / CPU / RAM / SWAP / TEMP.
>
> The plugin supports **5 color schemes × 5 visual styles**, for a total of **25 combinations**, switchable with one click in the settings panel.
>
> Live demo (early design prototype, not the actual ComfyUI UI): [Live Demo](https://feixue-ai.github.io/ComfyUI-Feixue-UniversalMonitor/?demo)

### 5 Visual Styles

| Style | Name | Design Highlights |
|------|--------|-------------------|
| **Neu** | Neu | White neumorphism, medical-instrument recessed windows, precise groove base, soft embossed shadows |
| **Jade Bamboo** | Jade Bamboo | Horizontal jade bamboo monitor bar with 8 naturally connected segments, jade cylindrical gloss, and a bamboo-slip settings panel |
| **Retro Terminal** | Retro | CRT phosphor screen effect, LED segment bars, scanlines and glow, supports 5 phosphor colors |
| **Luxury Cabinet** | Lux | Black-gold luxury showcase, gold trim with gemstone tones, high-contrast data cards |
| **Quantum Core** | Cyber | Heavy titanium frame + neon tubes, HUD numbers, futuristic sci-fi aesthetic |

### 5 Color Schemes

Aurora Ceramic / Deep Sea Blue / Sunset Warm / Forest Green / Midnight Black (each style maps these to corresponding material or phosphor colors).

---

## Features

- **Real-time hardware monitoring** — GPU utilization, VRAM (displayed in GB), CPU load, physical RAM, virtual memory (Swap), GPU temperature, disk I/O, network speed — 8 metrics in total
- **5 colors × 5 styles independently combinable** — color and visual style are fully decoupled, 25 combinations switchable with one click
- **Auto Chinese/English adaptation** — labels automatically display in Chinese or English based on browser language, avoiding translation software and layout overflow
- **Workflow sound alerts** — plays a sound when a ComfyUI workflow completes or errors; toggle state persists and syncs across themes
- **Drag-to-position** — enable drag mode to move the monitor bar freely; disable to automatically return to top-center; auto-repositions after theme switching
- **Collapsible floating panel** — click the gear icon to open the settings panel with expandable/collapsible sections
- **Neu medical instrument windows** — monitor bars use precisely inset instrument windows + continuous groove bases for a premium feel
- **Jade Bamboo monitor bar** — horizontal jade bamboo shape with 8 naturally connected segments, jade cylindrical gloss, and a bamboo-slip settings panel that strongly contrasts with Neu
- **Cross-platform AMD optimization** — Windows (AMD ADLX C++ Bridge DLL first, native driver-level) and Linux (libamd_smi.so ctypes first for accuracy, then sysfs direct kernel-driver read as zero-dependency fallback, plus rocm_smi / NVIDIA NVML) with clean source priority
- **WebSocket real-time push** — data pushed with sub-100ms latency, with an HTTP API fallback mode
- **Zero external frontend dependencies** — single `extension.js` file contains all UI, CSS, events, and data logic

---

## Installation

### Method 1: ComfyUI Manager (Recommended)

1. Open ComfyUI → **Manager** → **Install Custom Nodes**
2. Search for: `ComfyUI-Feixue-UniversalMonitor`
3. Click **Install** → **Restart** ComfyUI

The install script will automatically detect the operating system and GPU vendor, then install dependencies only when necessary:
- **Windows AMD**: ADLX C++ Bridge DLL (`libs/feixue_adlx_bridge.dll`) provides full GPU metrics directly from the AMD driver — **zero pip dependencies**
- **Windows NVIDIA**: Uses native driver `nvml.dll` directly — zero pip dependencies
- **Windows fallback**: System PDH counters + DXGI if no native driver interface is available
- **Linux AMD**: Reads GPU metrics directly from the AMDGPU kernel driver via `sysfs` (`/sys/class/drm`) — **zero pip dependencies and zero ROCm dependency**; falls back to system `libamd_smi.so` (ctypes) / `rocm_smi` / NVIDIA NVML
- **Linux NVIDIA**: Uses the driver's native `libnvidia-ml.so` — no extra pip dependencies
- **Base dependency**: `psutil` only

### Method 2: Manual Installation

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/feixue-ai/ComfyUI-Feixue-UniversalMonitor.git
```

Then restart ComfyUI. The plugin will automatically start the backend monitoring service.

---

## Usage

After installation, the monitor bar automatically appears at the top of the ComfyUI interface:

- **6 core metrics**: GPU Utilization | VRAM | CPU Load | Physical RAM | Virtual Memory (Swap) | GPU Temperature
- **2 auxiliary metrics**: Disk I/O | Network Speed (viewable in the floating panel)
- **Theme switching**: Click the ⚙️ gear button on the right side of the monitor bar to open the settings panel, then switch between "Style" and "Color"
- **Sound alerts**: Enable/disable in the settings panel; the state is automatically saved and synced across all themes
- **Drag positioning**: Enable "Drag Mode" to drag the monitor bar; disable to return it to top-center
- **Real-time updates**: Default refresh interval is 2 seconds; data is pushed in real time via WebSocket

---

## Project Structure

```
ComfyUI-Feixue-UniversalMonitor/
├── __init__.py              # Plugin entry & HTTP API routes
├── pyproject.toml           # Package metadata & ComfyUI registry info
├── install.py               # Cross-platform automatic dependency installation
├── requirements.txt         # Base dependency declaration
├── core/
│   ├── monitor.py           # Core hardware collection engine (FeixueHardwareInfo)
│   ├── websocket_service.py # WebSocket real-time push service
│   └── data_models.py       # Data model definitions
├── collectors/              # Data collectors (CPU, Memory, GPU providers)
│   └── gpu_providers/       # AMD/NVIDIA GPU data providers
├── config/                  # Configuration management
├── fxm_utils/               # Platform detection, thread safety, performance optimization
├── web/
│   └── extension.js         # Frontend UI (Premium UI v3.40.8)
├── docs/
│   └── index.html           # Online appearance demo (GitHub Pages)
└── tests/                   # Unit tests
```

---

## Technical Details

| Layer | Tech Stack |
|------|--------|
| **Backend Data Collection** | Python (psutil, ctypes native libraries on Windows/Linux) |
| **Frontend UI** | Vanilla JavaScript (zero external dependencies, single self-contained file) |
| **Data Channel** | WebSocket (`feixue.monitor` event) + HTTP REST API |
| **Compatibility** | ComfyUI (Windows / Linux Ubuntu), AMD / NVIDIA GPU |

### Data Collection Strategy

```
GPU data source priority:
  Windows: AMD ADLX C++ Bridge DLL → AMD ADL (atiadlxx.dll) → NVIDIA NVML (nvml.dll) → PDH counters + DXGI field-level fallback
  Linux:   libamd_smi.so (ctypes) → sysfs (/sys/class/drm amdgpu kernel driver) → rocm_smi → NVIDIA NVML

CPU/RAM/Swap: psutil (unified cross-platform)
```

All collection operations have timeout protection (≤8s). On exceptions, the system automatically falls back to cached data or safe default values, ensuring the ComfyUI main workflow is not affected. Inaccurate legacy methods (WMI / pynvml-amd-windows) have been removed; fan monitoring has also been removed to reduce complexity.

**Field-level fallback** (Windows): when the primary provider returns an invalid individual metric, DXGI fills missing VRAM and PDH fills missing GPU utilization, so each value is independently sourced from the most reliable interface available.

---

## Changelog

### v3.40.8 — Position Persistence Hardening + SEO / Docs Polish (Current)

- **Position persistence hardening**: Added `fxm_panel_version` migration. When upgrading to v3.40.8, stale `fxm_drag_pos_*` entries from older builds are automatically cleared, preventing the Jade Bamboo / Luxury Cabinet themes from appearing off-center after a theme switch
- **Dock default centering preserved**: All themes still default to horizontally centered, below the ComfyUI workflow tab bar (`top: 46px; left: 50%; transform: translateX(-50%)`). User-dragged positions continue to be saved per theme and restored only while drag mode is enabled
- **SEO & discoverability**: README title and pyproject metadata now include "ComfyUI Hardware Monitor" / "ComfyUI Monitor" keywords to improve English search visibility; added English introduction and star-call-to-action in README
- **Version unification**: All code, UI panel, package metadata, and snapshot format unified to v3.40.8

### v3.40.7 — Linux AMD SMI Accuracy + Field-Level Fallback

- **Linux GPU priority changed to amdsmi first**: After an accuracy comparison against `rocm-smi` and direct `sysfs` reads, `AmdSmiProvider` (ctypes direct call to `libamd_smi.so`) is now the primary Linux AMD source. It provides the most accurate GPU utilization, VRAM, temperature, and power readings under both idle and load. `sysfs` remains as the zero-dependency fallback, and `rocm_smi` is kept for legacy ROCm 5.x compatibility
- **Zero pip dependency preserved**: `AmdSmiProvider` still does **not** require the `amdsmi` Python package; it binds `libamd_smi.so` via ctypes and searches `/opt/rocm`, `/opt/rocm-6.x`, `LD_LIBRARY_PATH`, and `FEIXUE_AMD_SMI_PATH`. If the library is unavailable, monitoring automatically falls back to `sysfs`
- **Linux field-level fallback (数值分段降级)**: When the primary provider (amdsmi/rocm_smi) returns 0 or missing values for individual fields — common across different ROCm versions or GPU models — the same field is independently filled from `sysfs`. Each field is evaluated once and cached, so valid fields incur zero fallback overhead
- **Temperature aligned with rocm-smi**: All Linux temperature reads now prefer junction/hotspot sensors (`temp2_input` for sysfs, `AMDSMI_TEMPERATURE_TYPE_HOTSPOT` for amdsmi) before falling back to edge temperature, matching the values shown by `rocm-smi` and vitals tools
- **Sysfs cache TTL reduced**: `BatchSysfsReader` default cache TTL lowered from 0.5s to 0.1s to reduce VRAM lag during rapid workload changes
- **Field-level tiered fallback (Windows)**: Each metric field is supplemented independently — DXGI fills missing VRAM, PDH fills missing utilization (same data source as Windows Task Manager). First-invalid detection is cached for zero overhead on subsequent calls
- **AmdSmiProvider rewritten with ctypes + multi-version ROCm discovery**: Directly calls the system `libamd_smi.so` without importing the `amdsmi` Python package. Function bindings are fault-tolerant so older/newer ROCm versions degrade gracefully instead of crashing
- **ADLX C++ Bridge DLL (Windows first priority)**: Compiled `feixue_adlx_bridge.dll` wraps AMD ADLX SDK via `extern "C"` — provides full GPU metrics (utilization / VRAM used / VRAM total / temperature) directly from the AMD driver. Zero pip dependency, ships as a prebuilt DLL in `libs/`
- **503 fix / monitor stays alive when GPU source fails**: `_MonitorWrapper` no longer sets `is_running = False` just because the GPU provider failed; CPU/RAM monitoring continues and the HTTP/WebSocket APIs remain available
- **Module shadowing protection**: `__init__.py` now cleans non-plugin `core` modules from `sys.modules` and moves the plugin root to the front of `sys.path`, preventing other custom nodes from shadowing `core.monitor`
- **Theme switch no blank window**: Switching UI styles now immediately renders the latest cached snapshot into the newly visible theme, removing the ~0.5s empty-data gap
- **Responsive layout fix**: Dock and Panel now adapt to narrow viewports (Trae CN side panel / mobile remote control) without overlapping or text wrapping artifacts
- **Version unification**: All code, UI panel, package metadata, and snapshot format unified to v3.40.7

### v3.30 — PDH VRAM Fix + Capsule Bounce Fix

- **VRAM display fix (Windows AMD)**: Fixed PDH counter enumeration bug — `PdhEnumObjectItemsW` first call returns `PDH_MORE_DATA` which was incorrectly treated as failure, causing VRAM to always show 0. Now correctly handles the two-call enumeration pattern
- **Unicode buffer parsing fix**: Replaced `instance_buf.raw` (not available on `create_unicode_buffer`) with character-by-character iteration for proper instance name parsing
- **Capsule bounce fix**: Changed `.fx-capsule-dock` CSS transition from `all 0.4s ease` to `box-shadow, border-color` to prevent container size animation during high-load data updates
- **Version unification**: All code, panel, package metadata, and snapshot format unified to v3.30

### v3.29.2 — Zero-Dependency Native Monitoring Refactor

- **Zero pip dependency on Windows**: GPU monitoring now uses native driver DLLs — `atiadlxx.dll` for AMD, `nvml.dll` for NVIDIA, and `pdh.dll` as a system-level fallback
- **Removed inaccurate legacy methods**: WMI and `pynvml-amd-windows` fallbacks have been completely removed
- **On-demand Linux dependency installation**: `amdsmi` Python bindings are installed only when the system-level `libamd_smi.so` library is present; otherwise `sysfs` is used
- **Removed fan monitoring**: Fan speed collection removed from backend to reduce complexity and bug risk (UI already hid this metric)
- **Data source quality indicator**: Added `data_source_quality` field (`full` / `limited` / `minimal`) and one-time log warnings when running in fallback mode
- **WebSocket delta crash fix**: Fixed `KeyError: 'percent'` in `_dict_delta` caused by missing fan-speed data
- **Icon refresh**: Updated ComfyUI registry icon and added promotional poster asset
- **Version unification**: All code, panel, package metadata, and snapshot format unified to v3.29.2

### v3.28 — Smart Memory Cleanup + Stability Hardening

- **Smart memory cleanup**: Added a 3-mode switch in the settings panel (**Off / RAM Defrag / Deep Clean**) with user-controllable RAM threshold and idle confirmation delay
- **Safe deep clean**: Deep clean uses ComfyUI's native `/free` queue flags instead of direct `unload_all_models()`, preventing mosaic/corruption artifacts during workflow execution
- **RAM-only mode**: RAM defrag only runs `gc.collect()` + Linux `malloc_trim(0)` without touching models or VRAM, eliminating the risk of interrupting generation
- **Adaptive idle delay**: Auto-detects segmented/continuous workflows and extends the idle delay from 2s to 8s; falls back after 10 minutes of normal usage
- **Dynamic cooldown**: Normal single-image users get a 5s minimum cooldown; segmented/continuous workflows get a 30s cooldown to avoid repeated cleanups
- **Manual cleanup always available**: The "Deep Free Now" button works regardless of the auto-cleanup mode switch and shows a non-blocking toast instead of a blocking confirm dialog
- **Cyber style VRAM fix**: VRAM unit now correctly displays "GB" in the Quantum Core style
- **Version unification**: All code, panel, and package metadata unified to v3.28

### v3.26 — Premium UI 5 Colors × 5 Styles Refactor + Stability Fixes

- **5 new visual styles**: Neu, Jade Bamboo, Retro, Lux, Cyber
- **5 independently switchable color schemes**: Aurora Ceramic / Deep Sea Blue / Sunset Warm / Forest Green / Midnight Black
- **Chinese/English auto adaptation**: Displays Chinese or English based on system language; key labels stay short to avoid UI overflow
- **VRAM uniformly displayed in GB**: VRAM shown as used/total capacity (GB) in all dock styles and panels
- **Persistent sound alert sync**: Fixed inconsistent sound alert toggle state after theme switching; supports cross-theme memory
- **Auto reposition on theme switch**: Monitor bar automatically returns to top-center after style switch, avoiding stale positions
- **Lux temperature display fix**: Added GPU temperature rendering for the Lux style
- **Cyber collapsible panel fix**: Fixed expand/collapse failure in the Cyber style settings panel
- **Neu medical instrument windows redo**: Chips changed to precisely inset instrument windows with aligned groove bases, evoking high-end medical equipment
- **Jade Bamboo theme redo**: Horizontal jade bamboo monitor bar with 8 naturally connected segments, jade cylindrical gloss, and a bamboo-slip settings panel that strongly contrasts with Neu
- **Jade Bamboo high-contrast adaptive metrics**: Text/progress bar colors automatically switch with theme, avoiding being overwhelmed by orange/purple backgrounds
- **Retro dark LED bar fix**: Restored dark inactive background bars to keep the monitor bar visually full
- **Frontend stability fixes**: Fixed drag listener leaks, Retro font loading, theme body background overlay, fetch timeout timer leaks, localStorage privacy mode exceptions
- **Backend stability fixes**: WebSocket monitor loop exception protection, amdsmi init failure resource release, BatchSysfsReader thread safety, thread pool shutdown exception handling, refresh-rate API boundary validation
- **Version unification**: Code, panel, and package metadata all unified to v3.26
- **Legacy code cleanup**: Removed dead code and DEBUG logs from the old Emerald Capsule / v13 theme system

### v3.1.0 — Obsidian Glass Refactor + Full 5-Style Isolation

- Floating panel fully refactored: semi-transparent frosted glass + multi-layer diffuse shadows + glass edge highlights
- 5 styles fully visually isolated
- Added disk I/O and network speed monitoring
- All metrics available cross-platform

### v3.0.1 — Emerald Capsule

- Complete UI rewrite: pill/capsule design + 3D cylindrical cross-section stereo effect
- Added 5-color theme system
- Added drag-to-position feature
- Added Swap virtual memory monitoring

### v2.5.0

- First public release
- Basic monitoring functions (GPU/CPU/RAM)
- WebSocket real-time push

---

## License

MIT License

---

## Author

[Feixue Team](https://github.com/feixue-ai)
