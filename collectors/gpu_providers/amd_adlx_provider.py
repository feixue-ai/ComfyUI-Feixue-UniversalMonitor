"""
Windows AMD GPU Provider - ADLX 原生驱动级实现

替代旧的 windows_wmi_provider（WMI/wmic/pynvml-amd-windows 降级方案），
直接通过 AMD Device Library Extra (ADLX) 读取 GPU 指标：
- GPU 利用率
- VRAM 已用 / 总量
- GPU 温度（EDGE）
- 功耗

数据源优先级：
1. ADLXPybind（AMD ADLX SDK 的 Python 绑定）
2. 若 ADLXPybind 不可用，则初始化失败，不再降级到 WMI/wmic。

显存部分允许 PyTorch 作为补充校验（ComfyUI 用户一定有 torch，
torch.cuda.memory_allocated 是真实值），但不会用 WMI 编造数据。

Version: 3.0.0
Author: Feixue Team
"""

from __future__ import annotations

import ctypes
import logging
import platform
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)


class AMDADLXProvider(BaseGPUProvider):
    """基于 AMD ADLX SDK 的 Windows AMD GPU 数据提供者。"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="amd-adlx", priority=1, config=config)
        self._helper: Any = None
        self._system: Any = None
        self._perf_services: Any = None
        self._gpus: List[Any] = []
        self._tracking: bool = False

    @property
    def priority(self) -> int:
        return 1

    def initialize(self) -> bool:
        """初始化 ADLX SDK 并枚举 AMD GPU 设备。"""
        if platform.system() != "Windows":
            logger.debug("amd-adlx: 仅支持 Windows 平台")
            return False

        try:
            import ADLXPybind as adlx
        except ImportError:
            logger.info(
                "amd-adlx: ADLXPybind 未安装。"
                "Windows AMD 监控需要：pip install ADLXPybind"
            )
            return False

        try:
            self._helper = adlx.ADLXHelper()
            if not self._call(self._helper, "Initialize"):
                logger.warning("amd-adlx: ADLX Initialize 失败")
                return False

            self._system = self._call(self._helper, "GetSystemServices")
            if self._system is None:
                logger.warning("amd-adlx: 无法获取 SystemServices")
                return False

            self._perf_services = self._call(self._system, "GetPerformanceMonitoringServices")
            if self._perf_services is None:
                logger.warning("amd-adlx: 无法获取 PerformanceMonitoringServices")
                return False

            # 启动性能指标追踪
            self._call(self._perf_services, "StartPerformanceMetricsTracking")
            self._tracking = True

            # 枚举 GPU
            gpu_holder = self._call(self._system, "GetGPUs")
            if gpu_holder is None:
                logger.warning("amd-adlx: 无法获取 GPU 列表")
                return False

            self._gpus = self._extract_gpu_list(gpu_holder)
            if not self._gpus:
                logger.warning("amd-adlx: 未检测到 AMD GPU")
                return False

            self._device_count = len(self._gpus)
            self._device_names = [self._fetch_gpu_name(g) for g in self._gpus]
            self._initialized = True

            logger.info(
                "amd-adlx provider initialized: %d device(s)",
                self._device_count,
            )
            return True

        except Exception as e:
            logger.warning("amd-adlx: 初始化异常: %s", e)
            self._cleanup()
            return False

    def shutdown(self) -> None:
        """停止追踪并释放 ADLX 资源。"""
        try:
            if self._perf_services is not None and self._tracking:
                self._call(self._perf_services, "StopPerformanceMetricsTracking")
        except Exception as e:
            logger.debug("amd-adlx: StopPerformanceMetricsTracking error: %s", e)
        finally:
            self._tracking = False

        try:
            if self._helper is not None:
                self._call(self._helper, "Terminate")
        except Exception as e:
            logger.debug("amd-adlx: Terminate error: %s", e)
        finally:
            self._helper = None
            self._system = None
            self._perf_services = None
            self._gpus = []
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
        """通过 ADLX 采集单个 GPU 指标。"""
        if not self._initialized or device_id >= len(self._gpus):
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        gpu = self._gpus[device_id]
        metrics = self._call(
            self._perf_services, "GetCurrentGPUMetrics", gpu
        )

        gpu_util = self._read_metric(metrics, "GPUUsage", "GPUUsage")
        temperature = self._read_metric(metrics, "GPUTemperature", "GPUTemperature")
        power = self._read_metric(metrics, "GPUPower", "GPUChipPower")

        # ADLX VRAM 数据（如果可用）
        adlx_vram_used, adlx_vram_total = self._read_vram(metrics)

        # VRAM 总量：优先 ADLX，回退 PyTorch 设备属性
        torch_total, _ = self._get_pytorch_vram(device_id)
        vram_total = adlx_vram_total if adlx_vram_total else torch_total

        # VRAM 已用：优先 PDH 系统计数器（真实占用），其次 ADLX，最后 PyTorch
        pdh_vram = self._get_pdh_vram_used(device_id)
        if pdh_vram is not None:
            vram_used = pdh_vram
        elif adlx_vram_used is not None:
            vram_used = adlx_vram_used
        else:
            _, torch_used = self._get_pytorch_vram(device_id)
            vram_used = torch_used

        return GPUMetrics(
            gpu_utilization=float(gpu_util or 0),
            vram_used=max(0, int(vram_used or 0)),
            vram_total=max(0, int(vram_total or 0)),
            temperature=round(float(temperature), 1) if temperature else None,
            power_usage=round(float(power), 1) if power else None,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="",
        )

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _call(obj: Any, method_name: str, *args, **kwargs) -> Any:
        """安全调用对象方法，支持多种命名风格。"""
        if obj is None:
            return None
        method = getattr(obj, method_name, None)
        if callable(method):
            try:
                return method(*args, **kwargs)
            except Exception:
                return None
        return None

    def _read_metric(self, metrics: Any, method_name: str, fallback_name: str) -> Optional[float]:
        """从 IADLXGPUMetrics 读取单个浮点指标。"""
        if metrics is None:
            return None
        for name in (method_name, fallback_name):
            method = getattr(metrics, name, None)
            if not callable(method):
                continue
            try:
                value = method()
                if isinstance(value, (int, float)) and value >= 0:
                    return float(value)
                # 某些绑定返回对象，尝试 common 属性
                for attr in ("value", "Value", "_value"):
                    if hasattr(value, attr):
                        inner = getattr(value, attr)
                        if isinstance(inner, (int, float)) and inner >= 0:
                            return float(inner)
            except Exception:
                continue
        return None

    def _read_vram(self, metrics: Any) -> Tuple[Optional[int], Optional[int]]:
        """从 IADLXGPUMetrics 读取 VRAM 已用/总量（MB）。"""
        if metrics is None:
            return None, None

        vram_used_mb: Optional[int] = None
        vram_total_mb: Optional[int] = None

        for method_name in ("GPUVRAM", "GetGPUVRAM", "VRAMUsage", "GetVRAMUsage"):
            method = getattr(metrics, method_name, None)
            if not callable(method):
                continue
            try:
                value = method()
                if hasattr(value, "used") and hasattr(value, "total"):
                    used = getattr(value, "used")
                    total = getattr(value, "total")
                    return int(used) // (1024 * 1024), int(total) // (1024 * 1024)
                if hasattr(value, "Used") and hasattr(value, "Total"):
                    used = getattr(value, "Used")
                    total = getattr(value, "Total")
                    return int(used) // (1024 * 1024), int(total) // (1024 * 1024)
                if hasattr(value, "value"):
                    inner = getattr(value, "value")
                    if hasattr(inner, "used") and hasattr(inner, "total"):
                        return (
                            int(getattr(inner, "used")) // (1024 * 1024),
                            int(getattr(inner, "total")) // (1024 * 1024),
                        )
            except Exception:
                continue

        return vram_used_mb, vram_total_mb

    def _get_pdh_vram_used(self, device_id: int) -> Optional[int]:
        """通过 PDH 系统计数器获取 VRAM 占用（MB）。

        枚举 GPU Process Memory 的所有实例，用 pid(\\d+)_phys_(\\d+) 正则
        匹配出属于 device_id 对应物理 GPU 的实例，查询 Dedicated Usage 并求和。
        """
        if platform.system() != "Windows":
            return None

        try:
            pdh = ctypes.CDLL("pdh.dll")

            # ---- 1. 枚举 GPU Process Memory 的所有实例名 ----
            PDH_MORE_DATA = 0x800007D2

            counter_size = ctypes.c_ulong(0)
            instance_size = ctypes.c_ulong(0)

            # 第一次调用：获取所需缓冲区大小（返回 PDH_MORE_DATA 是正常的）
            pdh.PdhEnumObjectItemsW(
                None, None, "GPU Process Memory",
                None, ctypes.byref(counter_size),
                None, ctypes.byref(instance_size),
                0, 0,
            )

            if instance_size.value == 0:
                return None

            instance_buf = ctypes.create_unicode_buffer(instance_size.value)
            counter_buf = ctypes.create_unicode_buffer(counter_size.value if counter_size.value > 0 else 1)

            status = pdh.PdhEnumObjectItemsW(
                None, None, "GPU Process Memory",
                counter_buf, ctypes.byref(counter_size),
                instance_buf, ctypes.byref(instance_size),
                0, 0,
            )
            if status != 0:
                return None

            # 解析多字符串（以 \0 分隔，以 \0\0 结尾）
            instances: list[str] = []
            i = 0
            buf_len = len(instance_buf)
            while i < buf_len:
                end = i
                while end < buf_len and instance_buf[end] != '\0':
                    end += 1
                if end == i:
                    break
                instances.append(instance_buf[i:end])
                i = end + 1

            if not instances:
                return None

            # ---- 2. 按 phys_(\d+) 筛选 device_id 对应的实例 ----
            inst_re = re.compile(r'phys_(\d+)')
            device_instances: list[str] = []
            for inst in instances:
                m = inst_re.search(inst)
                if m and int(m.group(1)) == device_id:
                    device_instances.append(inst)

            if not device_instances:
                return None

            # ---- 3. 打开 PDH 查询，添加计数器 ----
            query = ctypes.c_void_p()
            status = pdh.PdhOpenQueryW(None, 0, ctypes.byref(query))
            if status != 0:
                return None

            try:
                counter_handles: list[ctypes.c_void_p] = []
                for inst in device_instances:
                    path = f"\\GPU Process Memory({inst})\\Dedicated Usage"
                    handle = ctypes.c_void_p()
                    st = pdh.PdhAddCounterW(query, path, 0, ctypes.byref(handle))
                    if st == 0:
                        counter_handles.append(handle)

                if not counter_handles:
                    return None

                # ---- 4. 两次采样（间隔 0.05s） ----
                status = pdh.PdhCollectQueryData(query)
                if status != 0:
                    return None

                time.sleep(0.05)

                status = pdh.PdhCollectQueryData(query)
                if status != 0:
                    return None

                # ---- 5. 读取每个计数器的值并求和 ----
                PDH_FMT_DOUBLE = 0x00000200

                class PDH_FMT_COUNTERVALUE(ctypes.Structure):
                    _fields_ = [
                        ("CStatus", ctypes.c_ulong),
                        ("doubleValue", ctypes.c_double),
                    ]

                total_bytes = 0.0
                for handle in counter_handles:
                    value = PDH_FMT_COUNTERVALUE()
                    st = pdh.PdhGetFormattedCounterValue(
                        handle, PDH_FMT_DOUBLE, None, ctypes.byref(value),
                    )
                    if st == 0 and value.CStatus == 0:
                        total_bytes += value.doubleValue

                # 字节 → MB
                return int(total_bytes / (1024 * 1024))

            finally:
                pdh.PdhCloseQuery(query)

        except Exception:
            return None

    def _extract_gpu_list(self, gpu_holder: Any) -> List[Any]:
        """从 GPUHolder / GPUList 对象中提取 GPU 实例列表。"""
        gpus: List[Any] = []
        if gpu_holder is None:
            return gpus

        # 尝试常见的集合访问方式
        for attr in ("gpu_list", "GPUList", "gpus", "GPUs", "_gpus"):
            obj = getattr(gpu_holder, attr, None)
            if obj is not None:
                if isinstance(obj, (list, tuple)):
                    return list(obj)
                gpu_holder = obj
                break

        # 如果是可迭代对象
        try:
            return list(gpu_holder)
        except Exception:
            pass

        # 尝试 at/size 接口
        size = getattr(gpu_holder, "Size", None) or getattr(gpu_holder, "size", None)
        at = getattr(gpu_holder, "At", None) or getattr(gpu_holder, "at", None)
        if size is not None and at is not None:
            try:
                count = int(size() if callable(size) else size)
                return [at(i) for i in range(count)]
            except Exception:
                pass

        # 尝试 getGPU / getGPUList
        for method_name in ("getGPU", "getGPUList", "GetGPU", "GetGPUList"):
            method = getattr(gpu_holder, method_name, None)
            if callable(method):
                try:
                    result = method()
                    if isinstance(result, (list, tuple)):
                        return list(result)
                    if result is not None:
                        return [result]
                except Exception:
                    continue

        return gpus

    def _fetch_gpu_name(self, gpu: Any) -> str:
        """读取 GPU 型号名称。"""
        for method_name in ("Name", "name", "GetName", "getName"):
            method = getattr(gpu, method_name, None)
            if callable(method):
                try:
                    value = method()
                    if isinstance(value, str) and value.strip():
                        return value
                except Exception:
                    continue
            value = getattr(gpu, method_name, None)
            if isinstance(value, str) and value.strip():
                return value
        return "AMD GPU"

    def _cleanup(self) -> None:
        """初始化失败时的清理。"""
        try:
            self.shutdown()
        except Exception:
            pass

    @staticmethod
    def _get_pytorch_vram(device_id: int) -> Tuple[int, int]:
        """通过 PyTorch 获取精确 VRAM（MB）。"""
        try:
            import torch

            if not torch.cuda.is_available():
                return 0, 0
            if device_id >= torch.cuda.device_count():
                return 0, 0

            props = torch.cuda.get_device_properties(device_id)
            total = getattr(props, "total_memory", 0)
            total_mb = int(total) // (1024 * 1024)
            used_mb = int(torch.cuda.memory_allocated(device_id)) // (1024 * 1024)
            return total_mb, used_mb
        except Exception:
            return 0, 0
