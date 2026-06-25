"""
ComfyUI-Feixue-UniversalMonitor - GPU Provider 集合

按平台/库提供多种 GPU 数据源实现，统一继承 BaseGPUProvider。
注册表 CollectorRegistry 按 priority 排序后自动选择最佳可用 Provider。
"""

from __future__ import annotations

from .nvidia_provider import NvidiaProvider
from .nvidia_nvml_provider import NvidiaNvmlProvider
from .amd_smi_provider import AmdSmiProvider
from .amd_rocm_provider import AmdRocmProvider
from .amd_sysfs_provider import AmdSysfsProvider
from .amd_adlx_provider import AMDADLXProvider
from .amd_adl_provider import AMDADLProvider
from .dxgi_provider import DXGIProvider
from .windows_pdh_provider import WindowsPdhProvider

__all__ = [
    "NvidiaProvider",
    "NvidiaNvmlProvider",
    "AmdSmiProvider",
    "AmdRocmProvider",
    "AmdSysfsProvider",
    "AMDADLXProvider",
    "AMDADLProvider",
    "DXGIProvider",
    "WindowsPdhProvider",
]
