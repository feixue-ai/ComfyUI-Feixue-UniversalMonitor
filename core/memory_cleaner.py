"""
智能内存清理模块 (Smart Memory Cleaner)

安全调用 ComfyUI 内存管理接口，兼容 CUDA / ROCm / MPS / CPU 环境。
核心原则：
1. 任何异常都不向上抛出，仅通过返回值反馈。
2. torch 不可用时跳过 torch 相关调用与显存采集。
3. 清理前后分别采样 RAM / VRAM，返回可量化的释放估算。
4. 'ram' 模式仅整理 Python 堆内存，不触碰 ComfyUI 模型/缓存，避免工作流出图异常。
5. 'deep' 模式通过 ComfyUI 原生 /free 端点卸载模型并释放显存，随后再做一次安全的 gc。
"""

from __future__ import annotations

import gc
import logging
import platform
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _get_ram_used_mb() -> int:
    """获取当前物理内存已用量（MB）。失败时返回 0。"""
    try:
        import psutil
        return int(psutil.virtual_memory().used // (1024 * 1024))
    except Exception as e:
        logger.debug(f"RAM 采样失败: {e}")
        return 0


def _get_vram_used_mb() -> Optional[int]:
    """
    获取 PyTorch 当前已分配显存（MB）。

    - CUDA / ROCm：使用 torch.cuda.memory_allocated
    - MPS：使用 torch.mps.current_allocated_memory（若可用）
    - CPU 或无 torch：返回 None

    Returns:
        已分配显存 MB 数，或 None（表示不可用）
    """
    try:
        import torch
    except Exception as e:
        logger.debug(f"torch 不可用，跳过 VRAM 采样: {e}")
        return None

    try:
        if torch.cuda.is_available():
            return int(torch.cuda.memory_allocated() // (1024 * 1024))

        if (
            hasattr(torch, "mps")
            and hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            # torch.mps.current_allocated_memory 在较新 torch 版本中可用
            if hasattr(torch.mps, "current_allocated_memory"):
                return int(torch.mps.current_allocated_memory() // (1024 * 1024))
    except Exception as e:
        logger.debug(f"VRAM 采样失败: {e}")

    return None


def _trim_malloc_arena() -> Optional[str]:
    """
    Linux 下调用 glibc malloc_trim 将空闲堆页还给操作系统。

    Returns:
        错误信息字符串；成功返回 None。
    """
    if platform.system() != "Linux":
        return None

    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
        return None
    except Exception as e:
        logger.debug(f"malloc_trim 调用失败: {e}")
        return f"malloc_trim 失败: {e}"


def _set_comfyui_free_flags() -> Optional[str]:
    """
    通过 ComfyUI PromptServer 设置队列清理标志。

    ComfyUI 主执行循环会在下一次执行边界安全地处理这些标志：
    - unload_models: 卸载已加载模型
    - free_memory: 释放执行缓存

    这种方式比直接调用 unload_all_models() 或直接 POST /free 更安全，
    因为它不会中断当前正在运行的工作流。

    Returns:
        错误信息字符串；成功返回 None。
    """
    try:
        from server import PromptServer
        prompt_queue = PromptServer.instance.prompt_queue
        prompt_queue.set_flag("unload_models", True)
        prompt_queue.set_flag("free_memory", True)
        return None
    except Exception as e:
        logger.warning(f"设置 ComfyUI 清理标志失败: {e}")
        return f"设置 ComfyUI 清理标志失败: {e}"


def _safe_gc() -> None:
    """执行一次安全的 gc.collect()，忽略所有异常。"""
    try:
        gc.collect()
    except Exception as e:
        logger.warning(f"gc.collect() 异常: {e}")


def free_memory(mode: str = "ram", base_url: Optional[str] = None) -> Dict[str, Any]:
    """
    执行一次安全的内存清理。

    支持两种模式：
    - 'ram': 仅整理 RAM。执行 gc.collect() 与 Linux malloc_trim(0)，
             不调用任何 ComfyUI 模型卸载或缓存清空函数，避免影响正在生成的工作流。
    - 'deep': 深度清理。通过 ComfyUI PromptServer 设置队列清理标志
              （unload_models + free_memory），ComfyUI 会在下一次执行边界
              安全地卸载模型并释放显存，随后再执行一次安全的 gc.collect()。

    Args:
        mode: 清理模式，'ram' 或 'deep'。
        base_url: 已弃用，仅保留接口兼容性。

    Returns:
        包含清理结果的字典，字段如下：
        {
            "success": bool,
            "mode": "ram" | "deep",
            "ram_before_mb": int,
            "ram_after_mb": int,
            "ram_released_mb": int,
            "vram_before_mb": int | None,
            "vram_after_mb": int | None,
            "vram_released_mb": int | None,
            "message": str,
        }
    """
    _ = base_url  # 已弃用，保留兼容性

    result: Dict[str, Any] = {
        "success": False,
        "mode": mode,
        "ram_before_mb": 0,
        "ram_after_mb": 0,
        "ram_released_mb": 0,
        "vram_before_mb": None,
        "vram_after_mb": None,
        "vram_released_mb": None,
        "message": "",
    }

    try:
        # 1. 清理前采样
        ram_before = _get_ram_used_mb()
        vram_before = _get_vram_used_mb()

        operation_error: Optional[str] = None

        if mode == "ram":
            # RAM 整理模式：只执行安全的 Python 层与 C 堆整理
            _safe_gc()
            operation_error = _trim_malloc_arena()

        elif mode == "deep":
            # 深度清理模式：请求 ComfyUI 在下一次执行边界安全卸载模型/释放缓存
            operation_error = _set_comfyui_free_flags()
            _safe_gc()

        else:
            result["message"] = f"不支持的清理模式: {mode}"
            logger.warning(f"[飞雪监测器] {result['message']}")
            return result

        # 2. 清理后采样
        ram_after = _get_ram_used_mb()
        vram_after = _get_vram_used_mb()

        # 3. 计算释放量
        ram_released = max(0, ram_before - ram_after)
        vram_released = None
        if vram_before is not None and vram_after is not None:
            vram_released = max(0, vram_before - vram_after)

        result.update(
            {
                "success": operation_error is None,
                "ram_before_mb": ram_before,
                "ram_after_mb": ram_after,
                "ram_released_mb": ram_released,
                "vram_before_mb": vram_before,
                "vram_after_mb": vram_after,
                "vram_released_mb": vram_released,
            }
        )

        mode_label = "RAM 整理" if mode == "ram" else "深度清理"
        vram_part = (
            f"，释放 VRAM {vram_released} MB"
            if vram_released is not None
            else ""
        )

        if operation_error is None:
            result["message"] = (
                f"{mode_label}完成：释放 RAM {ram_released} MB{vram_part}"
            )
        else:
            result["message"] = f"{mode_label}部分完成：{operation_error}"

        logger.info(f"[飞雪监测器] {result['message']}")
        return result

    except Exception as e:
        result["message"] = f"内存清理异常: {e}"
        logger.error(f"[飞雪监测器] free_memory 未捕获异常: {e}", exc_info=True)
        return result
