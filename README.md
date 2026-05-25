# 🌨️ ComfyUI-Feixue-UniversalMonitor (飞雪监测器)

<p align="center">
  <strong>世界顶级ComfyUI系统实时监控插件 V2.5</strong><br>
  <em>World-Class Capsule UI · 三套方案可切换 · AMD/NVIDIA双GPU支持</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.5.0-blue.svg" alt="Version">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/ComfyUI-Compatible-brightgreen.svg" alt="ComfyUI">
</p>

---

## ✨ 核心特性

### 🎨 世界顶级胶囊UI系统（V2.5全新）

飞雪监测器V2.5带来**三套工业级UI方案**，运行时可一键切换：

| 方案 | 名称 | 风格 | 性能 |
|------|------|------|------|
| **A** | 极简主义 Minimalist Pro | 扁平化、9999px完美圆角、Inter字体 | ⚡ 零GPU开销 |
| **B** | 科技未来感 Cyberpunk Tech | clip-path切角、多层霓虹glow、扫描线动画 | 🎮 FPS自动降级 |
| **C** | 玻璃态 Glassmorphism Refined | backdrop-filter blur(20px)、大圆角24px | 💎 浏览器兼容性降级 |

### 🔧 核心功能

- **📊 实时监控面板**
  - GPU利用率/显存/温度/功耗（AMD + NVIDIA双支持）
  - CPU使用率/频率/每核心负载
  - 内存使用率/SWAP状态

- **🎯 智能预测系统（PRED）**
  - 工作流执行成功率预估
  - 峰值显存需求预测
  - OOM风险等级评估
  - 智能优化建议生成

- **💫 ComfyUI深度集成**
  - 顶部胶囊菜单栏（7个功能模块）
  - 悬浮详情面板（hover展开）
  - WebSocket实时数据通道
  - HTTP API端点（`/feixue_monitor/snapshot`）

- **🔒 企业级稳定性**
  - AMD GPU三级Fallback策略（amdsmi → rocm_smi_lib → sysfs）
  - ES5语法100%兼容（无ES2020+特性）
  - 线程安全数据采集
  - 异常隔离机制（后端故障不影响ComfyUI主流程）

---

## 🚀 安装方式

### 方式1：ComfyUI Manager推荐（最简单）

1. 打开ComfyUI → 点击 **Manager** 按钮
2. 点击 **Install Custom Nodes**
3. 搜索 `Feixue-UniversalMonitor`
4. 点击 **Install** → 重启ComfyUI

### 方式2：手动安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/feixui/ComfyUI-Feixue-UniversalMonitor.git
```

### 方式3：PyPI安装（开发版）

```bash
pip install ComfyUI-Feixue-UniversalMonitor==2.5.0
```

---

## 📖 使用说明

### 启动插件

启动ComfyUI后，控制台会显示：

```
[飞雪监测器] ✅ 插件加载完成 (V2.5 World-Class Capsule UI)
[飞雪监测器] ✅ 后端监控已启动 (GPU: NVIDIA GeForce RTX 3090)
[飞雪监测器]    - CPU/RAM采集器: 运行中
[飞雪监测器]    - 采集间隔: 1.0s
[飞雪监测器] ✅ HTTP API 路由已注册:
    GET /feixue_monitor/snapshot - 获取监控数据
    GET /feixue_monitor/status   - 获取服务状态
```

### 切换UI方案

在ComfyUI界面顶部，你会看到**三个胶囊按钮**：
- **[A 极简]** → 切换到极简主义风格
- **[B 科技]** → 切换到赛博朋克风格
- **[C 玻璃]** → 切换到玻璃态风格

点击即可实时切换，选择会自动保存到localStorage。

### 调整刷新间隔

在配置文件 `config/config.json` 中修改：

```json
{
  "refresh_interval": 1.0,
  "theme": "dark",
  ...
}
```

---

## 🏗️ 技术架构

```
ComfyUI-Feixue-UniversalMonitor/
├── __init__.py                 # 插件入口 + HTTP API路由
├── pyproject.toml              # 项目元数据 & 依赖
├── LICENSE                     # MIT开源协议
│
├── core/                       # 后端核心
│   ├── monitor.py              # UniversalMonitor主类
│   └── data_models.py          # 数据模型定义
│
├── collectors/                 # 数据采集器
│   ├── cpu_collector.py        # CPU信息采集
│   ├── memory_collector.py     # 内存信息采集
│   └── predictor.py            # PRED智能预测算法
│
├── providers/                  # GPU驱动适配层
│   ├── nvidia/                 # NVIDIA GPU支持
│   └── amd/                    # AMD GPU支持
│       ├── linux_amd.py        # Linux AMD (sysfs优先)
│       └── windows_amd.py      # Windows AMD
│
├── web/                        # 前端代码
│   ├── extension.js            # 主前端文件（5642行，含三套UI）
│   ├── components/
│   │   ├── hover-panel.js      # 悬浮面板组件
│   │   └── top-menu-bar.js     # 顶部菜单栏组件
│   └── styles/                 # CSS样式表
│       ├── variables.css       # CSS变量系统
│       ├── base.css            # 基础样式
│       └── animations.css      # 动画库
│
├── config/                     # 配置管理
│   ├── config.json             # 默认配置
│   └── config_manager.py       # 配置管理器
│
└── utils/                      # 工具库
    ├── platform_detect.py      # 平台检测
    ├── thread_safe.py          # 线程安全工具
    └── performance_optimizations.py  # 性能优化
