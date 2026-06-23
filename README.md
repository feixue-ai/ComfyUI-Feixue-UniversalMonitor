# ComfyUI-Feixue-UniversalMonitor

<p align="center">
  <strong>Feixue Universal Monitor</strong> — AMD-focused · Cross-platform · 5 Colors × 5 Styles · Real-time Hardware Monitor
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ComfyUI-Compatible-brightgreen" alt="ComfyUI Compatible" />
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-blue" alt="Platform" />
  <img src="https://img.shields.io/badge/GPU-AMD_Optimized-orange" alt="GPU Support" />
  <img src="https://img.shields.io/badge/Version-3.26-red" alt="Version" />
  <img src="https://img.shields.io/badge/Styles-5_Colors_%C3%97_5_Styles-blueviolet" alt="25 Combinations" />
</p>

<p align="center">
  <a href="https://feixue-ai.github.io/ComfyUI-Feixue-UniversalMonitor/?demo">🖥️ Live Preview (Live Demo)</a>
</p>

---

## Preview

![Feixue Universal Monitor Premium UI v3.26](screenshot.png)

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
- **Cross-platform AMD optimization** — Windows (pynvml / WMI) and Linux (amdsmi / ROCm / sysfs) with three-level fallback degradation
- **WebSocket real-time push** — data pushed with sub-100ms latency, with an HTTP API fallback mode
- **Zero external frontend dependencies** — single `extension.js` file contains all UI, CSS, events, and data logic

---

## Installation

### Method 1: ComfyUI Manager (Recommended)

1. Open ComfyUI → **Manager** → **Install Custom Nodes**
2. Search for: `ComfyUI-Feixue-UniversalMonitor`
3. Click **Install** → **Restart** ComfyUI

The install script will automatically detect the operating system and install the corresponding dependencies:
- **Windows**: `pynvml-amd-windows` (ADLX GPU monitoring), `wmi` (system info)
- **Linux**: `amdsmi` (official AMD GPU monitoring library)

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
├── collectors/              # Data collectors (CPU, Memory, Predictor)
├── providers/amd/           # AMD GPU data sources (ROCm/sysfs)
├── config/                  # Configuration management
├── utils/                   # Platform detection, thread safety, performance optimization
├── web/
│   └── extension.js         # Frontend UI (Premium UI v3.26)
├── docs/
│   └── index.html           # Online appearance demo (GitHub Pages)
└── tests/                   # Unit tests
```

---

## Technical Details

| Layer | Tech Stack |
|------|--------|
| **Backend Data Collection** | Python (psutil, pynvml-amd-windows, amdsmi, WMI, PyTorch) |
| **Frontend UI** | Vanilla JavaScript (zero external dependencies, single self-contained file) |
| **Data Channel** | WebSocket (`feixue.monitor` event) + HTTP REST API |
| **Compatibility** | ComfyUI (Windows / Linux Ubuntu), AMD / NVIDIA GPU |

### Data Collection Strategy

```
GPU data source priority:
  Windows: pynvml (ADLX) → PyTorch → PowerShell → WMI
  Linux:   amdsmi → rocm_smi → sysfs

CPU/RAM/Swap: psutil (unified cross-platform)
```

All collection operations have timeout protection (≤8s). On exceptions, the system automatically degrades to cached data or safe default values, ensuring the ComfyUI main workflow is not affected.

---

## Changelog

### v3.26 — Premium UI 5 Colors × 5 Styles Refactor + Stability Fixes (Current)

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
