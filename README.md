# ComfyUI-Feixue-UniversalMonitor

<p align="center">
  <strong>飞雪监测器</strong> — 专注AMD · 跨平台 · 5色×5风格 · 实时硬件监测器
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ComfyUI-Compatible-brightgreen" alt="ComfyUI Compatible" />
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-blue" alt="Platform" />
  <img src="https://img.shields.io/badge/GPU-AMD_Optimized-orange" alt="GPU Support" />
  <img src="https://img.shields.io/badge/Version-3.1.0-red" alt="Version" />
  <img src="https://img.shields.io/badge/Styles-5_Colors_×_5_Styles-blueviolet" alt="25 Combinations" />
</p>

<p align="center">
  <a href="https://feixue-ai.github.io/ComfyUI-Feixue-UniversalMonitor/?demo">🖥️ 在线预览外观 (Live Demo)</a>
</p>

---

## 外观预览

![飞雪监测器 Emerald Capsule UI](screenshot.png)

> 上图展示了翡翠胶囊风格（Emerald Capsule）的监控栏。支持 **5 种颜色主题 × 5 种风格预设**，共 25 种视觉搭配，一键切换。
>
> 在线交互演示：[Live Demo](https://feixue-ai.github.io/ComfyUI-Feixue-UniversalMonitor/?demo)

---

## 特性

- **实时硬件监测** — GPU 利用率、显存(VRAM)、CPU 负载、物理内存(RAM)、虚拟内存(Swap)、GPU 温度、磁盘 I/O、网络速率，共 8 项指标
- **黑曜石毛玻璃面板** — 半透明毛玻璃悬浮面板 (backdrop-filter) + 多层弥散阴影 + 玻璃边缘高光，现代设计水准
- **5 色主题系统** — 翡翠绿 / 赛博紫 / 琥珀金 / 极光蓝 / 樱花粉，一键切换整体色彩方案
- **5 种风格预设** — 翡翠胶囊 / 赛博钛金 / 生物发光 / 结构蓝图 / 极简像素，颜色与风格独立组合（共 25 种搭配）
- **完整的视觉隔离** — 每种风格从形状、材质、边框到光效完全不同，胶囊独有 3D 圆柱::before 效果
- **拖拽自由定位** — 悬浮面板开关控制，可自由拖拽监测栏到任意位置，位置自动记忆（localStorage）
- **CSS 芯片图标** — 每种硬件对应独特的 CSS 绘制图标（GPU 芯片、VRAM 颗粒、CPU 处理器、RAM 内存条、存储、温度计）
- **凹陷进度条** — 内阴影凹陷轨道 + 渐变流体填充 + 缓慢漂移动画，直观展示各项资源使用率
- **跨平台 AMD 优化** — Windows（pynvml-amd-windows + WMI）和 Linux Ubuntu（amdsmi / ROCm / sysfs），专为 AMD GPU 优化
- **多源数据融合** — 三级 fallback 降级链，高负载下稳定可靠，超时保护 + 缓存降级
- **WebSocket 实时推送** — 低于 100ms 延迟的数据推送，同时提供 HTTP API 降级模式
- **工业方形拨动开关** — 拖拽开关采用方形机械拨动设计，贴合硬核硬件监测器定位

## 安装

### 方式一：ComfyUI Manager（推荐）

1. 打开 ComfyUI → **Manager** → **Install Custom Nodes**
2. 搜索：`ComfyUI-Feixue-UniversalMonitor`
3. 点击 **Install** → **重启** ComfyUI

安装脚本会自动检测操作系统并安装对应依赖：
- **Windows**：`pynvml-amd-windows`（ADLX GPU 监控）、`wmi`（系统信息）
- **Linux**：`amdsmi`（AMD GPU 官方监控库）

### 方式二：手动安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/feixue-ai/ComfyUI-Feixue-UniversalMonitor.git
```

然后重启 ComfyUI，插件会自动启动后端监控服务。

## 使用

安装后，监控栏自动显示在 ComfyUI 界面顶部：

- **6 项核心指标**：GPU 利用率 | 显存(VRAM) | CPU 负载 | 物理内存(RAM) | 虚拟内存(Swap) | GPU 温度
- **2 项辅助指标**：磁盘 I/O | 网络速率（悬浮面板中查看）
- **主题切换**：点击监控栏右侧的 ⚙️ 齿轮按钮打开悬浮面板，在主题区选择颜色主题和风格预设
- **拖拽定位**：悬浮面板中开启拖拽开关后，可拖拽监测栏到任意位置，关闭后自动回到居中
- **实时更新**：默认 2 秒刷新间隔，数据通过 WebSocket 实时推送

## 项目结构

```
ComfyUI-Feixue-UniversalMonitor/
├── __init__.py              # 插件入口 & HTTP API 路由
├── pyproject.toml           # 包元数据
├── install.py               # 跨平台自动依赖安装
├── requirements.txt         # 基础依赖声明
├── core/
│   ├── monitor.py           # 核心硬件采集引擎 (FeixueHardwareInfo)
│   ├── websocket_service.py # WebSocket 实时推送服务
│   └── data_models.py       # 数据模型定义
├── collectors/              # 数据采集器 (CPU, Memory, Predictor)
├── providers/amd/           # AMD GPU 数据源 (ROCm/sysfs)
├── config/                  # 配置管理
├── utils/                   # 平台检测、线程安全、性能优化
├── web/
│   └── extension.js         # 前端 UI (v3.1.0 黑曜石玻璃)
├── docs/
│   └── index.html           # 在线外观演示 (GitHub Pages)
└── tests/                   # 单元测试
```

## 技术细节

| 层级 | 技术栈 |
|------|--------|
| **后端数据采集** | Python (psutil, pynvml-amd-windows, amdsmi, WMI, PyTorch) |
| **前端 UI** | Vanilla JavaScript (零外部依赖，自包含 extension.js) |
| **数据通道** | WebSocket (`feixue.monitor` 事件) + HTTP REST API |
| **兼容性** | ComfyUI (Windows / Linux Ubuntu)，AMD GPU |

### 数据采集策略

```
GPU 数据源优先级:
  Windows: pynvml (ADLX) → PyTorch → PowerShell → WMI
  Linux:   amdsmi → rocm_smi → sysfs

CPU/RAM/Swap: psutil (跨平台统一)
```

所有采集操作均有超时保护（≤8s），异常时自动降级到缓存数据或安全默认值，确保 ComfyUI 主流程不受影响。

## 更新日志

### v3.1.0 — 黑曜石玻璃重构 + 5风格完全隔离 (当前版本)
- 悬浮面板全面重构：半透明毛玻璃 (backdrop-filter) + 多层弥散阴影 + 玻璃边缘高光
- 进度条重构为凹陷轨道 + 渐变流体填充 + 缓慢漂移动画
- Toggle 开关从 iOS 圆滑风格改为工业方形拨动开关
- **5 种风格完全视觉隔离**：胶囊保留 ::before 3D 圆柱效果，其余 4 风格全部隐藏
- 蓝图风格修复：图标/边框/进度条改用主题变量，切换主题色时装饰色跟随变化
- 全局发光变量软化，消除生硬光晕
- 面板装饰元素（图标、分隔线、标签）跟随主题色
- 数据卡片改为微玻璃半透明卡片
- 移除风扇转速监测（AMD Windows 不支持）
- 新增磁盘 I/O 和网络速率监测
- 跨平台（Windows + Linux）所有指标可用

### v3.0.1 — Emerald Capsule
- 完整 UI 重写：药丸/胶囊形设计 + 3D 圆柱横截面立体效果
- 新增 5 色主题系统（翡翠绿/赛博紫/琥珀金/极光蓝/樱花粉）
- 新增拖拽自由定位功能，位置自动记忆
- CSS 芯片图标系统（非 emoji，纯 CSS 绘制）
- 渐变状态条 + 液态光泽动画
- 新增 Swap 虚拟内存监测
- 悬浮面板改为不透明卡片风格
- 移除毛玻璃(glassmorphism)方案，解决 ComfyUI 复杂背景下灰蒙蒙问题
- 跨平台完善：Windows 支持 (pynvml-amd-windows + WMI)，Linux (amdsmi/ROCm/sysfs)
- 数据采集稳定性优化（pynvml 持久化连接、多源融合策略）
- 修复 pynvml FutureWarning 警告

### v2.5.0
- 首次公开发布
- 基础监测功能 (GPU/CPU/RAM)
- WebSocket 实时推送

## 许可证

MIT License

## 作者

[Feixue Team](https://github.com/feixue-ai)