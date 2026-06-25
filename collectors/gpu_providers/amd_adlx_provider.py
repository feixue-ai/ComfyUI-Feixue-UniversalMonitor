"""
Windows AMD GPU Provider — ADLX C++ Bridge 实现（零 pip 依赖）

通过 ctypes 加载随插件发布的 `feixue_adlx_bridge.dll`（C++ bridge，
内部调用 AMD ADLX SDK），获取 GPU 利用率、温度、VRAM、功耗。

架构：
  Python ctypes  →  feixue_adlx_bridge.dll (extern "C")  →  ADLX SDK (C++ COM)  →  AMD 驱动

优势：
- 零 pip 依赖（bridge DLL 随插件发布）
- 零用户编译（CI 预编译）
- 稳定可用（extern "C" ABI 锁死，驱动升级无需重新编译）
- 数据准确（ADLX 与驱动同源，精度最高）

降级链（仅当 bridge DLL 不存在或 AMD 驱动未装时）：
  ADLX(bridge) → ADL(ctypes) → DXGI(VRAM) → PDH(利用率)

Version: 4.0.0 (bridge DLL 重写版)
Author: Feixue Team
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
from typing import Optional

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)

# Bridge DLL 返回码
_FEIXUE_ADLX_OK = 0
_FEIXUE_ADLX_NOT_INIT = -1
_FEIXUE_ADLX_INIT_FAILED = -2
_FEIXUE_ADLX_NO_GPU = -3
_FEIXUE_ADLX_BAD_INDEX = -4
_FEIXUE_ADLX_METRICS_FAIL = -5
_FEIXUE_ADLX_EXCEPTION = -6


def _find_bridge_dll() -> Optional[str]:
    """定位随插件发布的 feixue_adlx_bridge.dll。

    搜索顺序：
    1. 插件根目录下的 libs/feixue_adlx_bridge.dll
    2. 插件根目录下的 feixue_adlx_bridge.dll
    """
    # 当前文件: collectors/gpu_providers/amd_adlx_provider.py
    # 插件根: 上三级目录
    plugin_root = os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )

    candidates = [
        os.path.join(plugin_root, "libs", "feixue_adlx_bridge.dll"),
        os.path.join(plugin_root, "feixue_adlx_bridge.dll"),
    ]

    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


class AMDADLXProvider(BaseGPUProvider):
    """基于 ADLX C++ Bridge DLL 的 Windows AMD GPU 数据提供者。

    第一优先级（priority=0）。在 AMD 驱动正常的 Windows 上应稳定返回全指标，
    无需降级。
    """

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="amd-adlx", priority=0, config=config)
        self._dll: Optional[ctypes.CDLL] = None
        self._dll_path: Optional[str] = None

    def initialize(self) -> bool:
        """加载 bridge DLL 并初始化 ADLX 运行时。"""
        if platform.system() != "Windows":
            logger.debug("amd-adlx: 仅支持 Windows 平台")
            return False

        if self._initialized:
            return True

        # 1. 定位 bridge DLL
        dll_path = _find_bridge_dll()
        if dll_path is None:
            logger.info(
                "amd-adlx: bridge DLL 未找到（libs/feixue_adlx_bridge.dll），"
                "将降级到 ADL。bridge DLL 将由 CI 自动构建。"
            )
            return False

        # 2. 加载 DLL
        try:
            self._dll = ctypes.CDLL(dll_path)
            self._dll_path = dll_path
        except OSError as e:
            logger.warning("amd-adlx: 加载 bridge DLL 失败 %s: %s", dll_path, e)
            return False

        # 3. 设置函数原型
        if not self._setup_prototypes():
            logger.warning("amd-adlx: bridge DLL 函数原型设置失败")
            self._dll = None
            return False

        # 4. 初始化 ADLX
        try:
            ret = self._dll.feixue_adlx_init()
            if ret != _FEIXUE_ADLX_OK:
                err = self._dll.feixue_adlx_last_error()
                err_msg = ctypes.string_at(err).decode("utf-8", errors="ignore") if err else ""
                logger.info(
                    "amd-adlx: ADLX 初始化失败 (code=%d): %s — 将降级到 ADL",
                    ret, err_msg,
                )
                self._dll = None
                return False
        except Exception as e:
            logger.warning("amd-adlx: feixue_adlx_init 异常: %s", e)
            self._dll = None
            return False

        # 5. 获取 GPU 数量和名称
        gpu_count = self._dll.feixue_adlx_get_gpu_count()
        if gpu_count <= 0:
            logger.warning("amd-adlx: 未检测到 AMD GPU (count=%d)", gpu_count)
            self._dll.feixue_adlx_shutdown()
            self._dll = None
            return False

        self._device_count = gpu_count
        self._device_names = []
        for i in range(gpu_count):
            name_ptr = self._dll.feixue_adlx_get_gpu_name(i)
            if name_ptr:
                name = ctypes.string_at(name_ptr).decode("utf-8", errors="ignore")
            else:
                name = f"AMD GPU {i}"
            self._device_names.append(name)

        self._initialized = True
        logger.info(
            "amd-adlx: ✅ ADLX bridge 初始化成功，检测到 %d 个 AMD GPU: %s",
            gpu_count,
            ", ".join(self._device_names),
        )
        return True

    def shutdown(self) -> None:
        """关闭 ADLX 运行时，释放资源。"""
        if self._dll is not None:
            try:
                self._dll.feixue_adlx_shutdown()
            except Exception as e:
                logger.debug("amd-adlx: shutdown 异常: %s", e)
            finally:
                self._dll = None

        self._initialized = False
        self._device_count = 0
        self._device_names = []

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"AMD GPU {device_id}"

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """通过 ADLX bridge 采集单个 GPU 的全部指标。"""
        if not self._initialized or self._dll is None:
            return self._empty_metrics(device_id)

        if device_id < 0 or device_id >= self._device_count:
            return self._empty_metrics(device_id)

        # 准备输出参数
        gpu_usage = ctypes.c_double(0.0)
        temperature = ctypes.c_double(0.0)
        vram_used = ctypes.c_ulonglong(0)
        vram_total = ctypes.c_ulonglong(0)
        power = ctypes.c_double(0.0)

        try:
            ret = self._dll.feixue_adlx_get_metrics(
                device_id,
                ctypes.byref(gpu_usage),
                ctypes.byref(temperature),
                ctypes.byref(vram_used),
                ctypes.byref(vram_total),
                ctypes.byref(power),
            )
        except Exception as e:
            logger.warning("amd-adlx: get_metrics 异常: %s", e)
            return self._empty_metrics(device_id)

        if ret != _FEIXUE_ADLX_OK:
            logger.debug("amd-adlx: get_metrics 返回错误码 %d", ret)
            return self._empty_metrics(device_id)

        # ADLX bridge 返回的 VRAM 单位为 MB（与 GPUMetrics 一致）
        return GPUMetrics(
            gpu_utilization=float(gpu_usage.value),
            vram_used=max(0, int(vram_used.value)),
            vram_total=max(0, int(vram_total.value)),
            temperature=round(float(temperature.value), 1) if temperature.value > 0 else None,
            power_usage=round(float(power.value), 1) if power.value > 0 else None,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="",
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _setup_prototypes(self) -> bool:
        """设置 bridge DLL 的函数原型（argtypes/restype）。"""
        dll = self._dll
        try:
            # int feixue_adlx_init(void)
            dll.feixue_adlx_init.argtypes = []
            dll.feixue_adlx_init.restype = ctypes.c_int

            # void feixue_adlx_shutdown(void)
            dll.feixue_adlx_shutdown.argtypes = []
            dll.feixue_adlx_shutdown.restype = None

            # int feixue_adlx_get_gpu_count(void)
            dll.feixue_adlx_get_gpu_count.argtypes = []
            dll.feixue_adlx_get_gpu_count.restype = ctypes.c_int

            # const char* feixue_adlx_get_gpu_name(int)
            dll.feixue_adlx_get_gpu_name.argtypes = [ctypes.c_int]
            dll.feixue_adlx_get_gpu_name.restype = ctypes.c_void_p

            # int feixue_adlx_get_metrics(int, double*, double*, ulonglong*, ulonglong*, double*)
            dll.feixue_adlx_get_metrics.argtypes = [
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_ulonglong),
                ctypes.POINTER(ctypes.c_ulonglong),
                ctypes.POINTER(ctypes.c_double),
            ]
            dll.feixue_adlx_get_metrics.restype = ctypes.c_int

            # const char* feixue_adlx_last_error(void)
            dll.feixue_adlx_last_error.argtypes = []
            dll.feixue_adlx_last_error.restype = ctypes.c_void_p

            return True
        except AttributeError as e:
            logger.warning("amd-adlx: bridge DLL 缺少必要函数: %s", e)
            return False

    def _empty_metrics(self, device_id: int) -> GPUMetrics:
        """返回空指标（用于未初始化或采集失败时）。"""
        return GPUMetrics(
            gpu_utilization=0.0,
            vram_used=0,
            vram_total=0,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
        )
