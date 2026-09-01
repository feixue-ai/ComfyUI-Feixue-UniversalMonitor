# Feixue Universal Monitor — 维护者指南

> 本项目正在寻找共同维护者。如果你熟悉 ComfyUI 插件开发、Python ctypes、GPU 驱动/NVML/ROCm，或前端 Lit/原生 JS，欢迎提交 PR 或联系作者。

## 1. 项目定位

**ComfyUI-Feixue-UniversalMonitor**（飞雪监测器）是一个跨平台实时硬件监控插件，设计目标：

- **零额外 pip 依赖**：Windows 上尽量用系统自带 DLL（ADLX/ADL/NVML/PDH/DXGI）；Linux 上优先读 sysfs，再尝试动态库。
- **A 卡友好**：AMD GPU 支持是核心场景，NVIDIA/Intel 为兼容场景。
- **前后端分离**：后端采集 + WebSocket/HTTP 推送，前端 Premium UI 面板。

## 2. 架构总览

```
web/extension.js          # 前端悬浮栏 / 设置面板 / 主题系统
    │
    ▼
core/websocket_service.py # WebSocket 推送、DIAG 钩子、HTTP 降级
core/monitor.py           # 采集调度器：GPU source 优先级 + fallback
core/diagnoser.py         # DIAG 报错诊断引擎
core/health_check.py      # 环境健康检查
core/data_models.py       # 统一数据模型
    │
    ▼
collectors/               # 各类采集器
collectors/gpu_providers/ # GPU Provider（重点维护区）
collectors/cpu_collector.py
collectors/memory_collector.py
```

## 3. GPU Provider 优先级链

### Windows

```
amd_adlx → amd_adl → nvidia → windows_pdh
```

- `amd_adlx_provider.py`：ADLX C++ Bridge DLL（最准确）。
- `amd_adl_provider.py`：atiadlxx.dll 旧接口。
- `nvidia_provider.py`：基于 `pynvml` / `nvidia-ml-py`，并已内置 NVML v2 + nvidia-smi fallback（RTX 50 / Blackwell 兼容）。
- `windows_pdh_provider.py`：Windows PDH 性能计数器 + DXGI 显存补全。

### Linux

```
amd_smi → amd_rocm → amd_sysfs → nvidia_nvml → nvidia → windows_pdh(不可用)
```

- `amd_smi_provider.py`：`libamd_smi.so` ctypes。
- `amd_rocm_provider.py`：`rocm-smi` 命令行。
- `amd_sysfs_provider.py`：`/sys/class/drm/card*/device/` 内核驱动接口。
- `nvidia_nvml_provider.py`：ctypes 原生 NVML，零 pip 依赖，支持 NVML v2。
- `nvidia_provider.py`：pynvml 版本（Linux 上可选）。

## 4. 关键设计决策

- **字段级降级锁死**：`MonitorSnapshot` 各指标一旦成功采集就不允许后续 source 覆盖为更差的值（例如已有显存则不再用 0 覆盖）。见 `core/monitor.py`。
- **DIAG 为事后诊断**：不预判、不轮询，仅在 ComfyUI 真实 `execution_error` 或用户手动触发时分析。
- **浏览器缓存控制**：`__init__.py` 注册了 aiohttp middleware，对 `extension.js` 强制 `no-store`，避免前端更新被缓存。
- **版本号分散**：当前 `pyproject.toml`、`__init__.py`、`web/extension.js`、README 中都有硬编码版本号。发布时需同步 bump。

## 5. 已知问题与待办

### 5.1 已修复 / 本次 Hotfix

- **RTX 50 / Blackwell 显存/温度为 0**：`nvidia_provider.py` 已增加 `nvmlDeviceGetMemoryInfo_v2` 与 `nvmlDeviceGetTemperatureV2` ctypes 调用，并带 `nvidia-smi` fallback。

### 5.2 待完善（DIAG 默认关闭）

DIAG 诊断引擎已随 v3.40.10 合入代码，但 `config.json` 中 `"diag.enabled": false`，默认不向用户暴露。待完善项：

- **DIAG 诊断覆盖率**：`core/diag_error_dict.py` 词库仍需扩充更多 ComfyUI 常见报错（模型加载失败、shape mismatch、LoRA 冲突等）。
- **DIAG 前端展示**：当前前端已能接收 `feixue.diag` 事件并弹窗，但面板整合、历史记录、一键复制报告仍可优化。
- **默认启用开关**：当词库覆盖率达到可接受水平且前端面板稳定后，再考虑将 `diag.enabled` 默认值改为 `true`。
- **macOS 支持**：目前几乎未测试，依赖 `psutil` 和基础采集器。
- **单元测试覆盖 GPU Provider**：现有测试多在 CPU/RAM/诊断模块，GPU Provider 因依赖物理硬件，测试以 mock 为主，可补强。
- **版本号统一管理**：建议后续把前端版本号改为从后端 `/feixue_monitor/status` 动态获取，避免多处硬编码。

## 6. 如何参与维护

1. **修复问题**：从 [GitHub Issues](https://github.com/feixue-ai/ComfyUI-Feixue-UniversalMonitor/issues) 认领。
2. **补充词库**：向 `core/diag_error_dict.py` 添加正则与多语言建议。
3. **测试 GPU Provider**：在 Windows/Linux、AMD/NVIDIA/Intel 环境下跑 `tools/provider_accuracy_test.py`。
4. **完善文档**：更新 README、本文件、代码注释。

## 7. 发布 checklist

- [ ] 修改 `pyproject.toml` 版本号
- [ ] 修改 `__init__.py` 版本号与启动日志
- [ ] 全局替换 `web/extension.js` 中的硬编码版本号
- [ ] 更新 README 版本徽章与 Release Notes
- [ ] 运行 `python -m py_compile` 检查所有 Python 文件
- [ ] 在目标平台（至少一个 Windows + 一个 Linux）手动验证监控栏数据正常
- [ ] 撰写 GitHub Release，说明变更、兼容性、已知问题

## 8. 联系

- GitHub: [feixue-ai/ComfyUI-Feixue-UniversalMonitor](https://github.com/feixue-ai/ComfyUI-Feixue-UniversalMonitor)
- 原维护者：Feixue Team
