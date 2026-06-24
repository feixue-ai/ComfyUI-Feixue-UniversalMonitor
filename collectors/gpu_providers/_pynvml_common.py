"""
pynvml 多实现检测辅助模块

解决不同 pynvml 包同名冲突问题：
- pynvml（NVIDIA 官方原版）
- pynvml-amd-windows（AMD ADLX 封装）
- nvidia-ml-py（第三方兼容层，通常也以 pynvml 模块暴露）

检测策略优先使用 importlib.metadata 读取安装包元数据，
失败时退回到属性启发式判断，避免重复 import 导致 AMD 分支永远走不到。
"""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# 已知 pynvml 变体
_VARIANT_NVIDIA_NATIVE = "nvidia_native"
_VARIANT_NVIDIA_ML_PY = "nvidia_ml_py"
_VARIANT_AMD_WINDOWS = "amd_windows"
_VARIANT_UNKNOWN = "unknown"


def _is_distribution_installed(name: str) -> bool:
    """检查某个 Python 发行包是否已安装（不触发模块导入）。"""
    try:
        importlib.metadata.distribution(name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def _detect_variant_by_metadata() -> Optional[str]:
    """
    通过已安装发行包名称判断当前 import 的 pynvml 属于哪个变体。

    注意：pynvml-amd-windows 同样会提供 pynvml 模块，
    因此不能仅靠模块属性判断，要先看元数据。
    """
    if _is_distribution_installed("pynvml-amd-windows"):
        return _VARIANT_AMD_WINDOWS
    if _is_distribution_installed("nvidia-ml-py"):
        return _VARIANT_NVIDIA_ML_PY
    if _is_distribution_installed("pynvml"):
        return _VARIANT_NVIDIA_NATIVE
    return None


def _heuristic_variant(module: Any) -> str:
    """当元数据不可用时，使用模块属性做启发式判断。"""
    # AMD 封装通常缺少 NVIDIA 专有常量或函数
    if not hasattr(module, "NVML_TEMPERATURE_GPU"):
        return _VARIANT_AMD_WINDOWS

    # nvidia-ml-py 常带有 __version__ 且版本号通常 >= 12.x
    version = getattr(module, "__version__", "")
    if isinstance(version, str) and "nvidia" in version.lower():
        return _VARIANT_NVIDIA_NATIVE

    return _VARIANT_UNKNOWN


def import_pynvml(
    allowed_variants: Optional[Tuple[str, ...]] = None,
) -> Tuple[Optional[Any], str]:
    """
    安全导入 pynvml 并识别其变体。

    Args:
        allowed_variants: 允许的变体白名单，例如 ("nvidia_native", "nvidia_ml_py")；
                          为 None 时表示接受任意变体。

    Returns:
        (module, variant) 元组。如果未安装或不在白名单内，返回 (None, "").
    """
    if allowed_variants is None:
        allowed_variants = (
            _VARIANT_NVIDIA_NATIVE,
            _VARIANT_NVIDIA_ML_PY,
            _VARIANT_AMD_WINDOWS,
            _VARIANT_UNKNOWN,
        )

    # 先尝试独立的 nvidia_ml_py 包
    try:
        import nvidia_ml_py as nvml_module

        variant = _detect_variant_by_metadata() or _heuristic_variant(nvml_module)
        if variant in allowed_variants:
            return nvml_module, variant
        logger.debug("nvidia_ml_py detected but variant '%s' not allowed", variant)
    except ImportError:
        pass

    # 再尝试 pynvml 模块（可能是 NVIDIA 原版，也可能是 AMD Windows 封装）
    try:
        import pynvml as nvml_module

        variant = _detect_variant_by_metadata() or _heuristic_variant(nvml_module)
        if variant in allowed_variants:
            return nvml_module, variant
        logger.debug("pynvml detected but variant '%s' not allowed", variant)
    except ImportError:
        pass

    return None, ""


def is_amd_windows_pynvml() -> bool:
    """判断当前环境中 pynvml 是否为 AMD Windows 封装。"""
    _, variant = import_pynvml(
        allowed_variants=(_VARIANT_AMD_WINDOWS, _VARIANT_NVIDIA_NATIVE, _VARIANT_UNKNOWN)
    )
    return variant == _VARIANT_AMD_WINDOWS
