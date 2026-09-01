"""
ComfyUI-Feixue-UniversalMonitor - DIAG 错误词库与翻译系统

职责：
1. 从 ComfyUI 实际报错信息中提炼可正则匹配的错误模式。
2. 提供多语言（至少中英）错误标题、说明与解决建议。
3. 建议根据 GPU 显存容量进行差异化表达。
4. 保持词库总大小 < 100KB；ERROR_DICT 在模块导入时全量加载到内存，匹配时按目标语言选择对应翻译。

设计约束：
- 所有错误条目以纯 Python 数据结构存放，便于运行时直接迭代。
- 建议项通过 VRAM 谓词函数过滤，确保返回的建议与当前硬件匹配。
- 未知错误由 diagnoser.py 中的兜底逻辑处理，不存放在本词库。

版本: 1.0.0
作者: Feixue
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# ============================================================================
# 版本与元数据
# ============================================================================

ERROR_DICT_VERSION = "1.5.2"
SUPPORTED_LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "en"

# ============================================================================
# VRAM 容量谓词（用于差异化建议）
# ============================================================================

VRAM_MB_8GB = 8192
VRAM_MB_16GB = 16384
VRAM_MB_24GB = 24576


def _vram_low(vram_total_mb: Optional[int], _platform: Optional[str] = None) -> bool:
    """显存小于 8GB（含未知）。"""
    return vram_total_mb is None or vram_total_mb < VRAM_MB_8GB


def _vram_mid(vram_total_mb: Optional[int], _platform: Optional[str] = None) -> bool:
    """显存 8GB ~ 16GB。"""
    return vram_total_mb is not None and VRAM_MB_8GB <= vram_total_mb < VRAM_MB_16GB


def _vram_high(vram_total_mb: Optional[int], _platform: Optional[str] = None) -> bool:
    """显存 16GB ~ 24GB。"""
    return vram_total_mb is not None and VRAM_MB_16GB <= vram_total_mb < VRAM_MB_24GB


def _vram_very_high(vram_total_mb: Optional[int], _platform: Optional[str] = None) -> bool:
    """显存大于等于 24GB。"""
    return vram_total_mb is not None and vram_total_mb >= VRAM_MB_24GB


def _vram_always(_vram_total_mb: Optional[int] = None, _platform: Optional[str] = None) -> bool:
    """无条件适用的建议。"""
    return True


# 平台相关谓词（与显存谓词签名保持一致，便于统一过滤）
# 同时兼容 platform.system() 大写、platform_detect.py 小写以及常见别名。
def _plat_windows(_vram_total_mb: Optional[int] = None, platform: Optional[str] = None) -> bool:
    """当前平台为 Windows。"""
    return isinstance(platform, str) and platform.lower() == "windows"


def _plat_linux(_vram_total_mb: Optional[int] = None, platform: Optional[str] = None) -> bool:
    """当前平台为 Linux。"""
    return isinstance(platform, str) and platform.lower() == "linux"


def _plat_macos(_vram_total_mb: Optional[int] = None, platform: Optional[str] = None) -> bool:
    """当前平台为 macOS。"""
    return isinstance(platform, str) and platform.lower() in ("darwin", "macos")


# 建议项类型：("谓词函数", "对应语言文本")
# 谓词签名统一为 (vram_total_mb: Optional[int], platform: Optional[str]) -> bool
SuggestionItem = Tuple[Optional[Callable[..., bool]], str]


def _pick_suggestions(
    items: List[SuggestionItem],
    vram_total_mb: Optional[int],
    platform: Optional[str] = None,
) -> List[str]:
    """根据显存容量和平台过滤建议项，返回文本列表。

    规则：
    - 谓词为 None 或返回 True 的建议项会被保留。
    - 无条件建议（_vram_always）始终保留。
    - 平台谓词（_plat_windows / _plat_linux / _plat_macos）只在识别到平台时生效，
      未识别平台时会被跳过，避免误导。
    - 保留原始顺序，便于前端按优先级展示。
    """
    result: List[str] = []
    for predicate, text in items:
        if predicate is None:
            result.append(text)
            continue
        try:
            if predicate(vram_total_mb, platform):
                result.append(text)
        except TypeError:
            # 兼容旧版只接受 vram_total_mb 的谓词
            try:
                if predicate(vram_total_mb):  # type: ignore[call-arg]
                    result.append(text)
            except Exception:
                pass
    return result


# ============================================================================
# 错误词库
# ============================================================================

# 每条错误包含：
# - error_key: 唯一标识
# - patterns: 正则表达式列表（按优先级顺序，优先匹配具体模式）
# - category: 错误分类
# - translations: {lang: {title, explanation}}
# - suggestions: {lang: [(predicate, text), ...]}

ERROR_DICT: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------
    # OOM 类（最优先匹配，避免被通用 RuntimeError 截获）
    # ------------------------------------------------------------------
    {
        "error_key": "cuda_oom",
        "patterns": [
            r"CUDA out of memory",
            r"CUDA error:\s*out of memory",
            r"torch\.cuda\.OutOfMemoryError",
            r"RuntimeError: CUDA out of memory",
        ],
        "category": "oom",
        "translations": {
            "zh": {
                "title": "CUDA 显存不足 (OOM)",
                "explanation": "当前工作流需要的显存超出了 GPU 显存容量，通常由分辨率过高、批量大、模型体积大或同时加载多个 LoRA/ControlNet 导致。",
            },
            "en": {
                "title": "CUDA Out of Memory",
                "explanation": "The workflow requires more VRAM than available on the GPU. Common causes: high resolution, large batch size, large models, or loading multiple LoRAs/ControlNets simultaneously.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "在 ComfyUI 启动参数中加入 --lowvram 或 --normalvram，并启用 tiled VAE 节点降低显存峰值。"),
            ],
            "en": [
                (_vram_always, "Add --lowvram or --normalvram to ComfyUI launch args and enable tiled VAE to reduce VRAM peaks."),
            ],
        },
    },
    {
        "error_key": "rocm_oom",
        "patterns": [
            r"hipError_t::hipOutOfMemory",
            r"HIP out of memory",
            r"ROCm out of memory",
            r"RuntimeError: out of memory.*hip",
        ],
        "category": "oom",
        "translations": {
            "zh": {
                "title": "ROCm / HIP 显存不足",
                "explanation": "AMD 显卡通过 ROCm/HIP 后端运行时显存耗尽，原因与 CUDA OOM 类似。",
            },
            "en": {
                "title": "ROCm / HIP Out of Memory",
                "explanation": "The AMD GPU ran out of VRAM through the ROCm/HIP backend. Causes are similar to CUDA OOM.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "在 ComfyUI 启动参数中加入 --lowvram 或 --normalvram，并启用 tiled VAE 节点。"),
            ],
            "en": [
                (_vram_always, "Add --lowvram or --normalvram to ComfyUI launch args and enable tiled VAE."),
            ],
        },
    },
    {
        "error_key": "mps_oom",
        "patterns": [
            r"MPS out of memory",
            r"Metal out of memory",
            r"mps out of memory",
            r"RuntimeError: out of memory.*mps",
        ],
        "category": "oom",
        "translations": {
            "zh": {
                "title": "Apple Silicon / MPS 显存不足",
                "explanation": "Mac 通过 MPS 后端运行时共享内存/显存不足，通常由模型过大或分辨率过高导致。",
            },
            "en": {
                "title": "Apple Silicon / MPS Out of Memory",
                "explanation": "The Mac ran out of shared memory/VRAM through the MPS backend. Common causes: oversized model or high resolution.",
            },
        },
        "suggestions": {
            "zh": [
                (_plat_macos, "macOS 启动前执行 export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.7 以限制 PyTorch MPS 内存占用。"),
            ],
            "en": [
                (_plat_macos, "On macOS, run export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.7 before launch to limit PyTorch MPS memory usage."),
            ],
        },
    },
    {
        "error_key": "shared_memory_insufficient",
        "patterns": [
            r"shared memory",
            r"Unable to allocate shared memory",
            r"could not create shared memory",
            r"SharedMemory",
        ],
        "category": "oom",
        "translations": {
            "zh": {
                "title": "共享内存不足",
                "explanation": "进程间通信或 DataLoader 所需的共享内存（shm）不足，常见于 Docker / WSL2 容器环境。",
            },
            "en": {
                "title": "Insufficient Shared Memory",
                "explanation": "Inter-process communication or DataLoader requires more shared memory (shm) than available, common in Docker / WSL2 containers.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "Docker 用户启动容器时加入 --shm-size=8g（或更大，如 16g）。"),
            ],
            "en": [
                (_vram_always, "Docker users: add --shm-size=8g (or larger, e.g. 16g) when starting the container."),
            ],
        },
    },
    {
        "error_key": "oom",
        "patterns": [
            r"out of memory",
            r"OOM",
            r"爆显存",
            r"显存不足",
            r"内存不足",
            r"insufficient memory",
        ],
        "category": "oom",
        "translations": {
            "zh": {
                "title": "显存/内存不足 (OOM)",
                "explanation": "当前工作流需要的显存或系统内存超过可用容量，通常由 batch 过大、分辨率过高、模型体积大或同时加载多个模型导致。",
            },
            "en": {
                "title": "Out of Memory (OOM)",
                "explanation": "The workflow requires more VRAM or system memory than available. Common causes: large batch size, high resolution, large models, or loading multiple models simultaneously.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "降低 batch size、生成分辨率或模型精度（如改用 FP8/INT8 量化模型），并在启动参数中加入 --lowvram / --normalvram。"),
            ],
            "en": [
                (_vram_always, "Lower batch size, generation resolution, or model precision (e.g. switch to FP8/INT8 quantized models), and add --lowvram / --normalvram to launch args."),
            ],
        },
    },

    # ------------------------------------------------------------------
    # GPU 后端检测失败（启动阶段常见）
    # ------------------------------------------------------------------
    {
        "error_key": "no_cuda_gpu_available",
        "patterns": [
            r"No CUDA GPUs are available",
            r"No CUDA runtime is found",
            r"Found no NVIDIA driver",
            r"cuda.*not available",
            r"NVIDIA driver.*not found",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "未检测到可用的 CUDA / NVIDIA GPU",
                "explanation": "PyTorch 无法找到可用的 NVIDIA GPU 或 CUDA 运行时。常见原因：未安装 NVIDIA 驱动、PyTorch 为 CPU 版本、CUDA 版本与驱动不匹配，或使用的是笔记本混合显卡未切换到独显。",
            },
            "en": {
                "title": "No CUDA / NVIDIA GPU Available",
                "explanation": "PyTorch cannot find an available NVIDIA GPU or CUDA runtime. Common causes: NVIDIA driver not installed, PyTorch CPU-only build, CUDA version mismatch, or laptop hybrid graphics not switched to discrete GPU.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "执行 python -c \"import torch; print(torch.cuda.is_available()); print(torch.version.cuda)\" 确认 PyTorch 是否为 CUDA 版本。"),
            ],
            "en": [
                (_vram_always, "Run python -c \"import torch; print(torch.cuda.is_available()); print(torch.version.cuda)\" to confirm PyTorch is a CUDA build."),
            ],
        },
    },
    {
        "error_key": "no_hip_gpu_available",
        "patterns": [
            r"No HIP GPUs are available",
            r"No HIP runtime is found",
            r"hip.*not available",
            r"No AMD GPU detected",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "未检测到可用的 HIP / AMD GPU",
                "explanation": "PyTorch 无法找到可用的 AMD GPU 或 HIP 运行时。常见于 ROCm 未安装、驱动未加载、用户未加入 render/video 组，或 PyTorch 安装的是 CUDA/CPU 版本。",
            },
            "en": {
                "title": "No HIP / AMD GPU Available",
                "explanation": "PyTorch cannot find an available AMD GPU or HIP runtime. Common causes: ROCm not installed, driver not loaded, user not in render/video group, or PyTorch is a CUDA/CPU build.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "执行 python -c \"import torch; print(torch.cuda.is_available()); print(torch.version.hip)\" 确认 PyTorch 是否为 ROCm 版本。"),
            ],
            "en": [
                (_vram_always, "Run python -c \"import torch; print(torch.cuda.is_available()); print(torch.version.hip)\" to confirm PyTorch is a ROCm build."),
            ],
        },
    },
    {
        "error_key": "hip_runtime_error",
        "patterns": [
            r"HIP error:\s*invalid argument",
            r"hipError_t::hipErrorInvalidArgument",
            r"HIP runtime error",
            r"hipLaunchKernel",
            r"HIP error",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "HIP / ROCm 运行时错误",
                "explanation": "AMD GPU 在执行 HIP 内核时发生运行时错误，通常由 ROCm 版本与显卡架构不匹配、环境变量缺失或 PyTorch ROCm wheel 不兼容导致。",
            },
            "en": {
                "title": "HIP / ROCm Runtime Error",
                "explanation": "A HIP runtime error occurred while executing on the AMD GPU. Usually caused by ROCm version/GPU architecture mismatch, missing environment variables, or incompatible PyTorch ROCm wheel.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "执行 rocm-smi 或 rocminfo 确认 ROCm 能识别到 GPU 及架构（如 gfx1100、gfx1030）。"),
            ],
            "en": [
                (_vram_always, "Run rocm-smi or rocminfo to verify ROCm detects the GPU and its architecture (e.g. gfx1100, gfx1030)."),
            ],
        },
    },
    {
        "error_key": "torch_not_compiled_with_cuda",
        "patterns": [
            r"Torch not compiled with CUDA enabled",
            r"torch\.cuda\.is_available\(\)\s*returned\s*False.*CUDA",
            r"No CUDA GPUs are available",
            r"Found no NVIDIA driver",
            r"CUDA driver.*not found",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "PyTorch 未编译 CUDA 支持 / 未检测到 NVIDIA GPU",
                "explanation": "当前 PyTorch 是 CPU 版本，或 CUDA 驱动/NVIDIA 驱动未正确安装，导致无法使用 GPU 加速。",
            },
            "en": {
                "title": "PyTorch Not Compiled with CUDA / No NVIDIA GPU Detected",
                "explanation": "The current PyTorch build does not support CUDA, or the CUDA/NVIDIA driver is not installed correctly, so GPU acceleration is unavailable.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "执行 python -c \"import torch; print(torch.version.cuda); print(torch.cuda.is_available())\" 确认 PyTorch 版本。"),
            ],
            "en": [
                (_vram_always, "Run python -c \"import torch; print(torch.version.cuda); print(torch.cuda.is_available())\" to confirm the PyTorch version."),
            ],
        },
    },

    # ------------------------------------------------------------------
    # CUDA 设备索引越界 / 启动参数错误（启动阶段常见）
    # ------------------------------------------------------------------
    {
        "error_key": "cuda_device_index_error",
        "patterns": [
            r"invalid device ordinal",
            r"CUDA error:\s*invalid device ordinal",
            r"CUDA out of device bounds",
            r"--cuda-device.*invalid",
            r"cuda.*device.*index.*out of range",
            r"RuntimeError:\s*CUDA error.*device",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "CUDA 设备索引越界 / --cuda-device 参数错误",
                "explanation": "指定的 CUDA 设备索引不存在，常见于多 GPU 环境中索引号写错，或单卡机器使用了 --cuda-device 1/2 等越界值。",
            },
            "en": {
                "title": "CUDA Device Index Out of Range / --cuda-device Argument Error",
                "explanation": "The specified CUDA device index does not exist. Common when the index is wrong in a multi-GPU setup, or a single-GPU machine uses --cuda-device 1/2 etc.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "执行 nvidia-smi 查看实际可用的 GPU 编号（从 0 开始）。"),
            ],
            "en": [
                (_vram_always, "Run nvidia-smi to see actual available GPU indices (starting from 0)."),
            ],
        },
    },
    {
        "error_key": "launch_argument_error",
        "patterns": [
            r"unrecognized arguments",
            r"argument.*invalid",
            r"invalid choice",
            r"error:\s*the following arguments are required",
            r"Command line argument.*error",
            r"unrecognized.*--",
            r"got an unexpected argument",
            r"invalid value.*--",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "ComfyUI 启动参数错误",
                "explanation": "启动参数拼写错误、值不合法，或当前 ComfyUI 版本不支持该参数。常见如 --max-memory（单位为 MB，不是 GB）、--preview-method、--cache-mode 等参数写错。",
            },
            "en": {
                "title": "ComfyUI Launch Argument Error",
                "explanation": "A launch argument is misspelled, has an invalid value, or is not supported by this ComfyUI version. Common mistakes: --max-memory uses MB not GB, --preview-method, --cache-mode, etc.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查启动参数拼写，移除或修正不支持的参数；可用 python main.py --help 查看当前 ComfyUI 支持的参数列表。"),
            ],
            "en": [
                (_vram_always, "Check launch argument spelling, remove or correct unsupported args; run python main.py --help to see supported parameters."),
            ],
        },
    },

    # ------------------------------------------------------------------
    # 前端校验错误（不触发 execution_error，但在工作流总览/节点上显示）
    # ------------------------------------------------------------------
    {
        "error_key": "frontend_connection_interrupted",
        "patterns": [
            # 仅匹配明确的前端工作流连线/执行连接中断，不命中普通网络连接错误。
            # 注意：不命中后端 execution_error 中的 "workflow connection failed" 等字样。
            r"前端工作流校验错误",
            r"前端工作流连接中断",
            r"\bnode connection interrupted\b",
            r"\bfrontend\b.*\bworkflow\b.*\bconnection\b.*\b(interrupted|broken|failed|error|disconnected)\b",
            r"链路中断",
            r"工作流连接断开",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "工作流连接中断",
                "explanation": "ComfyUI 前端检测到工作流中的连线或执行连接中断，可能是必填输入未连接、节点被删除或工作流加载不完整导致。",
            },
            "en": {
                "title": "Workflow Connection Interrupted",
                "explanation": "The ComfyUI frontend detected an interrupted connection in the workflow. This may be caused by required inputs not being connected, nodes being deleted, or an incomplete workflow load.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查工作流中的节点连线，确保所有输入/输出插槽已正确连接。"),
            ],
            "en": [
                (_vram_always, "Check node connections and ensure all input/output slots are correctly connected."),
            ],
        },
    },
    {
        "error_key": "input_slot_not_connected",
        "patterns": [
            # 仅命中 ComfyUI 前端/验证阶段关于输入插槽未连线的明确表述，
            # 避免把后端节点函数中的 "input not connected to device" 等误分类。
            r"输入插槽没有连接",
            r"输入插槽未连接",
            r"所需的输入插槽没有连接",
            r"\binput slot not connected\b",
            r"\brequired input slot\b.*\bnot connected\b",
            r"\binput slot\b.*\b(disconnected|missing)\b",
            r"缺少输入连线",
            r"输入未连线",
            r"缺少输入",
            r"输入插槽.*未连接",
            r"输入.*未连接",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "输入插槽未连接",
                "explanation": "工作流中存在必填的输入插槽没有连接数据源，ComfyUI 无法执行该节点。常见于断开 Load Image、Prompt、Model 等关键输入后尝试运行。",
            },
            "en": {
                "title": "Input Slot Not Connected",
                "explanation": "A required input slot in the workflow is not connected to a data source, so ComfyUI cannot execute the node. Common after disconnecting Load Image, Prompt, or Model inputs and trying to run.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查节点连线，确认所有必填输入插槽已连接到正确来源。"),
            ],
            "en": [
                (_vram_always, "Check node connections and ensure all required input slots are connected to the correct sources."),
            ],
        },
    },
    {
        "error_key": "required_widget_empty",
        "patterns": [
            # 仅命中节点 widget/参数为空的明确表述，避免与 input_slot_not_connected 混淆。
            r"缺少必填信息",
            r"\brequired widget is empty\b",
            r"\brequired widget\b.*\bempty\b",
            r"\bwidget\b.*\bis empty\b",
            r"必填参数为空",
            r"必填参数未填写",
            r"缺少必填参数",
            r"必需输入",
            r"部分要点",
            r"加载图片",
            r"未选择图片",
            r"未加载图像",
            r"未上传图片",
            r"必填参数未填写",
            r"必填项为空",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "必填参数为空",
                "explanation": "节点中存在必填参数（widget）未填写或为空，ComfyUI 无法执行该节点。常见于 Load Image 未选择图片、提示词/路径/数值留空等。",
            },
            "en": {
                "title": "Required Widget Empty",
                "explanation": "A required widget/parameter in a node is empty or not filled, so ComfyUI cannot execute the node. Common when prompts, paths, or numeric values are left blank.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查节点参数是否填写完整，确保所有标有红色边框或*号的必填项已输入有效值。"),
            ],
            "en": [
                (_vram_always, "Check that node parameters are fully filled, and ensure all required fields marked with a red border or asterisk contain valid values."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # ComfyUI /prompt node_errors 校验错误（来自 execution.validate_inputs）
    # ------------------------------------------------------------------
    {
        "error_key": "required_input_missing",
        "patterns": [
            r"\brequired_input_missing\b",
            r"\bRequired input is missing\b",
            r"\brequired input is missing\b",
            r"\bRequired input.*missing\b",
            r"必填输入缺失",
            r"缺少必填输入",
            r"必填输入.*缺失",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "必填输入缺失",
                "explanation": "ComfyUI 校验发现某个必填输入未提供，可能是输入插槽未连接或 widget 参数未填写。",
            },
            "en": {
                "title": "Required Input Missing",
                "explanation": "ComfyUI validation found a required input that was not provided; the input slot may be disconnected or the widget parameter may be empty.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错节点，将该必填输入连接到有效来源或填写 widget 参数值。"),
            ],
            "en": [
                (_vram_always, "Check the failing node and connect the required input to a valid source or fill in the widget parameter value."),
            ],
        },
    },
    {
        "error_key": "value_not_in_list",
        "patterns": [
            r"\bvalue_not_in_list\b",
            r"\bValue not in list\b",
            r"\bvalue not in list\b",
            r"\bnot in list\b",
            r"选项不在列表",
            r"不在列表中",
            r"值不在列表",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "选项值不在列表中",
                "explanation": "节点某个下拉框或列表参数选择了无效值，常见于模型文件名变更后工作流仍引用旧名称。",
            },
            "en": {
                "title": "Value Not In List",
                "explanation": "A dropdown or list parameter in a node has an invalid value; common after a model filename changes but the workflow still references the old name.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "重新点击报错节点的下拉框，选择当前 models 目录中实际存在的有效值。"),
            ],
            "en": [
                (_vram_always, "Click the dropdown in the failing node and select a value that currently exists in the models directory."),
            ],
        },
    },
    {
        "error_key": "invalid_input_type",
        "patterns": [
            r"\binvalid_input_type\b",
            r"\bFailed to convert an input value\b",
            r"\bFailed to convert an input value to a\b",
            r"\bInvalid input type\b",
            r"输入类型无效",
            r"类型转换失败",
            r"无法转换输入值",
            r"convert input",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "输入值类型转换失败",
                "explanation": "节点某个参数的值无法转换成期望类型（如 INT/FLOAT/STRING/BOOLEAN），可能是输入了非法字符或空值。",
            },
            "en": {
                "title": "Invalid Input Type",
                "explanation": "A node parameter value could not be converted to the expected type (INT/FLOAT/STRING/BOOLEAN); likely caused by illegal characters or an empty value.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错节点的参数值，确保输入的是有效数字/文本/布尔值，必要时重新拖拽一个新节点替换。"),
            ],
            "en": [
                (_vram_always, "Check the parameter values in the failing node, ensure valid numbers/text/booleans, and replace the node with a fresh one if necessary."),
            ],
        },
    },
    {
        "error_key": "return_type_mismatch",
        "patterns": [
            r"\breturn_type_mismatch\b",
            r"\bReturn type mismatch\b",
            r"\bReturn type mismatch between linked nodes\b",
            r"\btype mismatch\b",
            r"类型不匹配",
            r"输出类型不匹配",
            r"input.*type.*mismatch",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "节点输出类型不匹配",
                "explanation": "两个相连节点的输入/输出类型不兼容，ComfyUI 无法在它们之间传递数据。",
            },
            "en": {
                "title": "Return Type Mismatch",
                "explanation": "The input/output types of two connected nodes are incompatible; ComfyUI cannot pass data between them.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错节点的输入连线，确保上游节点输出类型与当前节点输入类型一致。"),
            ],
            "en": [
                (_vram_always, "Check the input connections of the failing node and ensure the upstream output type matches the current node's input type."),
            ],
        },
    },
    {
        "error_key": "custom_validation_failed",
        "patterns": [
            r"\bcustom_validation_failed\b",
            r"\bCustom validation failed\b",
            r"\bCustom validation failed for node\b",
            r"自定义校验失败",
            r"节点校验失败",
            r"VALIDATE_INPUTS",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "节点自定义校验失败",
                "explanation": "节点内部的 VALIDATE_INPUTS 校验未通过，通常是参数组合不合法或缺少依赖文件。",
            },
            "en": {
                "title": "Custom Validation Failed",
                "explanation": "The node's internal VALIDATE_INPUTS check failed; usually due to an invalid parameter combination or missing dependency file.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错节点的参数设置，阅读该节点文档中关于必填项和参数组合的说明。"),
            ],
            "en": [
                (_vram_always, "Check the parameter settings of the failing node and read its documentation for required fields and valid combinations."),
            ],
        },
    },
    {
        "error_key": "value_out_of_range",
        "patterns": [
            r"\bvalue_smaller_than_min\b",
            r"\bvalue_bigger_than_max\b",
            r"\bValue .* smaller than min\b",
            r"\bValue .* bigger than max\b",
            r"\bvalue out of range\b",
            r"超出范围",
            r"值超出范围",
            r"大于最大值",
            r"小于最小值",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "参数值超出允许范围",
                "explanation": "节点某个数值参数低于最小值或高于最大值。",
            },
            "en": {
                "title": "Value Out Of Range",
                "explanation": "A numeric parameter in a node is below the minimum or above the maximum allowed value.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "将报错节点的数值参数调整到允许范围内。"),
            ],
            "en": [
                (_vram_always, "Adjust the numeric parameter in the failing node to within the allowed range."),
            ],
        },
    },
    {
        "error_key": "dependency_cycle",
        "patterns": [
            r"\bdependency_cycle\b",
            r"\bDependency cycle detected\b",
            r"\bDependency cycle\b",
            r"\bcycle detected\b",
            r"循环依赖",
            r"检测到循环",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "工作流存在循环依赖",
                "explanation": "节点之间形成了闭环连接，ComfyUI 无法确定执行顺序。",
            },
            "en": {
                "title": "Dependency Cycle",
                "explanation": "Nodes are connected in a loop; ComfyUI cannot determine the execution order.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查节点连线，打破循环连接，确保数据流向始终从上游到下游。"),
            ],
            "en": [
                (_vram_always, "Check node connections, break the loop, and ensure data always flows from upstream to downstream."),
            ],
        },
    },
    {
        "error_key": "prompt_validation_failed",
        "patterns": [
            # 注意：Prompt execution failed 是后端任意节点执行失败时的通用前缀，
            # 不代表验证阶段失败，必须排除，避免把所有 execution_error 误诊为验证错误。
            r"\bPrompt outputs failed validation\b",
            r"\bValue not in list\b",
            r"\bckpt_name\b.*\bnot in\b",
            r"\bmodel\b.*\bnot in list\b",
            r"\bInvalid input type\b",
            r"\bMissing required parameter\b",
            r"\bvalidate_inputs\b",
            r"\bvalidation error\b",
            r"工作流验证失败",
            r"Prompt验证失败",
            r"无法验证工作流",
            r"校验失败",
            r"验证失败",
            r"prompt.*validation",
        ],
        "category": "workflow_validation",
        "translations": {
            "zh": {
                "title": "Prompt / 工作流验证失败",
                "explanation": "ComfyUI 在执行前验证工作流失败，常见原因包括：节点下拉框选择了不存在的模型、必填参数无效、工作流中引用了未安装的节点，或模型未出现在对应目录的扫描列表中。",
            },
            "en": {
                "title": "Prompt / Workflow Validation Failed",
                "explanation": "ComfyUI failed to validate the workflow before execution. Common causes: a dropdown references a model that does not exist, required parameters are invalid, the workflow references uninstalled nodes, or the model is not scanned into the corresponding directory list.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错中的节点与字段名，确认下拉框中选择的模型/文件确实存在于 models/ 对应子目录。"),
            ],
            "en": [
                (_vram_always, "Check the node and field names in the error; confirm the selected model/file in the dropdown actually exists in the corresponding models/ subdirectory."),
            ],
        },
    },
    {
        "error_key": "graph_load_node_missing",
        "patterns": [
            r"When loading the graph, the following node types were not found",
            r"following node types were not found",
            r"was-node-list-create",
            r"放弃节点包",
            r"missing custom nodes",
            r"custom nodes.*missing",
            r"nodes.*not found.*workflow",
            r"node types were not found",
            r"node.*not installed",
            r"custom node.*not installed",
            r"The custom node may not be installed",
            r"missing_node_type",
            r"MissingNode",
        ],
        "category": "node_not_found",
        "translations": {
            "zh": {
                "title": "工作流加载时发现缺失节点 / 放弃节点包",
                "explanation": "当前加载的工作流包含本环境未安装或未成功加载的自定义节点，ComfyUI 已用红框/放弃节点包提示。",
            },
            "en": {
                "title": "Missing Nodes When Loading Workflow / Abandoned Node Packages",
                "explanation": "The loaded workflow contains custom nodes that are not installed or failed to load in this environment. ComfyUI has marked them with red borders or 'abandoned node package' prompts.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "在 ComfyUI 界面中查看红框节点，记录节点类型名，然后到 ComfyUI Manager → Install Missing Custom Nodes 中搜索安装。"),
            ],
            "en": [
                (_vram_always, "Check red-bordered nodes in the ComfyUI interface, note their type names, then use ComfyUI Manager → Install Missing Custom Nodes."),
            ],
        },
    },

    # ------------------------------------------------------------------
    # 模型缺失 / 加载失败
    # ------------------------------------------------------------------
    {
        "error_key": "model_not_found",
        "patterns": [
            r"Cannot find model",
            r"model not found",
            r"Model not found",
            r"No model",
            r"unable to find model",
            r"failed to find model",
            r"模型缺失",
            r"模型未找到",
            r"模型不存在",
            r"找不到模型",
            r"缺少模型",
            r"模型文件未找到",
            r"找不到模型文件",
            r"缺少模型文件",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "模型文件未找到",
                "explanation": "ComfyUI 在 models/ 目录下找不到指定模型文件，可能是路径错误、文件名不一致或模型尚未下载。",
            },
            "en": {
                "title": "Model Not Found",
                "explanation": "ComfyUI could not locate the specified model file under models/. Possible reasons: wrong path, filename mismatch, or model not downloaded.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "根据报错信息确认缺失的模型文件名，将其下载并放入对应的 models/ 子目录（如 checkpoints、unet、vae、loras、controlnet 等）。"),
            ],
            "en": [
                (_vram_always, "Identify the missing model filename from the error message, download it, and place it in the correct models/ subdirectory (checkpoints, unet, vae, loras, controlnet, etc.)."),
            ],
        },
    },
    {
        "error_key": "model_path_error",
        "patterns": [
            r"UnicodeEncodeError",
            r"Non-ASCII",
            r"Too many levels of symbolic links",
            r"symbolic link",
            r"case sensitive",
            r"case-sensitive",
            r"中文路径",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "模型路径异常（中文/空格/大小写/symlink）",
                "explanation": "模型文件路径包含中文、空格，或 Linux 下大小写不匹配、符号链接失效，导致 ComfyUI 无法正确读取。",
            },
            "en": {
                "title": "Model Path Anomaly (Unicode/Space/Case/Symlink)",
                "explanation": "The model file path contains Chinese characters, spaces, or has case mismatch on Linux / broken symlink, preventing ComfyUI from reading it correctly.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "将模型目录与文件路径改为纯英文、无空格、无特殊符号，并检查 Linux 下大小写与符号链接是否有效。"),
            ],
            "en": [
                (_vram_always, "Use pure-English model directory and file paths without spaces or special characters; on Linux also check case sensitivity and symlinks."),
            ],
        },
    },
    {
        "error_key": "checkpoint_loading_failed",
        "patterns": [
            r"invalid model file",
            r"模型文件无效",
            r"无法加载模型",
            r"Error loading checkpoint",
            r"checkpoint loading failed",
            r"Failed to load checkpoint",
            r"Error loading.*checkpoint",
            r"cannot load checkpoint",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "Checkpoint 加载失败",
                "explanation": "模型文件存在但无法被正确读取，可能是文件损坏、格式不兼容（如 Safetensors 与 .ckpt 混用）或 PyTorch 版本不匹配。",
            },
            "en": {
                "title": "Checkpoint Loading Failed",
                "explanation": "The model file exists but cannot be loaded. Possible reasons: file corruption, format mismatch (e.g. Safetensors vs .ckpt), or PyTorch version incompatibility.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "确认报错的 checkpoint/模型文件名，从官方或可信来源重新下载，并用 SHA256 校验和确认文件完整。"),
            ],
            "en": [
                (_vram_always, "Identify the failing checkpoint/model filename, re-download it from an official or trusted source, and verify integrity with SHA256."),
            ],
        },
    },
    {
        "error_key": "state_dict_load_error",
        "patterns": [
            r"Error\(s\) in loading state_dict",
            r"Error in loading state dict",
            r"loading state_dict.*mismatch",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "模型 state_dict 加载失败 / 权重不匹配",
                "explanation": "模型权重结构与当前模型定义不匹配，通常由模型版本错误（如 SD1.5/SDXL/Flux/SD3 混用）、文件损坏、或 LoRA/Checkpoint 与基础模型不兼容导致。",
            },
            "en": {
                "title": "Model state_dict Load Failed / Weight Mismatch",
                "explanation": "The model weight structure does not match the current model definition. Usually caused by mixing model versions (SD1.5/SDXL/Flux/SD3), file corruption, or incompatible LoRA/checkpoint with the base model.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错的模型文件，确认其与工作流中其他模型属于同一架构系列（SD1.5、SDXL、Flux、SD3 等不能混用）。"),
            ],
            "en": [
                (_vram_always, "Check the failing model file and ensure it belongs to the same architecture family as the rest of the workflow (SD1.5, SDXL, Flux, SD3 cannot be mixed)."),
            ],
        },
    },
    {
        "error_key": "git_lfs_pointer_error",
        "patterns": [
            r"version https://git-lfs.github.com/spec/",
            r"oid sha256:",
            r"size \d+",
            r"Git LFS",
            r"git-lfs",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "Git LFS 指针文件 / 模型未实际拉取",
                "explanation": "通过 git clone 获取的模型仓库未启用 git-lfs，本地文件只是文本指针，没有实际二进制内容，导致加载时报 invalid magic number 或文件损坏。",
            },
            "en": {
                "title": "Git LFS Pointer File / Model Not Actually Pulled",
                "explanation": "A model repository obtained via git clone did not enable git-lfs; the local file is only a text pointer without actual binary content, causing invalid magic number or corruption errors.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "安装并启用 git-lfs：git lfs install，然后在模型仓库目录执行 git lfs pull 拉取实际二进制文件。"),
            ],
            "en": [
                (_vram_always, "Install and enable git-lfs: git lfs install, then run git lfs pull in the model repository directory to fetch actual binary files."),
            ],
        },
    },
    {
        "error_key": "invalid_magic_number",
        "patterns": [
            r"invalid magic number",
            r"invalid magic",
            r"RuntimeError: Error loading model",
            r"not a valid checkpoint",
            r"cannot identify image file",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "模型文件损坏或格式错误",
                "explanation": "模型文件不是有效的 .safetensors / .ckpt / .pt 格式，可能下载不完整、文件损坏，或被病毒/网盘同步修改。",
            },
            "en": {
                "title": "Model File Corrupted or Wrong Format",
                "explanation": "The model file is not a valid .safetensors / .ckpt / .pt file. Possible causes: incomplete download, file corruption, or modification by antivirus/cloud sync.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "重新从官方或可信来源下载模型，优先使用 .safetensors 格式，并用 SHA256 校验和确认文件完整。"),
            ],
            "en": [
                (_vram_always, "Re-download the model from an official or trusted source; prefer .safetensors format and verify integrity with SHA256."),
            ],
        },
    },
    {
        "error_key": "lora_weight_error",
        "patterns": [
            r"\blora\b.*weight",
            r"error.*\blora\b",
            r"load.*\blora\b.*fail",
            r"fail.*\blora\b",
            r"lora.*权重",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "LoRA 权重错误",
                "explanation": "加载或应用 LoRA 权重时出错，可能是权重文件损坏、与基础模型不兼容，或 LoRA 名称/键值不匹配。",
            },
            "en": {
                "title": "LoRA Weight Error",
                "explanation": "An error occurred while loading or applying LoRA weights. Possible reasons: corrupted file, incompatibility with the base model, or mismatched LoRA keys.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "确认 LoRA 文件未损坏，并匹配当前基础模型版本（SD1.5 / SDXL / Flux 等）。"),
            ],
            "en": [
                (_vram_always, "Verify the LoRA file is not corrupted and matches the base model version (SD1.5 / SDXL / Flux, etc.)."),
            ],
        },
    },
    {
        "error_key": "controlnet_error",
        "patterns": [
            r"ControlNetError",
            r"error.*\bcontrolnet\b",
            r"fail.*\bcontrolnet\b",
            r"\bcontrolnet\b.*load.*fail",
            r"\bcontrolnet\b.*error",
            r"ControlNetLoader.*fail",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "ControlNet 错误",
                "explanation": "ControlNet 模型加载或应用失败，可能是模型缺失、与基础模型不兼容，或控制图尺寸与生成图不一致。",
            },
            "en": {
                "title": "ControlNet Error",
                "explanation": "ControlNet model loading or application failed. Possible reasons: missing model, incompatibility with base model, or mismatched control/ generation image sizes.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "确认 ControlNet 模型已放入 models/controlnet，且与基础模型版本匹配（SD1.5 / SDXL / Flux）。"),
            ],
            "en": [
                (_vram_always, "Ensure the ControlNet model is placed in models/controlnet and matches the base model version (SD1.5 / SDXL / Flux)."),
            ],
        },
    },
    {
        "error_key": "vae_decode_error",
        "patterns": [
            r"VAE decode",
            r"vae decode",
            r"VAEDecode",
            r"DecodeError",
            r"error.*VAE",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "VAE 解码错误",
                "explanation": "VAE 将潜空间张量解码为图像时失败，常见原因包括 VAE 模型不兼容、分辨率非 64 倍数、或显存不足。",
            },
            "en": {
                "title": "VAE Decode Error",
                "explanation": "The VAE failed to decode latent tensors into an image. Common causes: incompatible VAE model, resolution not a multiple of 64, or insufficient VRAM.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "确保宽度和高度是 64 的整数倍（如 512、768、1024）。"),
            ],
            "en": [
                (_vram_always, "Ensure width and height are multiples of 64 (e.g. 512, 768, 1024)."),
            ],
        },
    },
    {
        "error_key": "model_architecture_mismatch",
        "patterns": [
            r"expected input.*to have.*channels, but got",
            r"Given groups=1, weight of size",
            r"Tensors must have same number of dimensions",
            r"mat1 and mat2 shapes cannot be multiplied",
            r"The size of tensor.*must match.*at non-singleton",
            r"model architecture mismatch",
            r"architecture mismatch",
        ],
        "category": "shape_mismatch",
        "translations": {
            "zh": {
                "title": "模型架构/版本不匹配",
                "explanation": "工作流中混用了不同架构家族的模型（如 SD1.5 / SDXL / Flux / SD3 / ControlNet 版本不匹配），导致张量通道数、维度或矩阵形状无法对齐。",
            },
            "en": {
                "title": "Model Architecture / Version Mismatch",
                "explanation": "The workflow mixes models from different architecture families (e.g. SD1.5 / SDXL / Flux / SD3 / mismatched ControlNet versions), causing channel counts, dimensions, or matrix shapes to misalign.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "确保 Checkpoint、VAE、LoRA、ControlNet、IPAdapter 全部来自同一模型家族（SD1.5/SDXL/Flux/SD3 不可混用）。"),
            ],
            "en": [
                (_vram_always, "Ensure checkpoint, VAE, LoRA, ControlNet, and IPAdapter all belong to the same model family (SD1.5/SDXL/Flux/SD3 cannot be mixed)."),
            ],
        },
    },
    {
        "error_key": "black_or_noisy_output",
        "patterns": [
            r"black image",
            r"black output",
            r"noise output",
            r"noisy output",
            r"图像全黑",
            r"输出全黑",
            r"黑图",
            r"噪点",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "生成结果全黑或全是噪点",
                "explanation": "采样完成后图像为纯黑或噪点，通常由 VAE 不兼容、模型损坏、FP16 精度溢出、CFG 过高或空 Latent 尺寸错误导致。",
            },
            "en": {
                "title": "Generated Image is Black or Noisy",
                "explanation": "The output after sampling is pure black or noise. Common causes: incompatible VAE, corrupted model, FP16 precision overflow, excessive CFG, or wrong empty latent size.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "更换与基础模型匹配的 VAE（Flux 用 ae.safetensors，SD1.5/SDXL 用对应 VAE）。"),
            ],
            "en": [
                (_vram_always, "Use a VAE matching the base model (Flux uses ae.safetensors; SD1.5/SDXL use their own VAEs)."),
            ],
        },
    },

    # ------------------------------------------------------------------
    # 张量/数据类型/设备不匹配
    # ------------------------------------------------------------------
    {
        "error_key": "device_mismatch",
        "patterns": [
            r"Expected all tensors to be on the same device",
            r"Expected object of device type",
            r"must be on the same device",
            r"Tensor.*device.*cuda.*cpu",
        ],
        "category": "device_mismatch",
        "translations": {
            "zh": {
                "title": "张量设备不一致",
                "explanation": "部分张量在 CPU，部分在 GPU，导致 PyTorch 无法执行运算。通常由节点内部未统一设备或手动指定 device 引起。",
            },
            "en": {
                "title": "Tensor Device Mismatch",
                "explanation": "Some tensors are on CPU while others are on GPU, so PyTorch cannot perform the operation. Usually caused by nodes not unifying devices or manual device assignments.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错节点及其上游节点，确保输入张量都在同一设备（CPU 或 CUDA）。"),
            ],
            "en": [
                (_vram_always, "Check the failing node and its upstream nodes; ensure inputs are on the same device (CPU or CUDA)."),
            ],
        },
    },
    {
        "error_key": "dtype_mismatch",
        "patterns": [
            r"Expected.*dtype",
            r"dtype mismatch",
            r"input types.*not match",
            r"found dtype",
            r"expected.*Float.*Half",
            r"expected.*Half.*Float",
        ],
        "category": "dtype_mismatch",
        "translations": {
            "zh": {
                "title": "数据类型不匹配",
                "explanation": "模型或张量的数据类型不一致（如 FP32 与 FP16 混用），导致运算无法执行。",
            },
            "en": {
                "title": "Data Type Mismatch",
                "explanation": "The model or tensors have inconsistent data types (e.g. FP32 mixed with FP16), so the operation cannot be executed.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "在模型加载节点中统一使用 fp16/fp32，不要混用。"),
            ],
            "en": [
                (_vram_always, "Use a consistent dtype (fp16/fp32) in model loader nodes; do not mix them."),
            ],
        },
    },
    {
        "error_key": "shape_mismatch",
        "patterns": [
            r"shape mismatch",
            r"size mismatch",
            r"RuntimeError: The size of tensor",
            r"mat1 and mat2 shapes",
            r"Shape.*mismatch",
            r"张量维度不匹配",
            r"维度不匹配",
            r"形状不匹配",
        ],
        "category": "shape_mismatch",
        "translations": {
            "zh": {
                "title": "张量维度不匹配",
                "explanation": "两个张量的维度无法对齐（如矩阵乘法形状错误、通道数不一致），通常由模型版本与输入尺寸不兼容导致。",
            },
            "en": {
                "title": "Tensor Shape Mismatch",
                "explanation": "Two tensors cannot be aligned (e.g. wrong matrix multiplication shapes or channel counts). Usually caused by model version incompatibility with input size.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查模型版本是否与工作流匹配，确保宽度和高度是 64 的整数倍，且所有输入图像/潜空间张量的通道数、宽高一致。"),
            ],
            "en": [
                (_vram_always, "Check that the model version matches the workflow; ensure width and height are multiples of 64 and all input image/latent tensors have consistent channels, width, and height."),
            ],
        },
    },
    {
        "error_key": "nan_error",
        "patterns": [
            r"produced NaN",
            r"\bNaN\b",
            r"NaN detected",
            r"invalid value.*NaN",
        ],
        "category": "dtype_mismatch",
        "translations": {
            "zh": {
                "title": "生成结果出现 NaN / 无效值",
                "explanation": "采样过程中出现非数字（NaN）或无效值，通常由模型损坏、VAE 不兼容、CFG 过高或数值溢出导致。",
            },
            "en": {
                "title": "NaN / Invalid Value Detected",
                "explanation": "Non-numeric (NaN) or invalid values appeared during sampling. Common causes: corrupted model, incompatible VAE, excessive CFG scale, or numerical overflow.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "降低 CFG Scale（建议 7~9），避免数值溢出。"),
            ],
            "en": [
                (_vram_always, "Lower CFG Scale (recommended 7~9) to avoid numerical overflow."),
            ],
        },
    },

    # ------------------------------------------------------------------
    # 节点缺失 / Python 异常
    # ------------------------------------------------------------------
    {
        "error_key": "node_not_found",
        "patterns": [
            r"Cannot find node class",
            r"Node not found",
            r"Node type.*not found",
            r"Node type.*does not exist",
            r"No node class named",
            r"Unknown node type",
            r"Node class.*not found",
            r"节点缺失",
            r"节点未找到",
            r"找不到节点",
            r"缺少节点",
            r"未知节点类型",
            r"无法找到节点",
            r"节点.*不存在",
            r"节点.*未注册",
            r"custom node.*missing",
            r"custom node.*not installed",
            r"was-node-list-create",
            r"节点类型未找到",
            r"missing_node_type",
            r"custom node may not be installed",
            r"The custom node may not be installed",
        ],
        "category": "node_not_found",
        "translations": {
            "zh": {
                "title": "节点类型未找到",
                "explanation": "工作流中使用了当前 ComfyUI 环境未安装的自定义节点，节点类无法被注册。",
            },
            "en": {
                "title": "Node Type Not Found",
                "explanation": "The workflow uses a custom node that is not installed in the current ComfyUI environment; the node class cannot be registered.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "根据报错信息找到缺失的节点类型名，在 ComfyUI Manager 的“安装缺失节点”中搜索并安装对应节点包，然后完全重启 ComfyUI。"),
            ],
            "en": [
                (_vram_always, "Identify the missing node type name from the error message, then search for and install the corresponding node package via ComfyUI Manager's 'Install Missing Nodes', and fully restart ComfyUI."),
            ],
        },
    },
    {
        "error_key": "node_execution_error",
        "patterns": [
            r"\bPrompt execution failed\b",
            r"Execution error in node",
            r"executed with errors",
            r"节点.*执行错误",
            r"节点执行失败",
            r"Error running node",
        ],
        "category": "execution_error",
        "translations": {
            "zh": {
                "title": "节点执行错误",
                "explanation": "某个节点在执行过程中抛出异常，可能由无效输入、损坏的模型文件或节点内部 bug 导致。",
            },
            "en": {
                "title": "Node Execution Error",
                "explanation": "A node threw an exception during execution. Possible causes: invalid inputs, corrupted model files, or an internal bug in the node.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错节点的输入参数和连线是否正确，确保所有必填输入已连接到有效来源。"),
            ],
            "en": [
                (_vram_always, "Check the inputs and connections of the failing node; ensure all required inputs are connected to valid sources."),
            ],
        },
    },
    {
        "error_key": "import_error",
        "patterns": [
            r"ImportError",
            r"ModuleNotFoundError",
            r"No module named",
            r"cannot import name",
        ],
        "category": "import_error",
        "translations": {
            "zh": {
                "title": "Python 模块导入失败",
                "explanation": "自定义节点或 ComfyUI 依赖的 Python 模块缺失或版本不兼容，导致导入失败。",
            },
            "en": {
                "title": "Python Import Error",
                "explanation": "A custom node or ComfyUI dependency is missing or has an incompatible version, causing the import to fail.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "根据报错中的模块名执行 pip install <模块名>。"),
            ],
            "en": [
                (_vram_always, "Run pip install <module_name> according to the missing module in the error."),
            ],
        },
    },
    {
        "error_key": "key_error",
        "patterns": [
            r"KeyError",
            r"key.*not found",
        ],
        "category": "import_error",
        "translations": {
            "zh": {
                "title": "字典键错误 (KeyError)",
                "explanation": "代码访问了不存在的字典键，通常由节点输入参数缺失、工作流版本不兼容或节点内部 bug 导致。",
            },
            "en": {
                "title": "KeyError",
                "explanation": "The code accessed a dictionary key that does not exist. Usually caused by missing node inputs, incompatible workflow versions, or internal node bugs.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错节点是否缺少必填输入（红色边框或空插槽），并重新拖拽一个新节点替换旧节点、重新连接所有输入。"),
            ],
            "en": [
                (_vram_always, "Check whether the failing node is missing required inputs (red border or empty slot), replace it with a fresh one, and reconnect all inputs."),
            ],
        },
    },
    {
        "error_key": "attribute_error",
        "patterns": [
            r"AttributeError",
            r"has no attribute",
        ],
        "category": "import_error",
        "translations": {
            "zh": {
                "title": "属性错误 (AttributeError)",
                "explanation": "代码访问了对象不存在的属性或方法，通常由节点版本与 ComfyUI 核心 API 不兼容导致。",
            },
            "en": {
                "title": "AttributeError",
                "explanation": "The code accessed an attribute or method that does not exist on the object. Usually caused by node version incompatibility with the ComfyUI core API.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "更新报错的自定义节点到最新版本，以适配当前 ComfyUI API。"),
            ],
            "en": [
                (_vram_always, "Update the failing custom node to the latest version to match the current ComfyUI API."),
            ],
        },
    },
    {
        "error_key": "file_not_found_error",
        "patterns": [
            r"FileNotFoundError",
            r"No such file or directory",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "文件未找到 (FileNotFoundError)",
                "explanation": "程序尝试读取的文件或目录不存在，可能是路径配置错误、文件被移动或删除。",
            },
            "en": {
                "title": "File Not Found",
                "explanation": "The program tried to read a file or directory that does not exist. Possible reasons: wrong path configuration, or the file was moved/deleted.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "根据报错中的路径，确认文件或目录是否存在。"),
            ],
            "en": [
                (_vram_always, "Confirm that the file or directory in the error path exists."),
            ],
        },
    },
    {
        "error_key": "permission_error",
        "patterns": [
            r"PermissionError",
            r"Permission denied",
            r"Access is denied",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "权限不足 (PermissionError)",
                "explanation": "ComfyUI 进程没有读取/写入目标文件或目录的权限，常见于模型目录、输出目录或系统日志路径。",
            },
            "en": {
                "title": "Permission Denied",
                "explanation": "The ComfyUI process lacks permission to read/write the target file or directory. Common locations: model directories, output folders, or system log paths.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查报错路径的文件权限，确保 ComfyUI 进程有读写权限。"),
            ],
            "en": [
                (_vram_always, "Check file permissions for the path in the error and ensure the ComfyUI process can read/write it."),
            ],
        },
    },
    {
        "error_key": "bus_error",
        "patterns": [
            r"Bus error",
            r"SIGBUS",
            r"BusError",
        ],
        "category": "device_mismatch",
        "translations": {
            "zh": {
                "title": "总线错误 (Bus Error)",
                "explanation": "底层硬件/驱动出现严重错误，可能由损坏的模型文件、内存故障、驱动 bug 或硬件过热导致。",
            },
            "en": {
                "title": "Bus Error",
                "explanation": "A low-level hardware/driver error occurred. Possible causes: corrupted model file, memory fault, driver bug, or hardware overheating.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "立即检查模型文件完整性，重新下载或校验 SHA256。"),
            ],
            "en": [
                (_vram_always, "Immediately verify model file integrity; re-download or check SHA256."),
            ],
        },
    },
    {
        "error_key": "connection_error",
        "patterns": [
            # 仅命中明确的网络/下载/连接错误，避免把任意 Timeout 或模型加载错误误分类。
            r"\bConnectionError\b",
            r"\bConnection refused\b",
            r"\bConnection reset\b",
            r"\bConnection timed out\b",
            r"\bconnection failed\b.*\b(?:network|socket|http|https|urlopen|websocket|download)\b",
            r"\b(?:network|socket|http|https|urlopen|websocket|download)\b.*\bconnection failed\b",
            r"\bconnection broken\b",
            r"连接失败",
            r"\bConnectTimeout\b",
            r"\bReadTimeout\b",
            r"\bHTTPError\b",
            r"\bURLError\b",
            r"\burlopen error\b",
            r"\bFailed to establish a new connection\b",
            r"\bName or service not known\b",
            r"\bgetaddrinfo failed\b",
            r"\bTemporary failure in name resolution\b",
            r"\b(?:download|fetch|request).*(?:huggingface\.co|github\.com|civitai)",
            r"\b(?:huggingface\.co|github\.com|civitai).*(?:download|fetch|request|timeout|failed)",
            r"下载失败",
            r"下载超时",
            r"网络错误",
        ],
        "category": "connection_error",
        "translations": {
            "zh": {
                "title": "网络连接错误",
                "explanation": "下载模型、访问 API 或连接外部服务时失败，可能是网络不通、代理配置错误或目标服务不可用。",
            },
            "en": {
                "title": "Connection Error",
                "explanation": "Failed to download a model, access an API, or connect to an external service. Possible reasons: network unavailable, proxy misconfiguration, or target service down.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查网络连接，确认可访问 huggingface.co、github.com 等目标地址。"),
            ],
            "en": [
                (_vram_always, "Check network connectivity to target addresses such as huggingface.co and github.com."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # WSL2 localhost 转发 / Windows 防火墙 / Docker 网络问题
    # ------------------------------------------------------------------
    {
        "error_key": "wsl_localhost_firewall_error",
        "patterns": [
            r"WSL",
            r"wsl",
            r"localhost.*refused",
            r"127\\.0\\.0\\.1.*refused",
            r"无法访问.*localhost",
            r"Windows.*firewall",
            r"firewall.*block",
            r"连接被拒绝",
        ],
        "category": "connection_error",
        "translations": {
            "zh": {
                "title": "WSL2 localhost 转发 / Windows 防火墙拦截",
                "explanation": "在 WSL2 内启动 ComfyUI 后，Windows 浏览器无法通过 localhost/127.0.0.1 访问，可能是 WSL2 网络转发未生效或 Windows 防火墙拦截。",
            },
            "en": {
                "title": "WSL2 localhost Forwarding / Windows Firewall Blocked",
                "explanation": "ComfyUI started inside WSL2 cannot be accessed via localhost/127.0.0.1 from Windows browser, likely due to WSL2 network forwarding or Windows Firewall.",
            },
        },
        "suggestions": {
            "zh": [
                (_plat_windows, "WSL2：启动 ComfyUI 时使用 --listen 0.0.0.0，例如 cd /mnt/... && python main.py --listen 0.0.0.0 --port 8188。"),
            ],
            "en": [
                (_plat_windows, "WSL2: launch ComfyUI with --listen 0.0.0.0, e.g. cd /mnt/... && python main.py --listen 0.0.0.0 --port 8188."),
            ],
        },
    },
    {
        "error_key": "safetensors_rust_error",
        "patterns": [
            r"SafetensorError",
            r"safetensors_rust",
            r"Error while deserializing header",
            r"Safetensors header is too small",
            r"invalid metadata",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "Safetensors / Rust 解析错误",
                "explanation": "加载 .safetensors 模型时解析头部或 metadata 失败，通常是文件损坏、下载不完整或 safetensors/rust 后端异常。",
            },
            "en": {
                "title": "Safetensors / Rust Parse Error",
                "explanation": "Failed to parse the header or metadata of a .safetensors model. Usually caused by file corruption, incomplete download, or a safetensors/rust backend issue.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "重新下载模型文件，并用 SHA256 校验和确认文件完整。"),
            ],
            "en": [
                (_vram_always, "Re-download the model and verify integrity with a SHA256 checksum."),
            ],
        },
    },
    {
        "error_key": "torch_compile_error",
        "patterns": [
            r"torch\._dynamo",
            r"torch\._inductor",
            r"InductorError",
            r"BackendCompilerFailed",
            r"dynamo.*compile",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "Torch Dynamo / Inductor 编译失败",
                "explanation": "torch.compile / torch._dynamo / inductor 在编译或优化计算图时失败，可能由 Python 版本、CUDA 版本或自定义算子不兼容导致。",
            },
            "en": {
                "title": "Torch Dynamo / Inductor Compile Error",
                "explanation": "torch.compile / torch._dynamo / inductor failed during graph compilation or optimization. Common causes: incompatible Python/CUDA versions or unsupported custom operators.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "临时关闭 torch.compile：设置环境变量 TORCH_COMPILE_BACKEND=eager 或移除代码中的 @torch.compile 装饰。"),
            ],
            "en": [
                (_vram_always, "Disable torch.compile temporarily: set TORCH_COMPILE_BACKEND=eager or remove @torch.compile decorators."),
            ],
        },
    },
    {
        "error_key": "cuda_kernel_image_mismatch",
        "patterns": [
            r"no kernel image is available for execution on the device",
            r"no kernel image",
            r"kernel image",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "CUDA 内核架构不匹配",
                "explanation": "当前 PyTorch/CUDA 编译的 GPU 计算架构（sm_xxx）与显卡实际架构不一致，导致 CUDA 内核无法在设备上执行。常见于显卡太新或太旧、安装了错误架构的 PyTorch wheel。",
            },
            "en": {
                "title": "CUDA Kernel Architecture Mismatch",
                "explanation": "The GPU compute architecture (sm_xxx) that PyTorch/CUDA was compiled for does not match your GPU's actual architecture, so the CUDA kernel cannot execute on the device. Common when the GPU is too new or too old, or the wrong PyTorch wheel was installed.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "执行 python -c \"import torch; print(torch.version.cuda); print(torch.cuda.get_device_capability())\"，确认 PyTorch wheel 的 CUDA 架构覆盖你的 GPU。"),
            ],
            "en": [
                (_vram_always, "Run python -c \"import torch; print(torch.version.cuda); print(torch.cuda.get_device_capability())\" and ensure the wheel's CUDA arch covers your GPU."),
            ],
        },
    },
    {
        "error_key": "cuda_error",
        "patterns": [
            r"CUDA error",
            r"CUDA runtime error",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "CUDA 运行错误",
                "explanation": "CUDA 运行时出现错误，可能由 CUDA 版本与 PyTorch 不兼容、内核执行异常或显卡驱动问题导致。",
            },
            "en": {
                "title": "CUDA Runtime Error",
                "explanation": "A CUDA runtime error occurred. Possible causes: CUDA version incompatible with PyTorch, kernel execution exception, or GPU driver issue.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查 PyTorch 是否为对应 CUDA 版本的 wheel：pip list | grep torch 并核对 torch.version.cuda。"),
            ],
            "en": [
                (_vram_always, "Check whether PyTorch is a CUDA-matching wheel: pip list | grep torch and verify torch.version.cuda."),
            ],
        },
    },
    {
        "error_key": "xformers_error",
        "patterns": [
            r"xformers",
            r"xFormers",
            r"Xformers",
            r"attention.*xformers",
            r"No module named ['\"]xformers['\"]",
        ],
        "category": "import_error",
        "translations": {
            "zh": {
                "title": "xFormers Attention 错误",
                "explanation": "xFormers 加速注意力模块未安装、版本与 PyTorch/CUDA 不匹配，或运行时构建失败。",
            },
            "en": {
                "title": "xFormers Attention Error",
                "explanation": "The xFormers attention module is not installed, its version mismatches PyTorch/CUDA, or it failed to build at runtime.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "执行 pip install xformers --upgrade 前，先确认 torch 与 CUDA 版本匹配。"),
            ],
            "en": [
                (_vram_always, "Before running pip install xformers --upgrade, confirm torch and CUDA versions match."),
            ],
        },
    },
    {
        "error_key": "pipeline_config_error",
        "patterns": [
            r"config\.json",
            r"pipeline.*config",
            r"Configuration file.*not found",
            r"diffusers.*config",
            r"model_index\.json",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "Diffusers Pipeline 配置缺失",
                "explanation": "diffusers Pipeline 所需的 config.json、model_index.json 等配置文件缺失，导致无法构造 pipeline。",
            },
            "en": {
                "title": "Diffusers Pipeline Config Missing",
                "explanation": "The diffusers Pipeline requires config.json, model_index.json, or similar config files that are missing, so the pipeline cannot be constructed.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "确认模型目录包含 config.json、model_index.json 等完整 diffusers 结构。"),
            ],
            "en": [
                (_vram_always, "Ensure the model directory contains the full diffusers structure including config.json and model_index.json."),
            ],
        },
    },
    {
        "error_key": "clip_vision_error",
        "patterns": [
            r"CLIPVision",
            r"CLIPVisionModel",
            r"clip_vision",
            r"clip vision",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "CLIPVision 模型加载失败",
                "explanation": "加载 CLIPVision 视觉编码器失败，可能是模型文件缺失、格式不兼容或路径错误。",
            },
            "en": {
                "title": "CLIPVision Model Load Failed",
                "explanation": "Failed to load the CLIPVision visual encoder. Possible reasons: missing model file, incompatible format, or wrong path.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "将 CLIPVision 模型（如 clip_vision_g.safetensors）放入 models/clip_vision/ 目录。"),
            ],
            "en": [
                (_vram_always, "Place the CLIPVision model (e.g. clip_vision_g.safetensors) in models/clip_vision/."),
            ],
        },
    },
    {
        "error_key": "unet_load_error",
        "patterns": [
            r"UNet",
            r"unet.*load",
            r"DiffusionUNet",
            r"UNet2DConditionModel",
            r"loading unet",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "UNet 模型加载失败",
                "explanation": "加载 UNet 去噪网络失败，可能是文件损坏、格式不兼容、路径错误或显存不足。",
            },
            "en": {
                "title": "UNet Model Load Failed",
                "explanation": "Failed to load the UNet denoising network. Possible reasons: corrupted file, incompatible format, wrong path, or insufficient VRAM.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "确认 UNet 文件路径与节点选择的模型名称一致；如为 diffusers 格式，确保 config.json 与权重文件配套。"),
            ],
            "en": [
                (_vram_always, "Confirm the UNet file path matches the model selected in the node; for diffusers format, ensure config.json accompanies the weight files."),
            ],
        },
    },
    {
        "error_key": "tokenizer_error",
        "patterns": [
            r"tokenizer",
            r"vocab\.json",
            r"merges\.txt",
            r"Tokenizer",
            r"tokenizer_config",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "Tokenizer 加载失败",
                "explanation": "加载文本 tokenizer（vocab.json、merges.txt、tokenizer_config.json 等）失败，导致 prompt 无法编码。",
            },
            "en": {
                "title": "Tokenizer Load Failed",
                "explanation": "Failed to load the text tokenizer (vocab.json, merges.txt, tokenizer_config.json, etc.), so prompts cannot be encoded.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "确认模型目录包含 vocab.json、merges.txt、tokenizer_config.json 等完整 tokenizer 文件。"),
            ],
            "en": [
                (_vram_always, "Ensure the model directory contains the full tokenizer files: vocab.json, merges.txt, tokenizer_config.json."),
            ],
        },
    },
    {
        "error_key": "ffmpeg_error",
        "patterns": [
            r"ffmpeg",
            r"FFmpeg",
            r"ffprobe",
            r"VideoReader",
            r"imageio_ffmpeg",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "FFmpeg 视频处理错误",
                "explanation": "视频节点调用 FFmpeg / ffprobe 失败，可能是未安装、未加入 PATH、编码器不支持或输入视频损坏。",
            },
            "en": {
                "title": "FFmpeg Video Processing Error",
                "explanation": "A video node failed to call FFmpeg / ffprobe. Possible reasons: not installed, not in PATH, unsupported codec, or corrupted input video.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "在系统 PATH 中安装 FFmpeg 与 ffprobe，并重启 ComfyUI 终端。"),
            ],
            "en": [
                (_vram_always, "Install FFmpeg and ffprobe on your system PATH and restart the ComfyUI terminal."),
            ],
        },
    },
    {
        "error_key": "websocket_timeout",
        "patterns": [
            r"WebSocket.*timeout",
            r"websocket.*timeout",
            r"WS connection.*timed out",
            r"WebSocketTimeout",
            r"WebSocket connection",
        ],
        "category": "connection_error",
        "translations": {
            "zh": {
                "title": "WebSocket 连接超时",
                "explanation": "浏览器/前端与 ComfyUI 后端的 WebSocket 连接超时或断开，可能由网络不稳定、代理/防火墙或队列任务执行过久导致。",
            },
            "en": {
                "title": "WebSocket Connection Timeout",
                "explanation": "The WebSocket connection between the browser/frontend and ComfyUI backend timed out or disconnected. Possible reasons: unstable network, proxy/firewall, or a queued task taking too long.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "刷新浏览器页面，ComfyUI 通常会自动重建 WebSocket 连接。"),
            ],
            "en": [
                (_vram_always, "Refresh the browser page; ComfyUI usually reconnects the WebSocket automatically."),
            ],
        },
    },
    {
        "error_key": "model_hash_mismatch",
        "patterns": [
            r"hash mismatch",
            r"HASH MISMATCH",
            r"model hash",
            r"SHA256 mismatch",
            r"checksum.*mismatch",
        ],
        "category": "model_missing",
        "translations": {
            "zh": {
                "title": "模型哈希不匹配",
                "explanation": "模型文件的哈希/校验和与预期不一致，说明文件在下载或传输过程中损坏，或被替换。",
            },
            "en": {
                "title": "Model Hash Mismatch",
                "explanation": "The model file hash/checksum does not match the expected value, indicating corruption during download/transfer or a replaced file.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "重新从官方或可信来源下载模型，并使用 SHA256 校验和核对。"),
            ],
            "en": [
                (_vram_always, "Re-download the model from an official or trusted source and verify with SHA256."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # 插件/节点包加载失败（启动阶段常见）
    # ------------------------------------------------------------------
    {
        "error_key": "plugin_load_failed",
        "patterns": [
            r"failed to load ComfyUI_",
            r"failed to load.*custom_nodes",
            r"FETCH ComfyRegistry Data",
            r"ComfyRegistry",
            r"ComfyRegistry.*timeout",
            r"ComfyRegistry.*stall",
            r"registry.*load.*fail",
            r"节点注册失败",
            r"插件加载失败",
            r"custom node.*failed to load",
            r"Error loading custom node",
            r"Could not load.*custom node",
            r"IMPORT FAILED",
            r"Import failed",
            r"import failed",
            r"Loading of custom node.*failed",
            r"Failed to load.*node",
            r"custom_node.*import",
            r"Cannot import.*custom",
            r"ComfyUI_IPAdapter_plus",
            r"ComfyUI-IPAdapter-Plus",
            r"IPAdapter_plus",
        ],
        "category": "import_error",
        "translations": {
            "zh": {
                "title": "自定义节点/插件加载失败",
                "explanation": "ComfyUI 启动时某个自定义节点包（如 IPAdapter_plus、Manager 等）加载失败，或 ComfyRegistry 拉取卡顿导致节点注册异常。通常由依赖冲突、版本不兼容、网络阻塞或插件目录损坏引起。",
            },
            "en": {
                "title": "Custom Node / Plugin Load Failed",
                "explanation": "A custom node package (e.g. IPAdapter_plus, Manager) failed to load during ComfyUI startup, or ComfyRegistry fetching stalled causing node registration issues. Usually caused by dependency conflicts, version incompatibility, network blockage, or corrupted plugin directory.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "查看启动日志中该节点包的具体 ImportError / ModuleNotFoundError，按缺失模块名 pip install 或安装 requirements.txt。"),
            ],
            "en": [
                (_vram_always, "Check the startup log for the specific ImportError / ModuleNotFoundError of the failing package, then pip install the missing module or its requirements.txt."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # 端口占用 / 启动网络错误
    # ------------------------------------------------------------------
    {
        "error_key": "port_in_use",
        "patterns": [
            r"Address already in use",
            r"OSError:\s*\[Errno 98\]",
            r"Port.*already in use",
            r"端口.*占用",
            r"端口.*被占用",
            r"Address in use",
            r"Permission denied.*port",
        ],
        "category": "connection_error",
        "translations": {
            "zh": {
                "title": "ComfyUI 端口被占用",
                "explanation": "ComfyUI 默认端口（通常是 8188）已被其他进程占用，或启动时权限不足，导致服务无法启动。",
            },
            "en": {
                "title": "ComfyUI Port Already in Use",
                "explanation": "The ComfyUI default port (usually 8188) is already used by another process, or the launch lacks permission to bind the port.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "关闭占用该端口的其他进程，或在启动参数中指定其他端口如 --port 8189。"),
            ],
            "en": [
                (_vram_always, "Close the other process using this port, or specify a different port in launch args such as --port 8189."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # Visual C++ Redistributable 缺失（Windows DLL 加载失败）
    # ------------------------------------------------------------------
    {
        "error_key": "visual_cpp_redistributable_missing",
        "patterns": [
            r"VCRUNTIME140",
            r"MSVCP140",
            r"api-ms-win-crt-runtime",
            r"api-ms-win-crt-heap",
            r"The code execution cannot proceed because",
            r"Visual C\\+\\+ Redistributable",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "Visual C++ Redistributable 缺失",
                "explanation": "Windows 系统缺少 PyTorch / CUDA 等库依赖的 Visual C++ Redistributable，导致 DLL 加载失败。",
            },
            "en": {
                "title": "Visual C++ Redistributable Missing",
                "explanation": "The Windows system lacks the Visual C++ Redistributable required by PyTorch / CUDA libraries, causing DLL load failures.",
            },
        },
        "suggestions": {
            "zh": [
                (_plat_windows, "Windows：从微软官网下载并安装最新版 Visual C++ Redistributable（x64）：https://aka.ms/vs/17/release/vc_redist.x64.exe"),
            ],
            "en": [
                (_plat_windows, "Windows: download and install the latest Visual C++ Redistributable (x64) from Microsoft: https://aka.ms/vs/17/release/vc_redist.x64.exe"),
            ],
        },
    },
    # ------------------------------------------------------------------
    # 共享库 / LD_LIBRARY_PATH / CUDA 运行时找不到
    # ------------------------------------------------------------------
    {
        "error_key": "shared_library_error",
        "patterns": [
            r"cannot open shared object",
            r"No such file or directory.*lib",
            r"lib.*\.so.*not found",
            r"libcudart",
            r"libcudnn",
            r"libtorch",
            r"LD_LIBRARY_PATH",
            r"error while loading shared libraries",
            r"找不到.*dll",
            r"dll.*not found",
            r"The specified module could not be found",
            r"VCRUNTIME",
            r"MSVCP",
            r"msvcr",
            r"vcomp",
            r"api-ms-win-crt",
            r"Visual C\+\+ Redistributable",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "共享库/CUDA 运行时找不到",
                "explanation": "系统或 PyTorch 无法找到所需的动态链接库（.so / .dll），常见原因包括 LD_LIBRARY_PATH 未设置、CUDA/cuDNN 库缺失、或 Windows 环境 PATH 不正确。",
            },
            "en": {
                "title": "Shared Library / CUDA Runtime Not Found",
                "explanation": "The system or PyTorch cannot find required dynamic libraries (.so / .dll). Common causes: LD_LIBRARY_PATH not set, missing CUDA/cuDNN libraries, or incorrect PATH on Windows.",
            },
        },
        "suggestions": {
            "zh": [
                (_plat_windows, "Windows：安装最新 Visual C++ Redistributable (x64)；将 CUDA 安装目录的 bin 文件夹加入系统 PATH；缺失的 .dll 可从 NVIDIA CUDA/cuDNN 目录复制到 ComfyUI 根目录。"),
            ],
            "en": [
                (_plat_windows, "Windows: install the latest Visual C++ Redistributable (x64); add the CUDA installation bin folder to system PATH; copy missing .dll files from NVIDIA CUDA/cuDNN folder to the ComfyUI root."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # 网络/连接类细化（WebSocket 持续重连、SSL、镜像下载失败）
    # ------------------------------------------------------------------
    {
        "error_key": "websocket_reconnecting",
        "patterns": [
            r"reconnecting",
            r"reconnect",
            r"Lost connection to server",
            r"Connection closed",
            r"WebSocket connection failed",
            r"WebSocket.*closed",
            r"ws.*closed",
            r"无法连接到服务器",
            r"连接服务器失败",
            r"连接已断开",
            r"与服务器的连接",
        ],
        "category": "connection_error",
        "translations": {
            "zh": {
                "title": "前端与 ComfyUI 服务器断开/持续重连",
                "explanation": "浏览器无法稳定连接到 ComfyUI 后端 WebSocket，页面反复显示重连。常见原因：ComfyUI 进程已退出、端口被占用、代理/防火墙拦截、Nginx 反向代理超时设置过短。",
            },
            "en": {
                "title": "Frontend Disconnected / Keep Reconnecting to ComfyUI Server",
                "explanation": "The browser cannot maintain a stable WebSocket connection to the ComfyUI backend and keeps reconnecting. Common causes: ComfyUI process exited, port conflict, proxy/firewall blocking, or Nginx reverse proxy timeout too short.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "先查看 ComfyUI 终端是否仍在运行，有无报错导致进程退出；刷新浏览器页面或清除缓存后重新打开。"),
            ],
            "en": [
                (_vram_always, "First check whether the ComfyUI terminal is still running and if any error caused it to exit; refresh the browser page or clear cache and reopen."),
            ],
        },
    },
    {
        "error_key": "ssl_certificate_error",
        "patterns": [
            r"SSL certificate verify failed",
            r"CERTIFICATE_VERIFY_FAILED",
            r"certificate verify failed",
            r"SSL: CERTIFICATE_VERIFY_FAILED",
            r"unable to get local issuer certificate",
            r"SSL handshake failed",
        ],
        "category": "connection_error",
        "translations": {
            "zh": {
                "title": "SSL / 证书验证失败",
                "explanation": "下载模型或访问 API 时 SSL 证书验证失败，常见于公司/校园网络中间人攻击、系统时间错误、或 Python 未安装 certifi 根证书。",
            },
            "en": {
                "title": "SSL / Certificate Verification Failed",
                "explanation": "SSL certificate verification failed while downloading models or accessing APIs. Common causes: corporate/campus network MITM, wrong system time, or Python missing certifi root certificates.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查系统时间是否正确，错误的系统时间会导致证书验证失败；更新 Python 证书包：pip install --upgrade certifi"),
            ],
            "en": [
                (_vram_always, "Check that the system time is correct; incorrect time causes certificate verification failures. Update Python certificates: pip install --upgrade certifi"),
            ],
        },
    },
    # ------------------------------------------------------------------
    # 环境与依赖安装失败
    # ------------------------------------------------------------------
    {
        "error_key": "pip_install_failed",
        "patterns": [
            r"pip install failed",
            r"Could not find a version that satisfies",
            r"metadata-generation-failed",
            r"error: subprocess-exited-with-error",
            r"Failed to build.*wheel",
            r"No matching distribution found",
            r"pip.*error",
            r"安装依赖失败",
            r"requirements\.txt.*失败",
        ],
        "category": "import_error",
        "translations": {
            "zh": {
                "title": "pip / 依赖安装失败",
                "explanation": "安装节点包依赖时 pip 报错，可能是 Python 版本不兼容、网络被墙、wheel 构建环境缺失，或 requirements.txt 中的包版本冲突。",
            },
            "en": {
                "title": "pip / Dependency Installation Failed",
                "explanation": "pip failed while installing node package dependencies. Possible causes: incompatible Python version, network blockage, missing wheel build environment, or version conflicts in requirements.txt.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "先升级 pip：python -m pip install --upgrade pip；如提示 Could not find a version，检查 Python 版本（推荐 3.10~3.12）并确认 PyTorch 与 CUDA 版本匹配。"),
            ],
            "en": [
                (_vram_always, "Upgrade pip first: python -m pip install --upgrade pip. If you see 'Could not find a version', check Python version (recommended 3.10~3.12) and PyTorch/CUDA compatibility."),
            ],
        },
    },
    {
        "error_key": "python_version_incompatible",
        "patterns": [
            r"requires Python",
            r"Python version.*required",
            r"Unsupported Python",
            r"python_requires",
            r"requires.*python",
            r"SyntaxError",
            r"invalid syntax",
        ],
        "category": "import_error",
        "translations": {
            "zh": {
                "title": "Python 版本不兼容 / SyntaxError",
                "explanation": "当前 Python 版本与节点包或依赖要求的版本不符，或代码使用了不支持的语法。ComfyUI 官方推荐 Python 3.10~3.12。",
            },
            "en": {
                "title": "Python Version Incompatible / SyntaxError",
                "explanation": "The current Python version does not match what a node package or dependency requires, or the code uses unsupported syntax. ComfyUI officially recommends Python 3.10~3.12.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查当前 Python 版本：python --version；ComfyUI 官方推荐 Python 3.10~3.12。"),
            ],
            "en": [
                (_vram_always, "Check current Python version: python --version. ComfyUI officially recommends Python 3.10~3.12."),
            ],
        },
    },
    {
        "error_key": "transformers_diffusers_version_error",
        "patterns": [
            r"transformers.*version",
            r"diffusers.*version",
            r"Version mismatch",
            r"needs transformers",
            r"needs diffusers",
            r"requires.*transformers",
            r"requires.*diffusers",
            r" transformers ",
            r" diffusers ",
        ],
        "category": "import_error",
        "translations": {
            "zh": {
                "title": "Transformers / Diffusers 版本冲突",
                "explanation": "transformers 或 diffusers 库版本与当前 ComfyUI / 节点包要求不匹配，常导致模型加载或 tokenizer 初始化失败。",
            },
            "en": {
                "title": "Transformers / Diffusers Version Conflict",
                "explanation": "The installed transformers or diffusers version does not match what ComfyUI or a node package requires, often causing model loading or tokenizer initialization failures.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "查看节点包文档或 requirements.txt 中指定的 transformers/diffusers 版本。"),
            ],
            "en": [
                (_vram_always, "Check the node package docs or requirements.txt for the required transformers/diffusers version."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # 系统级错误（磁盘、系统库、CPU 指令集）
    # ------------------------------------------------------------------
    {
        "error_key": "disk_full_error",
        "patterns": [
            r"No space left on device",
            r"Disk full",
            r"insufficient disk space",
            r"磁盘空间不足",
            r"空间不足",
            r"out of disk",
            r"not enough space",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "磁盘空间不足",
                "explanation": "系统磁盘剩余空间不足以保存模型、临时文件或输出图片，常见于模型目录或 /tmp 分区已满。",
            },
            "en": {
                "title": "Disk Space Insufficient",
                "explanation": "The system disk does not have enough free space to save models, temporary files, or output images. Common when the model directory or /tmp partition is full.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "清理 ComfyUI 的 temp、output 目录，或将 models 目录移动到剩余空间更大的分区。"),
            ],
            "en": [
                (_vram_always, "Clean ComfyUI's temp and output folders, or move the models directory to a partition with more free space."),
            ],
        },
    },
    {
        "error_key": "glibc_version_error",
        "patterns": [
            r"version `GLIBC_",
            r"version GLIBC",
            r"libc\.so",
            r"required version",
            r"glibc",
            r"GLIBCXX",
            r"libstdc\+\+",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "Linux 系统库（glibc/libstdc++）版本过低",
                "explanation": "某些预编译 wheel 或 CUDA/ROCm 工具链需要更高版本的 glibc/libstdc++，而当前 Linux 发行版过旧无法提供。",
            },
            "en": {
                "title": "Linux System Library (glibc/libstdc++) Version Too Old",
                "explanation": "Some prebuilt wheels or CUDA/ROCm toolchains require a newer glibc/libstdc++ than the current Linux distribution provides.",
            },
        },
        "suggestions": {
            "zh": [
                (_plat_linux, "Linux：执行 ldd --version 和 strings /usr/lib/x86_64-linux-gnu/libstdc++.so.6 | grep GLIBCXX 查看当前库版本。"),
            ],
            "en": [
                (_plat_linux, "Linux: run ldd --version and strings /usr/lib/x86_64-linux-gnu/libstdc++.so.6 | grep GLIBCXX to check current library versions."),
            ],
        },
    },
    {
        "error_key": "cpu_instruction_error",
        "patterns": [
            r"illegal instruction",
            r"SIGILL",
            r"Illegal instruction",
            r"AVX",
            r"SSE",
            r"CPU does not support",
            r"指令非法",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "CPU 指令集不支持（Illegal Instruction）",
                "explanation": "PyTorch 或某些加速库编译时使用了当前 CPU 不支持的指令集（如 AVX、AVX2），常见于老旧 CPU 运行新版 PyTorch。",
            },
            "en": {
                "title": "CPU Instruction Set Not Supported (Illegal Instruction)",
                "explanation": "PyTorch or acceleration libraries were compiled with instruction sets (e.g. AVX, AVX2) that the current CPU does not support. Common when running newer PyTorch on old CPUs.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "检查 CPU 支持的指令集：Linux 执行 cat /proc/cpuinfo | grep flags；Windows 使用 CPU-Z。"),
            ],
            "en": [
                (_vram_always, "Check supported CPU instructions: Linux run cat /proc/cpuinfo | grep flags; Windows use CPU-Z."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # 启动崩溃/闪退兜底
    # ------------------------------------------------------------------
    {
        "error_key": "launch_crash",
        "patterns": [
            r"启动闪退",
            r"启动崩溃",
            r"一启动就崩溃",
            r"闪退",
            r"启动后消失",
            r"ComfyUI.*crash",
            r"ComfyUI.*crashed",
            r"main\.py.*exit",
            r"Process finished with exit code",
            r"Fatal Python error",
            r"Segmentation fault",
            r"SIGSEGV",
            r"core dumped",
        ],
        "category": "crash",
        "translations": {
            "zh": {
                "title": "ComfyUI 启动崩溃/闪退",
                "explanation": "ComfyUI 在启动阶段或执行时异常退出，可能由显卡驱动不兼容、PyTorch/CUDA 版本错误、模型文件损坏、节点包冲突或硬件过热导致。",
            },
            "en": {
                "title": "ComfyUI Launch Crash / Sudden Exit",
                "explanation": "ComfyUI crashed during startup or execution. Possible causes: incompatible GPU driver, wrong PyTorch/CUDA version, corrupted model file, node package conflict, or hardware overheating.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "首先尝试用最小工作流（仅 Load Checkpoint + Empty Latent + KSampler）测试，排除复杂工作流或节点冲突。"),
            ],
            "en": [
                (_vram_always, "First test with a minimal workflow (Load Checkpoint + Empty Latent + KSampler) to rule out complex workflows or node conflicts."),
            ],
        },
    },
    # ------------------------------------------------------------------
    # 通用 Python 运行时异常兜底（必须在具体错误之后，避免覆盖）
    # ------------------------------------------------------------------
    {
        "error_key": "python_runtime_error",
        "patterns": [
            r"\bRuntimeError\b",
            r"\bValueError\b",
            r"\bTypeError\b",
            r"\bIndexError\b",
            r"\bAssertionError\b",
            r"\bNotImplementedError\b",
        ],
        "category": "runtime_error",
        "translations": {
            "zh": {
                "title": "运行时错误",
                "explanation": "ComfyUI 在执行过程中抛出了 Python 运行时异常。具体原因需要结合原始报错与堆栈定位。",
            },
            "en": {
                "title": "Runtime Error",
                "explanation": "ComfyUI raised a Python runtime exception during execution. Inspect the original error and traceback to locate the root cause.",
            },
        },
        "suggestions": {
            "zh": [
                (_vram_always, "查看上方原始报错与堆栈，定位抛出异常的节点和代码行。"),
            ],
            "en": [
                (_vram_always, "Review the raw error and traceback above to locate the failing node and code line."),
            ],
        },
    },
]


# ============================================================================
# 对外接口
# ============================================================================

def get_error_dict() -> List[Dict[str, Any]]:
    """返回完整错误词库列表。"""
    return ERROR_DICT


def get_error_dict_version() -> str:
    """返回词库版本号。"""
    return ERROR_DICT_VERSION
