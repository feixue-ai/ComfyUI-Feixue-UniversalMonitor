---
name: Bug Report
about: 报告一个 Bug 或问题
title: '[Bug] <简短描述>'
labels: 'bug'
assignees: ''
---

<!--
感谢您报告 Bug！请填写以下信息以帮助我们快速定位和解决问题。

在提交之前，请先检查：
1. 是否已有类似的 Issue（使用搜索功能）
2. 问题是否可以通过更新到最新版本解决
3. 问题是否在文档或 FAQ 中有说明

谢谢！
-->

## Bug 描述

清晰简洁地描述这个 Bug 是什么。

**预期行为：**
描述您期望发生的行为

**实际行为：**
描述实际发生了什么

**复现步骤：**
提供详细的步骤来重现这个问题：

1. 前往 '...'
2. 点击 '....'
3. 向下滚动到 '....'
4. 看到错误

## 环境信息

<!-- 请尽可能详细地填写以下信息 -->

### 操作系统
- [ ] Linux (Ubuntu 20.04/22.04/24.04)
- [ ] Windows 10/11
- [ ] macOS (版本: ___)
- [ ] 其他: ___

### Python 环境
- **Python 版本:** （运行 `python --version` 输出）
- **pip 版本:** （运行 `pip --version` 输出）
- **虚拟环境:** (venv/conda/pipenv/其他)

### ComfyUI 信息
- **ComfyUI 版本:** （如果知道的话）
- **安装方式:** (手动安装/ComfyUI Manager/其他)

### 插件信息
- **插件版本:** （运行 `python -c "from ComfyUI_Feixue_UniversalMonitor import __version__; print(__version__)"` 或查看 `pyproject.toml`）
- **安装方式:** (git clone/ComfyUI Manager/手动复制)

### GPU 信息
- **GPU 厂商:** (AMD/NVIDIA/Intel/无)
- **GPU 型号:** （例如: RX 7900 XTX, RTX 4090）
- **驱动版本:** （AMD: ROCm 版本 / NVIDIA: 驱动版本）

### 依赖版本
```
# 请粘贴以下命令的输出:
pip list | findstr -i "psutil torch amdsmi pynvml"
```

## 错误日志 / 截图

<!-- 请粘贴相关的错误输出、日志或截图 -->
<details>
<summary>点击展开错误日志</summary>

```
# 在这里粘贴完整的错误堆栈跟踪
# 可以从 ComfyUI 终端、浏览器控制台或系统日志中获取
# 请确保包含完整的 traceback，不要截断

```

</details>

<!-- 如果有截图，可以在这里添加 -->
<!-- ![截图描述](截图链接) -->

## 额外信息

<!-- 其他可能有助于解决问题的信息 -->
- 您是否尝试过修复这个问题？如果有，请描述：
- 这个问题是否影响了特定的工作流程？
- 是否有临时解决方案？

## 检查清单

<!-- 请确认您已经完成了以下步骤（将 [ ] 改为 [x]） -->
- [ ] 我已搜索现有的 Issues，确保没有重复报告
- [ ] 我已阅读并遵循了 [CONTRIBUTING.md](../CONTRIBUTING.md) 的指南
- [ ] 我提供了可复现的步骤和环境信息
- [ ] 我理解这是一个开源项目，维护者会尽力但无法保证响应时间
