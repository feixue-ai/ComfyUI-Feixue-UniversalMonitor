"""
Windows/Linux NVIDIA GPU Provider - NVML ctypes 原生零依赖实现

直接通过 ctypes 加载 NVIDIA 驱动自带的 nvml.dll / libnvidia-ml.so，
无需 pip 安装 nvidia-ml-py / pynvml 即可获取 NVIDIA GPU 核心指标。

可获取指标：
- GPU 利用率
- VRAM 已用 / 总量
- GPU 温度
- 功耗

若 ctypes NVML 初始化失败，则由 monitor.py 的 source priority
回退到其它可用 Provider。

Version: 3.0.0
Author: Feixue Team
"""

from __future__ import annotations

import logging
import platform
from typing import Any, Dict, List, Optional, Tuple

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)


class _NVMLWrapper:
    """ctypes 封装：加载 nvml.dll/libnvidia-ml.so 并映射关键函数。"""

    NVML_SUCCESS = 0
    NVML_TEMPERATURE_GPU = 0

    def __init__(self):
        self._dll: Any = None
        self._procs: Dict[str, Any] = {}

    def load(self) -> bool:
        import ctypes

        system = platform.system()
        lib_names: Tuple[str, ...] = ()
        if system == "Windows":
            lib_names = ("nvml.dll", "C:\\Windows\\System32\\nvml.dll")
        elif system == "Linux":
            lib_names = (
                "libnvidia-ml.so.1",
                "libnvidia-ml.so",
                "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1",
                "/usr/lib64/libnvidia-ml.so.1",
            )

        for name in lib_names:
            try:
                self._dll = ctypes.CDLL(name)
                logger.debug("nvml-ctypes: loaded %s", name)
                break
            except OSError:
                continue

        if self._dll is None:
            logger.debug("nvml-ctypes: no NVML library found")
            return False

        void_p = ctypes.c_void_p
        uint_p = ctypes.POINTER(ctypes.c_uint)
        int_p = ctypes.POINTER(ctypes.c_int)
        ulonglong_p = ctypes.POINTER(ctypes.c_ulonglong)

        procs = {
            "nvmlInit_v2": (),
            "nvmlShutdown": (),
            "nvmlDeviceGetCount_v2": (uint_p,),
            "nvmlDeviceGetHandleByIndex_v2": (ctypes.c_uint, ctypes.POINTER(void_p)),
            "nvmlDeviceGetName": (void_p, ctypes.c_char_p, ctypes.c_uint),
            "nvmlDeviceGetUtilizationRates": (void_p, ctypes.c_void_p),
            "nvmlDeviceGetMemoryInfo": (void_p, ctypes.c_void_p),
            "nvmlDeviceGetTemperature": (void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)),
            "nvmlDeviceGetPowerUsage": (void_p, ctypes.POINTER(ctypes.c_uint)),
        }

        for func_name, argtypes in procs.items():
            proc = getattr(self._dll, func_name, None)
            if proc is None:
                # 尝试去掉 _v2 后缀的旧版本
                alt_name = func_name.replace("_v2", "")
                proc = getattr(self._dll, alt_name, None)
                if proc is None:
                    logger.debug("nvml-ctypes: missing function %s", func_name)
                    continue
            try:
                proc.argtypes = argtypes
                proc.restype = ctypes.c_int
                self._procs[func_name] = proc
            except Exception as e:
                logger.debug("nvml-ctypes: failed to set prototype for %s: %s", func_name, e)

        if "nvmlInit_v2" not in self._procs:
            self._dll = None
            return False
        return True

    def initialize(self) -> bool:
        init = self._procs.get("nvmlInit_v2")
        if init is None:
            return False
        try:
            ret = init()
        except Exception as e:
            logger.warning("nvml-ctypes: nvmlInit failed: %s", e)
            return False
        if ret != self.NVML_SUCCESS:
            logger.warning("nvml-ctypes: nvmlInit returned %d", ret)
            return False
        return True

    def shutdown(self) -> None:
        shutdown = self._procs.get("nvmlShutdown")
        if shutdown is None:
            return
        try:
            shutdown()
        except Exception as e:
            logger.debug("nvml-ctypes: nvmlShutdown error: %s", e)

    def get_device_count(self) -> int:
        import ctypes

        proc = self._procs.get("nvmlDeviceGetCount_v2")
        if proc is None:
            return 0
        count = ctypes.c_uint(0)
        ret = proc(ctypes.byref(count))
        if ret != self.NVML_SUCCESS:
            return 0
        return int(count.value)

    def get_device_name(self, handle: Any) -> str:
        import ctypes

        proc = self._procs.get("nvmlDeviceGetName")
        if proc is None:
            return "NVIDIA GPU"
        buf = ctypes.create_string_buffer(256)
        ret = proc(handle, buf, 256)
        if ret != self.NVML_SUCCESS:
            return "NVIDIA GPU"
        try:
            return buf.value.decode("utf-8", errors="ignore").strip() or "NVIDIA GPU"
        except Exception:
            return "NVIDIA GPU"

    def get_utilization(self, handle: Any) -> Optional[float]:
        import ctypes

        proc = self._procs.get("nvmlDeviceGetUtilizationRates")
        if proc is None:
            return None

        class NVMLUtilization(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        util = NVMLUtilization()
        ret = proc(handle, ctypes.byref(util))
        if ret != self.NVML_SUCCESS:
            return None
        return float(util.gpu)

    def get_memory(self, handle: Any) -> Tuple[Optional[int], Optional[int]]:
        import ctypes

        proc = self._procs.get("nvmlDeviceGetMemoryInfo")
        if proc is None:
            return None, None

        class NVMLMemory(ctypes.Structure):
            _fields_ = [
                ("total", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong),
            ]

        mem = NVMLMemory()
        ret = proc(handle, ctypes.byref(mem))
        if ret != self.NVML_SUCCESS:
            return None, None
        return int(mem.total) // (1024 * 1024), int(mem.used) // (1024 * 1024)

    def get_temperature(self, handle: Any) -> Optional[float]:
        import ctypes

        proc = self._procs.get("nvmlDeviceGetTemperature")
        if proc is None:
            return None
        temp = ctypes.c_uint(0)
        ret = proc(handle, self.NVML_TEMPERATURE_GPU, ctypes.byref(temp))
        if ret != self.NVML_SUCCESS:
            return None
        return float(temp.value)

    def get_power_usage(self, handle: Any) -> Optional[float]:
        import ctypes

        proc = self._procs.get("nvmlDeviceGetPowerUsage")
        if proc is None:
            return None
        power = ctypes.c_uint(0)
        ret = proc(handle, ctypes.byref(power))
        if ret != self.NVML_SUCCESS:
            return None
        return round(power.value / 1000.0, 1)

class NvidiaNvmlProvider(BaseGPUProvider):
    """基于 NVML ctypes 的 NVIDIA GPU 数据提供者（零 pip 依赖）。"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="nvidia-nvml", priority=0, config=config)
        self._nvml: Optional[_NVMLWrapper] = None
        self._handles: List[Any] = []

    @property
    def priority(self) -> int:
        return 0

    def initialize(self) -> bool:
        nvml = _NVMLWrapper()
        if not nvml.load():
            logger.info("nvidia-nvml: 未找到 NVML 库，请确认已安装 NVIDIA 驱动")
            return False

        if not nvml.initialize():
            logger.warning("nvidia-nvml: NVML 初始化失败")
            return False

        count = nvml.get_device_count()
        if count <= 0:
            logger.warning("nvidia-nvml: 未检测到 NVIDIA GPU")
            nvml.shutdown()
            return False

        import ctypes

        handles = []
        for i in range(count):
            handle = ctypes.c_void_p()
            proc = nvml._procs.get("nvmlDeviceGetHandleByIndex_v2")
            if proc is None:
                continue
            ret = proc(ctypes.c_uint(i), ctypes.byref(handle))
            if ret == nvml.NVML_SUCCESS:
                handles.append(handle)

        if not handles:
            logger.warning("nvidia-nvml: 无法获取任何 GPU 句柄")
            nvml.shutdown()
            return False

        self._nvml = nvml
        self._handles = handles
        self._device_count = len(handles)
        self._device_names = [nvml.get_device_name(h) for h in handles]
        self._initialized = True

        logger.info(
            "nvidia-nvml provider initialized: %d device(s)",
            self._device_count,
        )
        return True

    def shutdown(self) -> None:
        if self._nvml is not None:
            try:
                self._nvml.shutdown()
            except Exception as e:
                logger.debug("nvidia-nvml: shutdown error: %s", e)
            finally:
                self._nvml = None
                self._handles = []
                self._initialized = False
                self._device_count = 0
                self._device_names = []

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"NVIDIA GPU {device_id}"

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        if not self._initialized or device_id >= len(self._handles) or self._nvml is None:
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        handle = self._handles[device_id]
        nvml = self._nvml

        gpu_util = nvml.get_utilization(handle)
        vram_total, vram_used = nvml.get_memory(handle)
        temperature = nvml.get_temperature(handle)
        power = nvml.get_power_usage(handle)

        return GPUMetrics(
            gpu_utilization=float(gpu_util or 0),
            vram_used=max(0, int(vram_used or 0)),
            vram_total=max(0, int(vram_total or 0)),
            temperature=temperature,
            power_usage=power,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="",
        )
