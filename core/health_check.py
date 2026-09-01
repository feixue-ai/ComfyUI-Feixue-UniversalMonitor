"""
ComfyUI-Feixue-UniversalMonitor - 环境健康检查器（手动诊断模式 C）

职责：
1. 扫描当前 ComfyUI 环境常见隐患：缺失节点、缺失模型、PyTorch 后端、驱动版本、系统内存。
2. 生成结构化的健康检查报告，按 error/warning/info 分组，并给出修复建议。

设计约束：
- 扫描在用户点击时执行，不在后台持续扫描。
- 单次扫描目标耗时 < 3 秒，所有外部命令/API 均带超时保护。
- 模型扫描仅检查文件存在性，不计算哈希。
- 节点扫描使用前缀匹配减少误报。

返回格式：
- 与 DiagReport 对齐的 HealthReport 数据类，category="health_check"。
- 包含 findings 列表，每个 finding 含 severity、category、title、explanation、suggestion。

版本: 1.0.0
作者: Feixue
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import platform as _platform
import re
import subprocess
import time
import urllib.request
from dataclasses import field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import folder_paths
except Exception:  # pragma: no cover - 在 ComfyUI 外运行测试时可能不存在
    folder_paths = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ============================================================================
# 国际化支持
# ============================================================================

_DEFAULT_LANGUAGE = "zh"
_SUPPORTED_LANGUAGES = {"zh", "en"}

_I18N: Dict[str, Dict[str, str]] = {
    # node checks
    "node_check_unavailable_title": {
        "zh": "无法获取已安装节点列表",
        "en": "Unable to retrieve installed node list",
    },
    "node_check_unavailable_explanation": {
        "zh": "无法读取 NODE_CLASS_MAPPINGS、/object_info 或 custom_nodes 目录。",
        "en": "Unable to read NODE_CLASS_MAPPINGS, /object_info, or the custom_nodes directory.",
    },
    "node_check_unavailable_suggestion": {
        "zh": "请确认在 ComfyUI 进程中运行健康检查，或检查插件权限。",
        "en": "Please make sure the health check is running inside the ComfyUI process, or check plugin permissions.",
    },
    "node_no_workflow_title": {
        "zh": "未提供工作流或队列为空",
        "en": "No workflow provided or queue is empty",
    },
    "node_no_workflow_explanation": {
        "zh": "未检测到工作流节点类型，无法判断节点缺失。",
        "en": "No workflow node types detected; unable to determine missing nodes.",
    },
    "node_no_workflow_suggestion": {
        "zh": "在画布中加载工作流后重新运行健康检查，或调用 API 时传入 workflow。",
        "en": "Load a workflow on the canvas and rerun the health check, or pass workflow when calling the API.",
    },
    "node_missing_title": {
        "zh": "缺少 {count} 个工作流节点类型",
        "en": "Missing {count} workflow node type(s)",
    },
    "node_missing_explanation": {
        "zh": "当前工作流使用了以下未安装的节点类型：{missing}。ComfyUI 界面提示的“节点包名”与这里的“节点类型名”可能不同，但两者指向同一缺失插件。",
        "en": "The current workflow uses the following uninstalled node types: {missing}. The 'node package name' shown in the ComfyUI UI may differ from the 'node type name' here, but both point to the same missing plugin.",
    },
    "node_missing_suggestion": {
        "zh": "请在 ComfyUI Manager 中搜索并安装对应节点包，然后重启 ComfyUI。提示：ComfyUI 显示的是节点包名（如 ComfyUI_LayerStyle_Advance），飞雪显示的是具体节点类型名（如 LayerMask:LoadSegmentAnythingModels），两者对应同一问题。",
        "en": "Please search for and install the corresponding node package in ComfyUI Manager, then restart ComfyUI. Note: ComfyUI shows the node package name (e.g. ComfyUI_LayerStyle_Advance), while Feixue shows the specific node type name (e.g. LayerMask:LoadSegmentAnythingModels); both refer to the same issue.",
    },
    "node_missing_individual_title": {
        "zh": "缺少自定义节点：{node}",
        "en": "Missing custom node: {node}",
    },
    "node_missing_individual_explanation": {
        "zh": "当前工作流使用了节点 {node}，但本地未安装该节点。",
        "en": "The current workflow uses node {node}, but it is not installed locally.",
    },
    "node_missing_individual_suggestion": {
        "zh": "请在 ComfyUI Manager 中搜索并安装 {node} 节点包，或从 GitHub 下载安装。如 ComfyUI 提示的节点包名与此处节点类型名不同，以后端/ComfyUI 界面显示为准。",
        "en": "Please search for and install the {node} node package in ComfyUI Manager, or download and install it from GitHub. If the package name shown in ComfyUI differs from the node type name here, follow the ComfyUI/backend display.",
    },
    "node_missing_unrecognized_title": {
        "zh": "缺少 {count} 个无法识别的自定义节点",
        "en": "Missing {count} unrecognized custom node(s)",
    },
    "node_missing_unrecognized_explanation": {
        "zh": "工作流中包含未安装的自定义节点（部分为 UUID 或无法识别的长串），例如：{samples}。",
        "en": "The workflow contains uninstalled custom nodes (some are UUIDs or unrecognizable long strings), e.g.: {samples}.",
    },
    "node_missing_unrecognized_suggestion": {
        "zh": "请在 ComfyUI 界面中检查“放弃节点包”提示，并在 ComfyUI Manager 中安装对应节点包，然后重启 ComfyUI。",
        "en": "Please check the 'missing custom nodes' prompt in the ComfyUI interface, install the corresponding node packages in ComfyUI Manager, and restart ComfyUI.",
    },
    "node_ok_title": {
        "zh": "工作流节点检查通过",
        "en": "Workflow node check passed",
    },
    "node_ok_explanation": {
        "zh": "检测到 {count} 个工作流节点类型，均已安装或匹配前缀。",
        "en": "Detected {count} workflow node type(s), all installed or prefix-matched.",
    },
    "node_ok_suggestion": {
        "zh": "无需操作。",
        "en": "No action needed.",
    },
    # model checks
    "models_dir_missing_title": {
        "zh": "models 目录不存在",
        "en": "models directory does not exist",
    },
    "models_dir_missing_explanation": {
        "zh": "未找到 ComfyUI 模型目录：{path}",
        "en": "ComfyUI models directory not found: {path}",
    },
    "models_dir_missing_suggestion": {
        "zh": "请确认 ComfyUI 安装路径正确，或手动创建 models 目录。",
        "en": "Please verify the ComfyUI installation path or create the models directory manually.",
    },
    "model_missing_title": {
        "zh": "未找到任何模型文件",
        "en": "No model files found",
    },
    "model_missing_explanation": {
        "zh": "models 下常见子目录均为空，无法运行大多数工作流。",
        "en": "Common subdirectories under models are empty; most workflows cannot run.",
    },
    "model_missing_suggestion": {
        "zh": "请先下载 Checkpoint、VAE、LoRA、ControlNet 等模型并放入对应子目录。",
        "en": "Please download Checkpoint, VAE, LoRA, ControlNet, etc. models and place them in the corresponding subdirectories.",
    },
    "model_present_title": {
        "zh": "已扫描到 {count} 个模型文件",
        "en": "Scanned {count} model file(s)",
    },
    "model_present_explanation": {
        "zh": "扫描了 {count} 个常见模型子目录。",
        "en": "Scanned {count} common model subdirectories.",
    },
    "model_present_suggestion": {
        "zh": "如需运行特定工作流，请确保对应子目录已放置所需模型。",
        "en": "If a specific workflow is required, make sure the needed models are placed in the corresponding subdirectories.",
    },
    "model_missing_specific_title": {
        "zh": "缺少模型文件：{name}",
        "en": "Missing model file: {name}",
    },
    "model_missing_specific_explanation": {
        "zh": "工作流引用了模型 {name}，但在 models 目录中未找到。",
        "en": "The workflow references model {name}, but it was not found in the models directory.",
    },
    "model_missing_specific_suggestion": {
        "zh": "请下载对应模型文件并放入 ComfyUI/models/{category} 目录，然后检查模型是否正确。",
        "en": "Please download the corresponding model file and place it in ComfyUI/models/{category}, then verify the model.",
    },
    "model_missing_specific_unknown_suggestion": {
        "zh": "请下载对应模型文件并放入 ComfyUI/models 下对应子目录，然后检查模型是否正确。",
        "en": "Please download the corresponding model file and place it in the appropriate ComfyUI/models subdirectory, then verify the model.",
    },
    "model_missing_aggregate_title": {
        "zh": "缺少 {count} 个工作流引用模型",
        "en": "Missing {count} workflow-referenced model(s)",
    },
    "model_missing_aggregate_explanation": {
        "zh": "当前工作流引用了以下未找到的模型文件：{names}。",
        "en": "The current workflow references the following model files that were not found: {names}.",
    },
    "model_missing_aggregate_suggestion": {
        "zh": "请下载对应模型文件并放入 ComfyUI/models 下对应子目录。ComfyUI 报错通常只提示其中 1 个模型；此处列出工作流中所有缺失模型供一次性补齐。",
        "en": "Please download the corresponding model files and place them in the appropriate ComfyUI/models subdirectories. ComfyUI usually reports only one missing model; all missing models in the workflow are listed here for batch fixing.",
    },
    "model_dir_empty_title": {
        "zh": "部分模型目录为空",
        "en": "Some model directories are empty",
    },
    "model_dir_empty_explanation": {
        "zh": "以下目录未找到任何模型文件：{dirs}。",
        "en": "No model files found in the following directories: {dirs}.",
    },
    "model_dir_empty_suggestion": {
        "zh": "如果工作流需要这些类型的模型，请下载并放入对应目录。",
        "en": "If the workflow needs these model types, please download and place them in the corresponding directories.",
    },
    # torch backend checks
    "torch_missing_title": {
        "zh": "未安装 PyTorch",
        "en": "PyTorch not installed",
    },
    "torch_missing_explanation": {
        "zh": "无法导入 torch：{error}",
        "en": "Unable to import torch: {error}",
    },
    "torch_missing_suggestion": {
        "zh": "请安装与 ComfyUI 兼容的 PyTorch 版本。",
        "en": "Please install a PyTorch version compatible with ComfyUI.",
    },
    "torch_rocm_ok_title": {
        "zh": "PyTorch ROCm/HIP 后端已启用（HIP {ver}）",
        "en": "PyTorch ROCm/HIP backend enabled (HIP {ver})",
    },
    "torch_rocm_ok_explanation": {
        "zh": "检测到 AMD GPU，PyTorch 已编译 ROCm 后端。",
        "en": "AMD GPU detected; PyTorch is compiled with the ROCm backend.",
    },
    "torch_rocm_ok_suggestion": {
        "zh": "无需操作。如遇到内核编译错误，请检查 ROCm 版本与显卡架构是否匹配。",
        "en": "No action needed. If kernel compilation errors occur, check whether the ROCm version matches your GPU architecture.",
    },
    "torch_cuda_ok_title": {
        "zh": "PyTorch CUDA 后端已启用（CUDA {ver}）",
        "en": "PyTorch CUDA backend enabled (CUDA {ver})",
    },
    "torch_cuda_ok_explanation": {
        "zh": "检测到 NVIDIA GPU，PyTorch 已编译 CUDA 后端。",
        "en": "NVIDIA GPU detected; PyTorch is compiled with the CUDA backend.",
    },
    "torch_cuda_ok_suggestion": {
        "zh": "无需操作。",
        "en": "No action needed.",
    },
    "torch_backend_unknown_title": {
        "zh": "检测到 GPU，但 PyTorch 后端信息异常",
        "en": "GPU detected, but PyTorch backend information is abnormal",
    },
    "torch_backend_unknown_explanation": {
        "zh": "torch.cuda.is_available() 为 True，但 cuda/hip 版本均不可用。",
        "en": "torch.cuda.is_available() is True, but neither cuda nor hip version is available.",
    },
    "torch_backend_unknown_suggestion": {
        "zh": "请检查 PyTorch 安装是否完整。",
        "en": "Please check whether the PyTorch installation is complete.",
    },
    "torch_mps_ok_title": {
        "zh": "PyTorch MPS 后端已启用",
        "en": "PyTorch MPS backend enabled",
    },
    "torch_mps_ok_explanation": {
        "zh": "检测到 Apple Silicon，MPS 后端可用。",
        "en": "Apple Silicon detected; MPS backend is available.",
    },
    "torch_mps_ok_suggestion": {
        "zh": "无需操作。注意 MPS 在部分算子上可能存在兼容性问题。",
        "en": "No action needed. Note that MPS may have compatibility issues with some operators.",
    },
    "torch_cuda_mismatch_title": {
        "zh": "PyTorch 为 CUDA 版本，但未检测到可用 GPU",
        "en": "PyTorch is CUDA version, but no usable GPU detected",
    },
    "torch_cuda_mismatch_explanation": {
        "zh": "torch.version.cuda={ver}，但 torch.cuda.is_available() 为 False。",
        "en": "torch.version.cuda={ver}, but torch.cuda.is_available() is False.",
    },
    "torch_cuda_mismatch_suggestion": {
        "zh": "请检查 NVIDIA 驱动是否安装、CUDA 运行时是否匹配，或更换为 CPU 版 PyTorch。",
        "en": "Please check whether the NVIDIA driver is installed and whether the CUDA runtime matches, or switch to the CPU version of PyTorch.",
    },
    "torch_rocm_mismatch_title": {
        "zh": "PyTorch 为 ROCm 版本，但未检测到可用 GPU",
        "en": "PyTorch is ROCm version, but no usable GPU detected",
    },
    "torch_rocm_mismatch_explanation": {
        "zh": "torch.version.hip={ver}，但 torch.cuda.is_available() 为 False。",
        "en": "torch.version.hip={ver}, but torch.cuda.is_available() is False.",
    },
    "torch_rocm_mismatch_suggestion": {
        "zh": "请检查 AMD 驱动、ROCm 及 /dev/kfd 权限。",
        "en": "Please check the AMD driver, ROCm, and /dev/kfd permissions.",
    },
    "torch_cpu_title": {
        "zh": "当前使用 CPU 版 PyTorch",
        "en": "Currently using CPU version of PyTorch",
    },
    "torch_cpu_explanation": {
        "zh": "未检测到可用的 GPU 后端，将以 CPU 模式运行。",
        "en": "No usable GPU backend detected; will run in CPU mode.",
    },
    "torch_cpu_suggestion": {
        "zh": "如需 GPU 加速，请安装对应 CUDA/ROCm/MPS 版本的 PyTorch。",
        "en": "For GPU acceleration, install the corresponding CUDA/ROCm/MPS version of PyTorch.",
    },
    # driver checks
    "driver_nvidia_title": {
        "zh": "NVIDIA 驱动版本：{ver}",
        "en": "NVIDIA driver version: {ver}",
    },
    "driver_nvidia_explanation": {
        "zh": "通过 nvidia-smi 读取到驱动版本 {ver}。",
        "en": "Driver version {ver} read via nvidia-smi.",
    },
    "driver_nvidia_suggestion_old": {
        "zh": "NVIDIA 驱动版本较旧，建议升级到最新稳定版。",
        "en": "NVIDIA driver version is old; consider upgrading to the latest stable version.",
    },
    "driver_nvidia_suggestion_ok": {
        "zh": "无需操作。",
        "en": "No action needed.",
    },
    "driver_amd_title": {
        "zh": "ROCm 版本：{ver}",
        "en": "ROCm version: {ver}",
    },
    "driver_amd_explanation": {
        "zh": "通过 rocminfo 读取到 ROCm 版本 {ver}。",
        "en": "ROCm version {ver} read via rocminfo.",
    },
    "driver_amd_suggestion": {
        "zh": "如需更新驱动，请访问 AMD 官网下载对应 ROCm 版本。",
        "en": "To update the driver, visit the AMD website to download the corresponding ROCm version.",
    },
    "driver_unknown_linux_title": {
        "zh": "未检测到 GPU 驱动工具",
        "en": "No GPU driver tool detected",
    },
    "driver_unknown_linux_explanation": {
        "zh": "当前系统未找到 nvidia-smi 或 rocminfo。",
        "en": "nvidia-smi or rocminfo was not found on this system.",
    },
    "driver_unknown_linux_suggestion": {
        "zh": "如使用 GPU，请安装对应驱动工具；如仅使用 CPU，可忽略此项。",
        "en": "If you use a GPU, install the corresponding driver tool; if using CPU only, you can ignore this.",
    },
    "driver_windows_title": {
        "zh": "显卡驱动版本：{ver}",
        "en": "GPU driver version: {ver}",
    },
    "driver_windows_explanation": {
        "zh": "通过 Windows 注册表读取到驱动版本。",
        "en": "Driver version read from the Windows registry.",
    },
    "driver_windows_suggestion": {
        "zh": "无需操作。",
        "en": "No action needed.",
    },
    "driver_unknown_windows_title": {
        "zh": "未检测到 GPU 驱动信息",
        "en": "No GPU driver information detected",
    },
    "driver_unknown_windows_explanation": {
        "zh": "nvidia-smi 与注册表均未返回驱动版本。",
        "en": "Neither nvidia-smi nor the registry returned a driver version.",
    },
    "driver_unknown_windows_suggestion": {
        "zh": "请检查显卡驱动是否正确安装。",
        "en": "Please check whether the GPU driver is installed correctly.",
    },
    "driver_unsupported_platform_title": {
        "zh": "暂不支持此平台的驱动检测",
        "en": "Driver detection not supported on this platform",
    },
    "driver_unsupported_platform_explanation": {
        "zh": "当前平台：{system}。",
        "en": "Current platform: {system}.",
    },
    "driver_unsupported_platform_suggestion": {
        "zh": "请手动检查显卡驱动版本。",
        "en": "Please check the GPU driver version manually.",
    },
    # memory checks
    "memory_unknown_title": {
        "zh": "无法读取系统内存",
        "en": "Unable to read system memory",
    },
    "memory_unknown_explanation": {
        "zh": "psutil 与 /proc/meminfo 均不可用。",
        "en": "Both psutil and /proc/meminfo are unavailable.",
    },
    "memory_unknown_suggestion": {
        "zh": "请检查是否安装了 psutil，或手动确认系统内存容量。",
        "en": "Please check whether psutil is installed, or confirm the system memory capacity manually.",
    },
    "memory_low_title": {
        "zh": "系统内存不足：{total:.1f} GB",
        "en": "Insufficient system memory: {total:.1f} GB",
    },
    "memory_low_explanation": {
        "zh": "ComfyUI 推荐至少 {min} GB 内存，当前可能不足以运行大型模型。",
        "en": "ComfyUI recommends at least {min} GB of memory; the current amount may be insufficient for large models.",
    },
    "memory_low_suggestion": {
        "zh": "请关闭其他大型程序、增加物理内存，或配置足够的 Swap/虚拟内存。",
        "en": "Please close other large programs, increase physical memory, or configure sufficient Swap/virtual memory.",
    },
    "memory_ok_title": {
        "zh": "系统内存充足：{total:.1f} GB",
        "en": "Sufficient system memory: {total:.1f} GB",
    },
    "memory_ok_explanation": {
        "zh": "内存容量达到 {min} GB 建议值。",
        "en": "Memory capacity meets the recommended {min} GB.",
    },
    "memory_ok_suggestion": {
        "zh": "无需操作。",
        "en": "No action needed.",
    },
    # aggregate report
    "health_error_title": {
        "zh": "环境健康检查：发现错误",
        "en": "Environment Health Check: Errors Found",
    },
    "health_warning_title": {
        "zh": "环境健康检查：发现警告",
        "en": "Environment Health Check: Warnings Found",
    },
    "health_ok_title": {
        "zh": "环境健康检查：正常",
        "en": "Environment Health Check: Normal",
    },
    "health_suggestion_error": {
        "zh": "请优先处理错误项：安装缺失的自定义节点或模型文件。",
        "en": "Please prioritize the errors: install missing custom nodes or model files.",
    },
    "health_suggestion_warning": {
        "zh": "请关注警告项：内存、空模型目录或 PyTorch 后端不匹配可能影响工作流运行。",
        "en": "Please review the warnings: memory, empty model directories, or PyTorch backend mismatches may affect workflow execution.",
    },
    "health_suggestion_ok": {
        "zh": "当前环境无明显隐患，可正常运行工作流。",
        "en": "No obvious risks detected in the current environment; workflows should run normally.",
    },
    "health_explanation": {
        "zh": "共完成 {count} 项检查，耗时 {elapsed:.2f} 秒。注意：健康检查是飞雪监测器主动扫描环境隐患的结果，不是 ComfyUI 本次报错的逐条翻译；ComfyUI 真实报错请查看上方的自动诊断或“最近报错”。",
        "en": "Completed {count} check(s) in {elapsed:.2f} seconds. Note: Health check is an active environment scan by Feixue Monitor, not a one-to-one translation of ComfyUI errors. For actual ComfyUI errors, check the auto-diagnosis above or \"Last Error\".",
    },
}


def _t(key: str, language: Optional[str] = None, **kwargs: Any) -> str:
    """根据 language 获取翻译模板并格式化，不支持时回退到默认语言。"""
    lang = language if language in _SUPPORTED_LANGUAGES else _DEFAULT_LANGUAGE
    template = _I18N.get(key, {}).get(lang, key)
    try:
        return template.format(**kwargs)
    except Exception:
        return template


# ============================================================================
# 常量定义
# ============================================================================

MODEL_SUBDIRS = [
    "checkpoints",
    "clip",
    "clip_vision",
    "controlnet",
    "diffusers",
    "embeddings",
    "ipadapter",
    "loras",
    "unet",
    "vae",
    "vae_approx",
]

# 将 health_check 内部模型分类映射到 ComfyUI folder_paths 中的注册名，
# 从而正确读取 extra_model_paths.yaml 等配置指定的额外模型路径。
_COMFY_FOLDER_MAP: Dict[str, str] = {
    "checkpoints": "checkpoints",
    "clip": "text_encoders",
    "clip_vision": "clip_vision",
    "controlnet": "controlnet",
    "diffusers": "diffusers",
    "embeddings": "embeddings",
    "loras": "loras",
    "unet": "diffusion_models",
    "vae": "vae",
    "vae_approx": "vae_approx",
    "ipadapter": "ipadapter",
}

MIN_MEMORY_GB = 16.0
NVIDIA_DRIVER_OLD = 470

# 节点类型前缀匹配时忽略的过短前缀（过短会导致大量误报为“已安装”）
_MIN_PREFIX_LEN = 5

# 模型递归搜索最大深度，避免在极大目录树中耗时过长
_MAX_MODEL_SEARCH_DEPTH = 5

# 用于识别 UUID 格式的缺失节点类型
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# 工作流节点类型提取时，会被误当成节点类型的常见 widget 值/标题/文件相关字符串。
# 仅做精确匹配，避免误杀真正的节点类型（如 ImageScale 不含独立的 image 单词）。
_NODE_TYPE_DENYLIST: Set[str] = {
    # 文件/媒体/IO
    "image", "images", "video", "audio", "input", "output", "mask", "maskt",
    # 采样/缩放/算法
    "lanczos", "nearest", "bilinear", "bicubic", "area", "nearest-exact",
    "nearest_neighbor", "bilinear_antialias",
    # 语义占位/参数名
    "subject", "prompt", "positive", "negative", "seed", "steps", "cfg",
    "sampler", "scheduler", "denoise", "strength", "width", "height",
    "batch_size", "model", "models", "checkpoint", "ckpt",
    "normal", "randomize", "fixed", "increment", "decrement",
    "latent", "pixel",
    # 执行设备/精度
    "cuda", "cpu", "mps", "rocm", "directml", "openvino", "npu",
    "fp16", "fp32", "bf16", "float16", "float32", "bfloat16", "int8", "int4",
    # 通用值
    "true", "false", "none", "null", "empty", "text", "string", "number",
    "int", "float", "boolean", "json",
}

# 输入/输出类节点：它们的 widgets_values/inputs 中通常包含用户文件路径，不应被提取为节点类型或模型。
_INPUT_OUTPUT_NODE_TYPES: Set[str] = {
    "loadimage", "loadimagecapture", "loadvideocapture", "loadaudio",
    "saveimage", "previewimage", "saveaudio", "loadvideo", "savevideo",
    "vhs_loadvideo", "vhs_savevideo", "loadimagesfromdirectory",
    "imageload", "videoload", "audioload", "saveimageextended",
    "loadimagefrompath", "loadimagefromurl", "loadimagefrombase64",
}

# 工作流中常见的占位节点类型，其实际类型应从 properties 恢复，这些占位本身不应作为节点类型。
_PLACEHOLDER_NODE_TYPES: Set[str] = {
    "nodenotfound", "unknownnode", "missingnodetype", "missingnode",
    "nodemissing", "missing_node_type", "missingnodetypeproxy", "proxy",
    "missing",
}

# ComfyUI 内置节点白名单：即使读取不到 NODE_CLASS_MAPPINGS，也不应被报告为缺失。
_CORE_NODE_WHITELIST: Set[str] = {
    "note", "reroute", "nodere reroute", "primitivenode",
    "loadimage", "loadimagemask", "loadvideo", "loadaudio",
    "saveimage", "previewimage", "saveaudio", "savevideo",
    "loadimagesfromdirectory", "vhs_loadvideo", "vhs_savevideo",
}


def _is_placeholder_node_type(value: Optional[str]) -> bool:
    if not isinstance(value, str):
        return False
    return value.replace(" ", "").lower() in _PLACEHOLDER_NODE_TYPES


def _clean_missing_node_title(value: str) -> str:
    """从占位节点标题中清理 'Missing:' 等前缀，尝试恢复原始节点类型名。"""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    # 移除常见前缀：Missing: / Missing / NotFound: 等
    for prefix in ("Missing:", "missing:", "MISSING:", "Missing ", "NotFound:", "Unknown:"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    return value


def _is_node_type_candidate(value: str) -> bool:
    """判断字符串是否可能是一个真实的 ComfyUI 节点类型名。

    节点类型通常由字母、数字、下划线、连字符、冒号组成，不含空格、路径分隔符或文件扩展名点号。
    """
    if not isinstance(value, str) or not value:
        return False
    # 长度限制
    if len(value) < 3 or len(value) > 64:
        return False
    # 至少包含一个字母
    if not any(ch.isalpha() for ch in value):
        return False
    # 排除路径/文件特征
    if any(ch in value for ch in "/\\."):
        return False
    # 排除带空格的自定义标题
    if " " in value:
        return False
    # 排除常见 widget 值/设备名/参数名（精确匹配，忽略大小写）
    if value.lower() in _NODE_TYPE_DENYLIST:
        return False
    return True


# ============================================================================
# 数据模型
# ============================================================================

@dataclasses.dataclass
class HealthFinding:
    """单项健康检查发现。"""

    severity: str
    category: str
    title: str
    explanation: str
    suggestion: str
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "explanation": self.explanation,
            "suggestion": self.suggestion,
            "raw_data": self.raw_data,
        }


@dataclasses.dataclass
class HealthReport:
    """健康检查报告，与 DiagReport 结构保持兼容。"""

    error_node: Optional[Dict[str, Any]] = None
    category: str = "health_check"
    category_label: str = "环境健康检查"
    status: str = "ok"
    severity: str = "info"
    scope: ssr = "full"
    tcope: str = "full"
    title: str = ""
    explanation: str = ""
    suggestions: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    raw_error: str = ""
    node_info: Dict[str, Any] = field(default_factory=dict)
    system_snapshot: Dict[str, Any] = field(default_factory=dict)
    system_context: Dict[str, Any] = field(default_factory=dict)
    language: str = "zh"
    timestamp: float = 0.0
    elapsed_seconds: float = 0.0
    matched: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# ============================================================================
# 路径工具
# ============================================================================

def _comfyui_root() -> Path:
    """根据插件安装位置推导 ComfyUI 根目录。"""
    return Path(__file__).resolve().parent.parent.parent.parent


def _custom_nodes_dir() -> Path:
    return _comfyui_root() / "custom_nodes"


def _models_dir() -> Path:
    return _comfyui_root() / "models"


def _get_model_search_dirs(category: Optional[str] = None) -> List[Path]:
    """获取指定模型分类的真实搜索路径。

    优先使用 ComfyUI folder_paths 中注册的路径（含 extra_model_paths.yaml 等配置），
    无法获取时回退到默认的 ComfyUI/models/<category>。
    """
    dirs: List[Path] = []

    if folder_paths is not None:
        try:
            comfy_name = _COMFY_FOLDER_MAP.get(category, category) if category else None
            if comfy_name and comfy_name in folder_paths.folder_names_and_paths:
                for p in folder_paths.get_folder_paths(comfy_name):
                    dirs.append(Path(p))
            # 如果 folder_paths 中没有该分类，回退到默认路径
            if not dirs and category:
                dirs.append(_models_dir() / category)
            return dirs
        except Exception as e:
            logger.debug("folder_paths 获取模型路径失败: %s", e)

    # 无 folder_paths 时 fallback
    if category:
        dirs.append(_models_dir() / category)
    return dirs


# ============================================================================
# 通用工具
# ============================================================================

def _run(cmd: List[str], timeout: float = 1.5) -> str:
    """运行外部命令并返回 stdout，超时保护。"""
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result.stdout or ""


def _count_files(directory: Path, cap: int = 5000) -> int:
    """统计目录下文件数量（含一级子目录），避免无限递归导致超时。"""
    if not directory.is_dir():
        return 0
    count = 0
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    count += 1
                elif entry.is_dir(follow_symlinks=False):
                    try:
                        with os.scandir(entry.path) as sub_it:
                            for sub in sub_it:
                                if sub.is_file(follow_symlinks=False):
                                    count += 1
                                if count >= cap:
                                    return cap
                    except OSError:
                        pass
                if count >= cap:
                    return cap
    except OSError:
        pass
    return count


def _server_address() -> Tuple[str, int]:
    """获取当前 ComfyUI HTTP 服务地址，用于调用 /object_info。"""
    try:
        from server import PromptServer

        server = PromptServer.instance
        address = getattr(server, "address", "127.0.0.1")
        port = getattr(server, "port", 8188)
        if address in ("0.0.0.0", "::"):
            address = "127.0.0.1"
        return address, int(port)
    except Exception:
        return "127.0.0.1", 8188


def _object_info_url() -> str:
    host, port = _server_address()
    return f"http://{host}:{port}/object_info"


# ============================================================================
# 节点缺失检查
# ============================================================================

def _installed_custom_node_packages() -> Set[str]:
    """扫描 custom_nodes 目录，返回已安装的自定义节点包名。"""
    packages: Set[str] = set()
    custom_nodes = _custom_nodes_dir()
    if not custom_nodes.is_dir():
        return packages
    try:
        for entry in os.scandir(custom_nodes):
            if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                packages.add(entry.name)
            elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".py"):
                packages.add(Path(entry.name).stem)
    except OSError:
        pass
    return packages


def _installed_node_class_types() -> Set[str]:
    """获取已注册的节点类类型（优先内存中的 NODE_CLASS_MAPPINGS）。"""
    try:
        import nodes

        mappings = getattr(nodes, "NODE_CLASS_MAPPINGS", {})
        return set(mappings.keys())
    except Exception as e:
        logger.debug(f"[健康检查] 读取 NODE_CLASS_MAPPINGS 失败: {e}")
    return set()


def _object_info_node_types(timeout: float = 1.5) -> Set[str]:
    """通过 ComfyUI /object_info API 获取已注册节点类型（降级方案）。"""
    try:
        req = urllib.request.Request(
            _object_info_url(),
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return set(data.keys())
    except Exception as e:
        logger.debug(f"[健康检查] /object_info 请求失败: {e}")
    return set()


def _is_input_output_node_type(node_type: Optional[str]) -> bool:
    """判断节点类型是否为输入/输出类节点（其 widget 值可能是文件路径而非节点类型）。"""
    if not isinstance(node_type, str):
        return False
    return node_type.replace(" ", "").lower() in _INPUT_OUTPUT_NODE_TYPES


def _extract_workflow_node_types(
    workflow: Optional[Dict[str, Any]],
    executed_node_ids: Optional[Set[str]] = None,
) -> Set[str]:
    """从工作流 JSON 中提取节点类型集合。

    支持：
    - 前端工作流格式：{ "nodes": [{ "type": "...", "properties": { ... } }] }
    - ComfyUI prompt 格式：{ "node_id": { "class_type": "...", "_meta": { "title": "..." } } }

    对“放弃节点包”场景做兼容：
    - 如果节点的 type 被替换为占位值，尝试从 properties 中恢复原始类型名。
    - 如果 prompt 中缺少 class_type，从 _meta.title 提取可能的类型名（仅限通过候选校验）。

    Args:
        executed_node_ids: 若提供，仅返回实际执行路径上的节点类型，避免未连接节点造成误报。
    """
    types: Set[str] = set()
    if not workflow or not isinstance(workflow, dict):
        return types

    # 明确区分“未提供执行路径”与“执行路径为空”。
    # None -> 不过滤（全图扫描）；set() -> 过滤掉所有节点（返回空集合）。
    filter_enabled = executed_node_ids is not None
    executed_node_ids = executed_node_ids or set()

    def _add_type(t: Any) -> None:
        if isinstance(t, str):
            candidate = t.strip()
            # 规范化节点类型名：移除冒号后的空格，统一格式
            candidate = re.sub(r":\s+", ":", candidate)
            # 排除 reroute 类占位
            if candidate and not candidate.startswith("Reroute") and candidate not in ("NodeReroute", "Reroute"):
                if _is_node_type_candidate(candidate):
                    types.add(candidate)

    nodes = workflow.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nid = str(node.get("id", ""))
            if filter_enabled and nid not in executed_node_ids:
                continue
            # 主 type 字段（占位节点本身不加入，从 properties 恢复真实类型）
            node_type = node.get("type")
            if isinstance(node_type, str) and not _is_placeholder_node_type(node_type):
                _add_type(node_type)
            # properties 中可能保留原始类型名
            properties = node.get("properties")
            if isinstance(properties, dict):
                for key in ("type", "nodetype", "orig_type", "original_type", "class_type", "originalNodeType", "comfyClass"):
                    _add_type(properties.get(key))
            # 占位节点：从 title 中恢复原始类型名（标题常为 "Missing: NodeType"）
            if _is_placeholder_node_type(node_type):
                title = node.get("title") or (node.get("_meta") or {}).get("title")
                if isinstance(title, str) and title.strip():
                    _add_type(_clean_missing_node_title(title))
            # widgets_values 中偶尔包含节点类型占位，但仅对占位节点做回退提取，
            # 正常节点的 widgets_values 是参数值（采样器、调度器、提示词等）。
            if _is_placeholder_node_type(node_type):
                widgets = node.get("widgets_values")
                if isinstance(widgets, list):
                    for w in widgets:
                        # widgets_values 通常是字符串参数，只有看起来像真实节点类型名才采纳
                        if isinstance(w, str) and _is_node_type_candidate(w.strip()):
                            _add_type(w)

    prompt = workflow.get("prompt") or workflow
    if isinstance(prompt, dict):
        for nid_raw, value in prompt.items():
            if not isinstance(value, dict):
                continue
            nid = str(nid_raw)
            if filter_enabled and nid not in executed_node_ids:
                continue
            ct = value.get("class_type")
            if isinstance(ct, str) and ct:
                _add_type(ct)
            # 缺失节点时 class_type 可能为空，尝试从 _meta.title 推断
            # _meta.title 是用户自定义标题，仅当通过严格节点类型校验时才采纳
            meta = value.get("_meta")
            if isinstance(meta, dict) and not (isinstance(ct, str) and ct):
                title = meta.get("title")
                _add_type(_clean_missing_node_title(title))

    return types


def _get_executed_node_types(
    workflow: Optional[Dict[str, Any]],
) -> Tuple[Optional[Set[str]], Optional[Set[str]]]:
    """从工作流中提取实际执行路径上的节点。

    返回 (executed_node_ids, executed_node_types)。
    仅当存在可识别的输出节点（无输出或输出未连接）时才进行反向 BFS；
    如果无法解析执行路径，返回 (None, None)，调用方应回退到全图扫描；
    如果成功解析但路径为空，返回 (set(), set())。

    支持：
    - 前端工作流格式：{ "nodes": [...], "links": [...] }
    - ComfyUI prompt 格式：{ "node_id": { "class_type": "...", "inputs": {...} } }
    """
    unknown: Tuple[Optional[Set[str]], Optional[Set[str]]] = (None, None)
    if not workflow or not isinstance(workflow, dict):
        return unknown

    node_ids: Set[str] = set()
    node_types: Dict[str, str] = {}

    # --------------------------------------------------
    # 前端 graph 格式
    # --------------------------------------------------
    nodes = workflow.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nid_raw = node.get("id")
            if nid_raw is None:
                continue
            nid = str(nid_raw)
            node_ids.add(nid)
            nt = node.get("type")
            if isinstance(nt, str):
                node_types[nid] = nt

        # link_id -> source node id
        link_to_source: Dict[Any, str] = {}
        links = workflow.get("links")
        if isinstance(links, list):
            for link in links:
                if isinstance(link, (list, tuple)) and len(link) >= 4:
                    link_to_source[link[0]] = str(link[1])
                elif isinstance(link, dict):
                    lid = link.get("id")
                    src = link.get("origin_id") or link.get("source_id")
                    if lid is not None and src is not None:
                        link_to_source[lid] = str(src)

        # 输出节点：没有 outputs 或所有 outputs 都没有连线
        output_ids: Set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nid = str(node.get("id", ""))
            if not nid or nid not in node_ids:
                continue
            outputs = node.get("outputs")
            if not isinstance(outputs, list) or not outputs:
                output_ids.add(nid)
                continue
            has_link = False
            for out in outputs:
                if isinstance(out, dict):
                    out_links = out.get("links")
                    if isinstance(out_links, list) and out_links:
                        has_link = True
                        break
            if not has_link:
                output_ids.add(nid)

        # 反向 BFS：从输出节点沿输入连线回溯
        visited: Set[str] = set()
        queue = list(output_ids)
        while queue:
            nid = queue.pop(0)
            if nid in visited or nid not in node_ids:
                continue
            visited.add(nid)
            node = next(
                (n for n in nodes if isinstance(n, dict) and str(n.get("id", "")) == nid),
                None,
            )
            if not node:
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, list):
                continue
            for inp in inputs:
                if not isinstance(inp, dict):
                    continue
                link = inp.get("link")
                if link is None or link == -1:
                    continue
                src = link_to_source.get(link)
                if src and src not in visited:
                    queue.append(src)

        types = {node_types[nid] for nid in visited if nid in node_types}
        return visited, types

    # --------------------------------------------------
    # ComfyUI prompt 格式
    # --------------------------------------------------
    prompt = workflow.get("prompt") or workflow
    if isinstance(prompt, dict):
        for nid_raw, node in prompt.items():
            if not isinstance(node, dict):
                continue
            nid = str(nid_raw)
            node_ids.add(nid)
            ct = node.get("class_type")
            if isinstance(ct, str) and ct:
                node_types[nid] = ct

        # 找到未被任何节点引用的节点 = 输出节点
        referenced: Set[str] = set()
        for node in prompt.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if isinstance(inputs, dict):
                for v in inputs.values():
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        ref = v[0]
                        if isinstance(ref, (str, int)):
                            referenced.add(str(ref))

        output_ids = node_ids - referenced
        visited: Set[str] = set()
        queue = list(output_ids)
        while queue:
            nid = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            node = prompt.get(nid)
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if isinstance(inputs, dict):
                for v in inputs.values():
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        ref = v[0]
                        if isinstance(ref, (str, int)):
                            src = str(ref)
                            if src not in visited:
                                queue.append(src)

        types = {node_types[nid] for nid in visited if nid in node_types}
        return visited, types

    return unknown


def _node_prefix(node_type: str) -> str:
    """提取节点类型的前缀（用于前缀匹配）。"""
    for sep in ("_", "-"):
        if sep in node_type:
            prefix = node_type.split(sep)[0]
            if len(prefix) >= _MIN_PREFIX_LEN:
                return prefix
    return node_type[:_MIN_PREFIX_LEN] if len(node_type) >= _MIN_PREFIX_LEN else ""


def _fuzzy_node_present(node_type: str, class_types: Set[str], packages: Set[str]) -> bool:
    """判断节点类型是否可能已安装，严格优先精确匹配，减少漏报。

    规则：
    1. 精确匹配（忽略大小写）。
    2. 对于 Package:Node 格式（自定义节点常见写法），必须精确匹配某个已安装类名，
       不再因为包名存在就误判为已安装，避免真实缺失节点被漏报。
    3. 普通节点类型使用前缀匹配，但前缀长度必须 >= _MIN_PREFIX_LEN，
       且匹配方向必须是从头开始，避免任意子串误匹配。
    """
    if not isinstance(node_type, str) or not node_type:
        return False

    # 规范化：移除冒号后的空格，统一 ComfyUI 节点类型格式
    def _norm(s: str) -> str:
        return re.sub(r":\s+", ":", s.strip().lower())

    node_lower = _norm(node_type)
    class_types_lower = {_norm(ct) for ct in class_types if isinstance(ct, str)}

    # 1. 精确匹配（忽略大小写、忽略冒号后空格）
    if node_lower in class_types_lower:
        return True

    # 1.5 内置节点白名单兜底，避免在无法读取 NODE_CLASS_MAPPINGS 时误报
    if node_lower in _CORE_NODE_WHITELIST:
        return True

    # 2. Package:Node 格式：只信任精确类名匹配，避免包名存在导致漏报
    if ":" in node_type:
        package = node_type.split(":", 1)[0].lower()
        # 如果已安装类名中有同包的其他节点，认为该包已安装且当前节点也存在
        # （同一包节点通常一起安装，但此处仍优先要求精确匹配以减少漏报）
        for ct in class_types_lower:
            if ct == node_lower:
                return True
        # 包名精确匹配作为最后兜底，仅当包名本身也是一个已注册类名时
        if package in class_types_lower:
            return True
        return False

    # 3. 普通节点类型：前缀匹配
    prefix = _node_prefix(node_type)
    if not prefix or len(prefix) < _MIN_PREFIX_LEN:
        return False

    candidates = class_types | packages
    for installed in candidates:
        if not isinstance(installed, str) or len(installed) < _MIN_PREFIX_LEN:
            continue
        installed_lower = _norm(installed)
        # 已安装类名/包名以节点前缀开头
        if installed_lower.startswith(prefix.lower()):
            return True
        # 节点类型以已安装类名/包名开头，例如 CheckpointLoaderSimple 对应 CheckpointLoader
        if node_lower.startswith(installed_lower):
            return True
    return False


def _looks_like_node_type(value: str) -> bool:
    """前端显式报告的缺失节点类型只做轻量校验，避免 UUID/空串混入。"""
    if not isinstance(value, str) or not value:
        return False
    value = _clean_missing_node_title(value)
    if len(value) < 3 or len(value) > 96:
        return False
    # 至少包含一个字母，避免纯 UUID/随机串
    if not any(ch.isalpha() for ch in value):
        return False
    # 排除明显不是节点类型的纯路径/文件
    if "/" in value or "\\" in value:
        return False
    return True


def _is_unrecognized_node_type(node_type: str) -> bool:
    """判断节点类型是否为 UUID 或无法识别的长串。

    这些值通常来自工作流中尚未安装且 ComfyUI 无法解析的自定义节点，
    直接显示会干扰用户，应聚合为友好提示。

    注意：真正的自定义节点名通常包含 _ 或 -，即使较长也不应误判。
    """
    if not isinstance(node_type, str):
        return True
    if _UUID_RE.match(node_type):
        return True
    # 只有纯随机字符（无 _-./ 分隔符）且长度异常才视为无法识别
    if len(node_type) > 36 and not any(c in node_type for c in "_-./\\"):
        return True
    return False


def _current_queue_node_types() -> Set[str]:
    """从 ComfyUI 当前运行/排队队列中提取节点类型。"""
    types: Set[str] = set()
    try:
        from server import PromptServer

        pq = PromptServer.instance.prompt_queue
        running, queued = pq.get_current_queue_volatile()
        for item in running + queued:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            prompt = item[2]
            if not isinstance(prompt, dict):
                continue
            for node in prompt.values():
                if isinstance(node, dict):
                    ct = node.get("class_type")
                    if isinstance(ct, str) and ct:
                        types.add(ct)
    except Exception as e:
        logger.debug(f"[健康检查] 读取队列失败: {e}")
    return types


def check_missing_nodes(
    workflow: Optional[Dict[str, Any]] = None,
    language: str = "zh",
    extra_missing_types: Optional[List[str]] = None,
) -> List[HealthFinding]:
    """检查当前工作流中是否有未安装的节点类型。

    Args:
        workflow: 当前工作流 JSON（前端 serialize() 结果）。
        language: 报告语言。
        extra_missing_types: 前端直接提供的缺失节点类型列表（如从 ComfyUI
            “放弃节点包”提示中收集），会与从 workflow 提取的类型合并检查。
    """
    findings: List[HealthFinding] = []

    class_types = _installed_node_class_types()
    if not class_types:
        class_types = _object_info_node_types(timeout=1.5)

    packages = _installed_custom_node_packages()

    source = "provided_workflow" if workflow else "queue"

    # 前端显式传入的缺失节点类型（来自 ComfyUI “放弃节点包” 提示或前端扫描）
    # 这些类型直接信任并报告为缺失，不再经过模糊前缀匹配，避免被误报为已安装。
    frontend_missing_types: Set[str] = set()
    if extra_missing_types:
        for nt in extra_missing_types:
            if _looks_like_node_type(nt):
                frontend_missing_types.add(nt.strip())

    # 若前端没有显式报告缺失节点，则从 workflow 提取并应用执行路径过滤，
    # 避免未连接分支上的节点造成误报。
    workflow_types: Set[str] = set()
    executed_node_ids: Optional[Set[str]] = None
    if workflow:
        executed_node_ids, _ = _get_executed_node_types(workflow)
        workflow_types = _extract_workflow_node_types(workflow, executed_node_ids)
    if not workflow_types and not frontend_missing_types:
        workflow_types = _current_queue_node_types()
        executed_node_ids = None
        source = "queue"

    if not class_types and not packages:
        findings.append(
            HealthFinding(
                severity="warning",
                category="node_check_unavailable",
                title=_t("node_check_unavailable_title", language),
                explanation=_t("node_check_unavailable_explanation", language),
                suggestion=_t("node_check_unavailable_suggestion", language),
                raw_data={"source": source},
            )
        )
        return findings

    all_types_count = len(workflow_types) + len(frontend_missing_types)
    if not all_types_count:
        # 如果用户明确传了 workflow 却提取不到节点，说明序列化异常或未加载工作流
        severity = "warning" if workflow else "info"
        findings.append(
            HealthFinding(
                severity=severity,
                category="node_no_workflow",
                title=_t("node_no_workflow_title", language),
                explanation=_t("node_no_workflow_explanation", language),
                suggestion=_t("node_no_workflow_suggestion", language),
                raw_data={"source": source, "workflow_provided": bool(workflow)},
            )
        )
        return findings

    missing_from_workflow = [
        nt
        for nt in workflow_types
        if not _fuzzy_node_present(nt, class_types, packages)
    ]
    # 前端报告的缺失节点直接加入 missing，不再做模糊匹配
    missing = set(missing_from_workflow)
    missing.update(nt for nt in frontend_missing_types if nt not in workflow_types)
    missing = sorted(missing)

    if missing:
        named_nodes = [nt for nt in missing if not _is_unrecognized_node_type(nt)]
        unrecognized_nodes = [nt for nt in missing if _is_unrecognized_node_type(nt)]

        # 聚合为一条 finding：ComfyUI 对“缺失节点”通常只给出一条报错/提示，
        # 健康检查不应把同一问题拆成 overview + individual + unrecognized 多条。
        explanation_parts: List[str] = []
        if named_nodes:
            explanation_parts.append(
                _t("node_missing_explanation", language, missing=", ".join(named_nodes[:10]))
            )
        if unrecognized_nodes:
            explanation_parts.append(
                _t(
                    "node_missing_unrecognized_explanation",
                    language,
                    count=len(unrecognized_nodes),
                    samples=", ".join(unrecognized_nodes[:3]),
                )
            )

        findings.append(
            HealthFinding(
                severity="error",
                category="node_missing",
                title=_t("node_missing_title", language, count=len(missing)),
                explanation=" ".join(explanation_parts) if explanation_parts else "",
                suggestion=_t("node_missing_suggestion", language),
                raw_data={
                    "missing_nodes": list(missing),
                    "named_nodes": named_nodes,
                    "unrecognized_nodes": unrecognized_nodes,
                    "count": len(missing),
                    "source": source,
                    "executed_node_ids": list(executed_node_ids) if executed_node_ids else None,
                },
            )
        )
    else:
        findings.append(
            HealthFinding(
                severity="info",
                category="node_ok",
                title=_t("node_ok_title", language),
                explanation=_t("node_ok_explanation", language, count=all_types_count),
                suggestion=_t("node_ok_suggestion", language),
                raw_data={"node_count": all_types_count, "source": source},
            )
        )

    return findings


# ============================================================================
# 模型缺失检查
# ============================================================================

MODEL_EXTENSIONS = {".ckpt", ".safetensors", ".pt", ".pth", ".bin", ".gguf", ".onnx"}


def _looks_like_model_filename(value: str) -> bool:
    """判断字符串是否像模型文件名。"""
    if not isinstance(value, str) or not value:
        return False
    value_lower = value.lower()
    return any(value_lower.endswith(ext) for ext in MODEL_EXTENSIONS)


def _infer_model_category(node_type: str) -> Optional[str]:
    """根据节点类型推断模型应归属的 models 子目录。"""
    nt = node_type.lower()
    # 优先精确匹配常见 Loader 节点类型，减少误推断
    loader_mapping = {
        "checkpointloader": "checkpoints",
        "checkpointloadersimple": "checkpoints",
        "unetloader": "unet",
        "unetloadergguf": "unet",
        "dualcliploader": "clip",
        "cliploader": "clip",
        "clipvisionloader": "clip_vision",
        "vaeloader": "vae",
        "loraloader": "loras",
        "loraloadermodelonly": "loras",
        "controlnetloader": "controlnet",
        "diffcontrolnetloader": "controlnet",
        "ipadaptermodelloader": "ipadapter",
        "embeddingmodelloader": "embeddings",
        "stylemodelloader": "style_models",
        "upscalemodelloader": "upscale_models",
        "t2iadapterloader": "controlnet",
    }
    if nt in loader_mapping:
        return loader_mapping[nt]
    if "checkpoint" in nt or "ckpt" in nt:
        return "checkpoints"
    if "lora" in nt:
        return "loras"
    if "vae" in nt:
        return "vae"
    if "clip_vision" in nt or "clipvision" in nt:
        return "clip_vision"
    if "clip" in nt:
        return "clip"
    if "controlnet" in nt or "t2i" in nt:
        return "controlnet"
    if "unet" in nt:
        return "unet"
    if "ipadapter" in nt:
        return "ipadapter"
    if "embedding" in nt:
        return "embeddings"
    if "diffusers" in nt:
        return "diffusers"
    if "style_model" in nt:
        return "style_models"
    if "upscale_model" in nt:
        return "upscale_models"
    return None


def _split_model_path(value: str) -> Tuple[str, Optional[str]]:
    """从可能包含 models/ 前缀或子目录的值中提取纯文件名和目录分类。

    例如：
    - "models/loras/subdir/model.safetensors" -> ("model.safetensors", "loras")
    - "subdir/model.safetensors" -> ("model.safetensors", None)
    - "model.safetensors" -> ("model.safetensors", None)
    """
    normalized = value.replace("\\", "/")
    if "models/" in normalized:
        after = normalized.split("models/", 1)[1]
        parts = [p for p in after.split("/") if p]
        if parts:
            category = parts[0] if parts[0] in MODEL_SUBDIRS else None
            return parts[-1], category
    # 不含 models/ 前缀时，仅取最后一段文件名
    return Path(normalized).name, None


def _extract_workflow_model_refs(
    workflow: Optional[Dict[str, Any]],
    executed_node_ids: Optional[Set[str]] = None,
) -> List[Tuple[str, Optional[str]]]:
    """从工作流 JSON 中提取引用的模型文件名及推断目录。

    支持：
    - 前端工作流格式：{ "nodes": [{ "type": "...", "widgets_values": [...] }] }
    - ComfyUI prompt 格式：{ "node_id": { "class_type": "...", "inputs": {...} } }

    Args:
        executed_node_ids: 若提供，仅扫描实际执行路径上的节点，避免未连接节点造成误报。
    """
    refs: List[Tuple[str, Optional[str]]] = []
    seen: Set[Tuple[str, Optional[str]]] = set()
    if not workflow or not isinstance(workflow, dict):
        return refs

    executed_node_ids = executed_node_ids or set()

    nodes = workflow.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nid = str(node.get("id", ""))
            if executed_node_ids and nid not in executed_node_ids:
                continue
            node_type = node.get("type", "")
            # 输入/输出节点的 widgets_values 通常是用户文件路径，不应被当作模型引用
            if _is_input_output_node_type(node_type):
                continue
            category = _infer_model_category(node_type)
            widgets = node.get("widgets_values")
            if isinstance(widgets, list):
                for value in widgets:
                    if isinstance(value, str) and _looks_like_model_filename(value):
                        filename, parsed_category = _split_model_path(value)
                        final_category = parsed_category or category
                        key = (filename, final_category)
                        if key not in seen:
                            seen.add(key)
                            refs.append((filename, final_category))
        return refs

    prompt = workflow.get("prompt") or workflow
    if isinstance(prompt, dict):
        for nid_raw, node in prompt.items():
            if not isinstance(node, dict):
                continue
            nid = str(nid_raw)
            if executed_node_ids and nid not in executed_node_ids:
                continue
            class_type = node.get("class_type", "")
            # 输入/输出节点的 inputs 通常是用户文件路径
            if _is_input_output_node_type(class_type):
                continue
            inputs = node.get("inputs", {})
            category = _infer_model_category(class_type)
            if isinstance(inputs, dict):
                for value in inputs.values():
                    if isinstance(value, str) and _looks_like_model_filename(value):
                        filename, parsed_category = _split_model_path(value)
                        final_category = parsed_category or category
                        key = (filename, final_category)
                        if key not in seen:
                            seen.add(key)
                            refs.append((filename, final_category))
    return refs


def _recursive_find_model(directory: Path, name: str, max_depth: int, current_depth: int = 0) -> bool:
    """在 directory 下递归查找 name 模型文件，支持忽略大小写，限制最大深度。"""
    if current_depth > max_depth:
        return False
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    if entry.name == name or entry.name.lower() == name.lower():
                        return True
                elif entry.is_dir(follow_symlinks=False):
                    if _recursive_find_model(
                        Path(entry.path), name, max_depth, current_depth + 1
                    ):
                        return True
    except OSError:
        pass
    return False


def _model_file_exists(name: str, category: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """检查模型文件是否存在于 models 目录（含 extra_model_paths 额外路径），返回 (是否存在, 找到/建议目录)。"""
    # 若 name 包含路径分隔符，先提取纯文件名进行匹配
    pure_name = Path(name.replace("\\", "/")).name

    dirs_to_search: List[Path] = []
    if category and category in MODEL_SUBDIRS:
        dirs_to_search = _get_model_search_dirs(category)
    else:
        for sub in MODEL_SUBDIRS:
            dirs_to_search.extend(_get_model_search_dirs(sub))

    for sub_dir in dirs_to_search:
        if not sub_dir.is_dir():
            continue
        if _recursive_find_model(sub_dir, pure_name, _MAX_MODEL_SEARCH_DEPTH):
            # 返回用户传入的 category，保持报告一致性
            return True, category or sub_dir.name
    return False, category


def check_missing_models(
    workflow: Optional[Dict[str, Any]] = None,
    language: str = "zh",
    executed_node_ids: Optional[Set[str]] = None,
) -> List[HealthFinding]:
    """扫描 ComfyUI/models 下常见子目录，检查模型文件是否存在。

    若传入 workflow，还会检查工作流中引用的具体模型文件是否缺失，
    并可传入 executed_node_ids 仅扫描实际执行路径上的节点，避免未连接节点造成误报。
    """
    findings: List[HealthFinding] = []

    # 使用 folder_paths 获取真实模型搜索路径（含 extra_model_paths.yaml 外部路径），
    # 不再强制要求默认 ComfyUI/models 目录存在。
    empty_dirs: List[str] = []
    total_files = 0
    dir_counts: Dict[str, int] = {}

    for sub in MODEL_SUBDIRS:
        search_dirs = _get_model_search_dirs(sub)
        if not search_dirs:
            continue
        count = 0
        for sub_dir in search_dirs:
            if sub_dir.is_dir():
                count += _count_files(sub_dir)
        dir_counts[sub] = count
        total_files += count
        if count == 0:
            empty_dirs.append(sub)

    # 只有未提供 workflow 时才报告空模型目录；提供 workflow 时只关心工作流实际引用的模型，
    # 避免把无关的空目录警告混进“错误数量”。
    # 空目录本身不是错误，降级为 info，避免与 ComfyUI 报错数量混淆。
    if not workflow:
        if empty_dirs:
            findings.append(
                HealthFinding(
                    severity="info",
                    category="model_dir_empty",
                    title=_t("model_dir_empty_title", language),
                    explanation=_t("model_dir_empty_explanation", language, dirs=", ".join(empty_dirs)),
                    suggestion=_t("model_dir_empty_suggestion", language),
                    raw_data={"empty_dirs": empty_dirs, "dir_counts": dir_counts},
                )
            )
        elif total_files == 0:
            # 没有任何常见模型子目录或子目录中均无模型文件
            findings.append(
                HealthFinding(
                    severity="warning",
                    category="model_missing",
                    title=_t("model_missing_title", language),
                    explanation=_t("model_missing_explanation", language),
                    suggestion=_t("model_missing_suggestion", language),
                    raw_data={"dir_counts": dir_counts},
                )
            )

    if workflow:
        refs = _extract_workflow_model_refs(workflow, executed_node_ids)
        missing_refs: List[Tuple[str, Optional[str]]] = []
        for name, category in refs:
            exists, found_or_suggested = _model_file_exists(name, category)
            if not exists:
                missing_refs.append((name, found_or_suggested or category))

        # 聚合为一条 finding：ComfyUI 执行时通常只报第一个缺失模型，
        # 健康检查不应把同一类问题拆成多条，避免“错误数量”与 ComfyUI 报错数量不一致。
        if missing_refs:
            names = [name for name, _ in missing_refs]
            sample_details = []
            for name, category in missing_refs[:5]:
                if category:
                    sample_details.append(f"{name} ({category})")
                else:
                    sample_details.append(name)
            findings.append(
                HealthFinding(
                    severity="error",
                    category="model_missing_specific",
                    title=_t("model_missing_aggregate_title", language, count=len(missing_refs)),
                    explanation=_t(
                        "model_missing_aggregate_explanation",
                        language,
                        names=", ".join(sample_details),
                    ),
                    suggestion=_t("model_missing_aggregate_suggestion", language),
                    raw_data={
                        "missing_models": names,
                        "count": len(missing_refs),
                        "details": [
                            {"model_name": name, "expected_category": cat}
                            for name, cat in missing_refs
                        ],
                    },
                )
            )

    return findings


# ============================================================================
# PyTorch 后端检查
# ============================================================================

def check_torch_backend(language: str = "zh") -> List[HealthFinding]:
    """检查 PyTorch 后端是否与当前 GPU 匹配。"""
    findings: List[HealthFinding] = []

    try:
        import torch
    except ImportError as e:
        findings.append(
            HealthFinding(
                severity="error",
                category="torch_missing",
                title=_t("torch_missing_title", language),
                explanation=_t("torch_missing_explanation", language, error=str(e)),
                suggestion=_t("torch_missing_suggestion", language),
            )
        )
        return findings

    cuda_version = torch.version.cuda
    hip_version = torch.version.hip
    mps_available = torch.backends.mps.is_available()
    cuda_available = torch.cuda.is_available()

    if cuda_available:
        if hip_version:
            findings.append(
                HealthFinding(
                    severity="info",
                    category="torch_backend_ok",
                    title=_t("torch_rocm_ok_title", language, ver=hip_version),
                    explanation=_t("torch_rocm_ok_explanation", language),
                    suggestion=_t("torch_rocm_ok_suggestion", language),
                )
            )
        elif cuda_version:
            findings.append(
                HealthFinding(
                    severity="info",
                    category="torch_backend_ok",
                    title=_t("torch_cuda_ok_title", language, ver=cuda_version),
                    explanation=_t("torch_cuda_ok_explanation", language),
                    suggestion=_t("torch_cuda_ok_suggestion", language),
                )
            )
        else:
            findings.append(
                HealthFinding(
                    severity="warning",
                    category="torch_backend_unknown",
                    title=_t("torch_backend_unknown_title", language),
                    explanation=_t("torch_backend_unknown_explanation", language),
                    suggestion=_t("torch_backend_unknown_suggestion", language),
                )
            )
    elif mps_available:
        findings.append(
            HealthFinding(
                severity="info",
                category="torch_backend_ok",
                title=_t("torch_mps_ok_title", language),
                explanation=_t("torch_mps_ok_explanation", language),
                suggestion=_t("torch_mps_ok_suggestion", language),
            )
        )
    else:
        if cuda_version:
            findings.append(
                HealthFinding(
                    severity="warning",
                    category="torch_backend_mismatch",
                    title=_t("torch_cuda_mismatch_title", language),
                    explanation=_t("torch_cuda_mismatch_explanation", language, ver=cuda_version),
                    suggestion=_t("torch_cuda_mismatch_suggestion", language),
                )
            )
        elif hip_version:
            findings.append(
                HealthFinding(
                    severity="warning",
                    category="torch_backend_mismatch",
                    title=_t("torch_rocm_mismatch_title", language),
                    explanation=_t("torch_rocm_mismatch_explanation", language, ver=hip_version),
                    suggestion=_t("torch_rocm_mismatch_suggestion", language),
                )
            )
        else:
            findings.append(
                HealthFinding(
                    severity="info",
                    category="torch_backend_cpu",
                    title=_t("torch_cpu_title", language),
                    explanation=_t("torch_cpu_explanation", language),
                    suggestion=_t("torch_cpu_suggestion", language),
                )
            )

    return findings


# ============================================================================
# 驱动版本检查
# ============================================================================

def _parse_nvidia_driver(stdout: str) -> Optional[str]:
    """解析 nvidia-smi 驱动版本输出。"""
    for line in stdout.strip().splitlines():
        line = line.strip()
        if line and re.match(r"^\d+(\.\d+)*$", line):
            return line
    return None


def _parse_amd_driver(stdout: str) -> Optional[str]:
    """解析 rocminfo 输出中的 ROCm 版本。"""
    for line in stdout.splitlines():
        if "ROCm Version" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
        if "Runtime Version" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
    return None


def _windows_registry_driver() -> Optional[str]:
    """从 Windows 注册表读取显卡驱动版本。"""
    try:
        import winreg  # type: ignore[import]
    except ImportError:
        return None

    key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                subname = winreg.EnumKey(key, i)
                try:
                    with winreg.OpenKey(key, subname) as subkey:
                        ver, _ = winreg.QueryValueEx(subkey, "DriverVersion")
                        if ver:
                            return str(ver)
                except (FileNotFoundError, OSError):
                    continue
    except OSError:
        pass
    return None


def check_driver_version(language: str = "zh") -> List[HealthFinding]:
    """读取当前 GPU 驱动版本。"""
    findings: List[HealthFinding] = []
    system = _platform.system()

    if system == "Linux":
        try:
            out = _run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], timeout=1.5)
            ver = _parse_nvidia_driver(out)
            if ver:
                major = int(ver.split(".")[0]) if "." in ver else 0
                severity = "warning" if major < NVIDIA_DRIVER_OLD else "info"
                suggestion_key = (
                    "driver_nvidia_suggestion_old"
                    if severity == "warning"
                    else "driver_nvidia_suggestion_ok"
                )
                findings.append(
                    HealthFinding(
                        severity=severity,
                        category="driver_nvidia",
                        title=_t("driver_nvidia_title", language, ver=ver),
                        explanation=_t("driver_nvidia_explanation", language, ver=ver),
                        suggestion=_t(suggestion_key, language),
                        raw_data={"version": ver},
                    )
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        try:
            out = _run(["rocminfo"], timeout=1.5)
            ver = _parse_amd_driver(out)
            if ver:
                findings.append(
                    HealthFinding(
                        severity="info",
                        category="driver_amd",
                        title=_t("driver_amd_title", language, ver=ver),
                        explanation=_t("driver_amd_explanation", language, ver=ver),
                        suggestion=_t("driver_amd_suggestion", language),
                        raw_data={"version": ver},
                    )
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if not findings:
            findings.append(
                HealthFinding(
                    severity="info",
                    category="driver_unknown",
                    title=_t("driver_unknown_linux_title", language),
                    explanation=_t("driver_unknown_linux_explanation", language),
                    suggestion=_t("driver_unknown_linux_suggestion", language),
                )
            )

    elif system == "Windows":
        try:
            out = _run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], timeout=1.5)
            ver = _parse_nvidia_driver(out)
            if ver:
                findings.append(
                    HealthFinding(
                        severity="info",
                        category="driver_nvidia",
                        title=_t("driver_nvidia_title", language, ver=ver),
                        explanation=_t("driver_nvidia_explanation", language, ver=ver),
                        suggestion=_t("driver_nvidia_suggestion_ok", language),
                        raw_data={"version": ver},
                    )
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if not findings:
            ver = _windows_registry_driver()
            if ver:
                findings.append(
                    HealthFinding(
                        severity="info",
                        category="driver_windows",
                        title=_t("driver_windows_title", language, ver=ver),
                        explanation=_t("driver_windows_explanation", language),
                        suggestion=_t("driver_windows_suggestion", language),
                        raw_data={"version": ver},
                    )
                )

        if not findings:
            findings.append(
                HealthFinding(
                    severity="info",
                    category="driver_unknown",
                    title=_t("driver_unknown_windows_title", language),
                    explanation=_t("driver_unknown_windows_explanation", language),
                    suggestion=_t("driver_unknown_windows_suggestion", language),
                )
            )

    else:
        findings.append(
            HealthFinding(
                severity="info",
                category="driver_unsupported_platform",
                title=_t("driver_unsupported_platform_title", language),
                explanation=_t("driver_unsupported_platform_explanation", language, system=system),
                suggestion=_t("driver_unsupported_platform_suggestion", language),
            )
        )

    return findings


# ============================================================================
# 系统内存检查
# ============================================================================

def _system_memory_gb() -> float:
    """读取系统总内存（GB）。"""
    try:
        import psutil

        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        pass

    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024 ** 2)
    except Exception:
        pass

    return 0.0


def check_system_memory(language: str = "zh") -> List[HealthFinding]:
    """检查系统内存是否满足 ComfyUI 运行建议。"""
    findings: List[HealthFinding] = []
    total_gb = _system_memory_gb()

    if total_gb <= 0:
        findings.append(
            HealthFinding(
                severity="warning",
                category="memory_unknown",
                title=_t("memory_unknown_title", language),
                explanation=_t("memory_unknown_explanation", language),
                suggestion=_t("memory_unknown_suggestion", language),
            )
        )
        return findings

    if total_gb < MIN_MEMORY_GB:
        findings.append(
            HealthFinding(
                severity="warning",
                category="memory_low",
                title=_t("memory_low_title", language, total=total_gb),
                explanation=_t("memory_low_explanation", language, min=int(MIN_MEMORY_GB)),
                suggestion=_t("memory_low_suggestion", language),
                raw_data={"total_gb": round(total_gb, 2)},
            )
        )
    else:
        findings.append(
            HealthFinding(
                severity="info",
                category="memory_ok",
                title=_t("memory_ok_title", language, total=total_gb),
                explanation=_t("memory_ok_explanation", language, min=int(MIN_MEMORY_GB)),
                suggestion=_t("memory_ok_suggestion", language),
                raw_data={"total_gb": round(total_gb, 2)},
            )
        )

    return findings


# ============================================================================
# 综合健康检查
# ============================================================================

def health_check(
    workflow: Optional[Dict[str, Any]] = None,
    language: str = "zh",
    include_info: bool = False,
    extra_missing_types: Optional[List[str]] = None,
    scope: Optional[str] = None,
) -> HealthReport:
    """执行环境健康检查并返回报告。

    默认情况下只返回 error/warning 级别的 finding，避免 info 提示干扰用户。
    如需完整信息，可传入 include_info=True。

    Args:
        extra_missing_types: 前端直接提供的缺失节点类型/包名列表，会合并到节点缺失检查中。
        scope: 检查范围。
            - "workflow"（默认值当提供 workflow 时）：只将工作流相关检查（节点、模型）
              计入错误/警告计数；环境检查（PyTorch、驱动、内存）降级为 info，
              避免 ComfyUI 只报 1 条错时健康检查却列出多条环境问题。
            - "full" 或 None：完整环境扫描，所有 error/warning 均计入计数。
    """
    start = time.time()
    findings: List[HealthFinding] = []

    if scope not in ("workflow", "environment", "full"):
        scope = "workflow" if workflow else "full"

    executed_node_ids: Optional[Set[str]] = None
    if workflow and scope == "workflow":
        executed_node_ids, _ = _get_executed_node_types(workflow)

    node_findings = check_missing_nodes(
        workflow, language=language, extra_missing_types=extra_missing_types
    )
    model_findings = check_missing_models(
        workflow=workflow, language=language, executed_node_ids=executed_node_ids
    )
    env_findings = (
        check_torch_backend(language=language)
        + check_driver_version(language=language)
        + check_system_memory(language=language)
    )

    if scope == "workflow":
        # 工作流模式下：环境检查降级为 info，避免它们 inflate 错误数量
        for f in env_findings:
            f.severity = "info"
        findings = node_findings + model_findings + env_findings
    elif scope == "environment":
        findings = env_findings
    else:
        findings = node_findings + model_findings + env_findings

    elapsed = time.time() - start

    if not include_info:
        findings = [f for f in findings if f.severity in ("error", "warning")]

    severity_counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    if severity_counts["error"]:
        top_severity = "error"
        title = _t("health_error_title", language)
    elif severity_counts["warning"]:
        top_severity = "warning"
        title = _t("health_warning_title", language)
    else:
        top_severity = "info"
        title = _t("health_ok_title", language)

    suggestions: List[str] = []
    if severity_counts["error"]:
        suggestions.append(_t("health_suggestion_error", language))
    if severity_counts["warning"]:
        suggestions.append(_t("health_suggestion_warning", language))
    if not suggestions:
        suggestions.append(_t("health_suggestion_ok", language))

    workflow_node_count = len(_extract_workflow_node_types(workflow)) if workflow else 0

    system_context = {
        "severity_counts": severity_counts,
        "elapsed_seconds": elapsed,
        "workflow_node_count": workflow_node_count,
        "source": "provided_workflow" if workflow else "queue",
        "scope": scope,
    }
    category_label = (
        _t("health_ok_title", language)
        if top_severity == "info"
        else _t("health_error_title", language) if top_severity == "error" else _t("health_warning_title", language)
    )

    return HealthReport(
        error_node=None,
        matched=True,
        category="health_check",
        category_label=category_label,
        status=top_severity,
        scope=scope,
        severity=top_severity,
        title=title,
        explanation=_t("health_explanation", language, count=len(findings), elapsed=elapsed),
        suggestions=suggestions,
        findings=[f.to_dict() for f in findings],
        raw_error="",
        node_info={
            "workflow_node_count": workflow_node_count,
            "source": "provided_workflow" if workflow else "queue",
            "scope": scope,
        },
        system_snapshot=system_context,
        system_context=system_context,
        language=language,
        timestamp=time.time(),
        elapsed_seconds=elapsed,
    )