```

---

## 🔌 API文档

### 获取监控快照

```bash
GET /feixue_monitor/snapshot
```

**响应示例**：
```json
{
  "timestamp": 1706659200.123,
  "status": "ok",
  "data_source": "nvidia-smi",
  "version": "2.5.0",
  "cpu": {
    "utilization": 45.2,
    "cores": 16,
    "freq_mhz": 4200,
    "per_core_usage": [30, 50, 45, ...]
  },
  "ram": {
    "total_gb": 32.0,
    "used_gb": 18.5,
    "percent": 57.8,
    "free_gb": 13.5
  },
  "gpu": {
    "utilization": 78.5,
    "vram_used_gb": 20.3,
    "vram_total_gb": 24.0,
    "vram_percent": 84.6,
    "temperature": 72,
    "device_name": "NVIDIA GeForce RTX 3090"
  },
  "prediction": {
    "success_rate": 85.0,
    "risk_level": "medium",
    "peak_vram_estimate_mb": 22000,
    "confidence": 0.75
  }
}
```

### 获取服务状态

```bash
GET /feixue_monitor/status
```

---

## ⚙️ 系统要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| **Python** | 3.10+ | 3.11+ |
| **操作系统** | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| **GPU** | NVIDIA GTX 1060+ 或 AMD RX 5000系列 | RTX 3060+ / RX 6000系列 |
| **内存** | 8 GB RAM | 16 GB RAM+ |
| **浏览器** | Chrome 90+ / Firefox 88+ | 最新版Chrome/Edge |

### Python依赖

```
psutil>=5.9.0
torch>=2.5.0
orjson>=3.9.0
aiohttp  (ComfyUI自带)
```

---

## 🛠️ 开发指南

### 本地开发环境搭建

```bash
# 克隆仓库
git clone https://github.com/feixui/ComfyUI-Feixue-UniversalMonitor.git
cd ComfyUI-Feixue-UniversalMonitor

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装开发依赖
pip install -e ".[dev]"
```

### 运行测试

```bash
pytest tests/unit/ -v --cov=core --cov=collectors
```

### 代码质量检查

```bash
black .                    # 代码格式化
isort .                   # 导入排序
ruff check .              # Lint检查
```

---

## 📈 版本历史

### V2.5.0 (当前版本) - World-Class Capsule UI 🎨

**重大更新**：
- ✅ 全新三套世界级UI方案（极简/科技/玻璃态）
- ✅ 运行时UI切换机制（A/B/C按钮组）
- ✅ 方案B FPS自动降级监控系统
- ✅ 方案C backdrop-filter兼容性检测
- ✅ 修复93处ES2020语法兼容性问题
- ✅ 完善项目元数据和发布流程

### V2.4 - Cyberpunk UI优化
- 毛玻璃效果菜单栏
- 动画性能优化
- 暗色主题增强

### V2.2-V2.3 - 后端服务集成
- UniversalMonitor后端架构
- HTTP API数据通道
- AMD GPU三级Fallback策略
- PRED智能预测系统

### V2.1 - 初始版本
- 基础监控功能
- GPU/CPU/RAM数据采集
- 前端可视化展示

---

## 🤝 贡献指南

欢迎贡献代码！请遵循以下步骤：

1. Fork本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建Pull Request

**代码规范**：
- 遵循PEP 8 Python编码规范
- 使用Black格式化代码
- 保持ES5语法兼容性（前端代码）
- 为新功能添加测试用例

---

## 🐛 问题反馈

如果您遇到问题或有功能建议：

1. 查看 [Issues](https://github.com/feixui/ComfyUI-Feixue-UniversalMonitor/issues) 是否已有相关问题
2. 如果没有，请创建新Issue并提供：
   - ComfyUI版本
   - 操作系统和Python版本
   - GPU型号和驱动版本
   - 错误日志或截图

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

```
Copyright (c) 2024 Feixue (飞雪)

自由使用、修改、分发和商用，仅需保留版权声明。
```

---

## 🙏 致谢

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - 强大的节点式AI工作流平台
- [ComfyUI Manager](https://github.com/ltdrdata/ComfyUI-Manager) - 插件管理系统
- 所有贡献者和用户的支持

---

<p align="center">
  <strong>⭐ 如果这个项目对您有帮助，请给一个Star！⭐</strong>
  <br><br>
  Made with ❤️ by <a href="https://github.com/feixui">Feixue (飞雪)</a>
</p>
