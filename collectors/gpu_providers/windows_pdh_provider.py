"""
Windows GPU Provider - PDH 性能计数器零依赖实现

直接通过 ctypes 调用 Windows 系统自带的 pdh.dll，
无需任何第三方 pip 包即可获取 GPU 利用率与 VRAM 占用。

数据来源与 Windows 任务管理器同源：
- GPU 利用率：GPU Engine\\Utilization Percentage
- 专用显存：GPU Process Memory\\Dedicated Usage

限制：
- 无法获取 GPU 温度、功耗、风扇转速（PDH 未暴露这些计数器）。
- 多 GPU 场景下按物理索引 phys_N 分组；若实例名中无 phys 标记，
  则所有数据归到 device 0。

该 provider 作为 Windows 下 AMD ADL / NVIDIA NVML ctypes 失败后的
真实数据兜底，不会编造任何指标。

Version: 3.0.0
Author: Feixue Team
"""

from __future__ import annotations

import logging
import platform
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)


class _PDHWrapper:
    """ctypes 封装：加载 pdh.dll 并映射关键函数。"""

    PDH_MORE_DATA = -2147481646  # 0x800007D2
    PDH_CSTATUS_VALID_DATA = 0
    PDH_FMT_DOUBLE = 0x00000200

    def __init__(self):
        self._dll: Any = None
        self._procs: Dict[str, Any] = {}

    def load(self) -> bool:
        import ctypes

        if platform.system() != "Windows":
            return False
        try:
            self._dll = ctypes.CDLL("pdh.dll")
        except OSError as e:
            logger.debug("pdh-ctypes: failed to load pdh.dll: %s", e)
            return False

        procs = {
            "PdhOpenQueryW": (ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
            "PdhCloseQuery": (ctypes.c_void_p,),
            "PdhEnumObjectItemsW": (
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.c_ulong,
                ctypes.c_ulong,
            ),
            "PdhAddCounterW": (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
            "PdhCollectQueryData": (ctypes.c_void_p,),
            "PdhGetFormattedCounterValue": (ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p),
            "PdhRemoveCounter": (ctypes.c_void_p,),
        }

        for func_name, argtypes in procs.items():
            proc = getattr(self._dll, func_name, None)
            if proc is None:
                logger.debug("pdh-ctypes: missing function %s", func_name)
                continue
            try:
                proc.argtypes = argtypes
                proc.restype = ctypes.c_long
                self._procs[func_name] = proc
            except Exception as e:
                logger.debug("pdh-ctypes: failed to set prototype for %s: %s", func_name, e)

        if "PdhOpenQueryW" not in self._procs:
            self._dll = None
            return False
        return True

    def enum_instances(self, object_name: str = "GPU Engine") -> List[str]:
        """枚举 PDH 对象的所有实例名。"""
        import ctypes

        proc = self._procs.get("PdhEnumObjectItemsW")
        if proc is None:
            return []

        counter_size = ctypes.c_ulong(0)
        instance_size = ctypes.c_ulong(0)

        # 第一次调用获取缓冲区大小
        ret = proc(None, None, object_name, None, ctypes.byref(counter_size), None, ctypes.byref(instance_size), 0, 0)
        if ret != self.PDH_MORE_DATA and ret != 0:
            return []

        if instance_size.value == 0:
            return []

        # 实例名缓冲区
        instance_buf = ctypes.create_unicode_buffer(instance_size.value)
        counter_buf = ctypes.create_unicode_buffer(counter_size.value)

        ret = proc(
            None,
            None,
            object_name,
            counter_buf,
            ctypes.byref(counter_size),
            instance_buf,
            ctypes.byref(instance_size),
            0,
            0,
        )
        if ret != 0:
            return []

        # 解析 MULTI_SZ
        names: List[str] = []
        i = 0
        buf_len = len(instance_buf)
        while i < buf_len:
            # 找到下一个 null 结尾字符串
            end = i
            while end < buf_len and instance_buf[end] != "\0":
                end += 1
            if end == i:
                break
            names.append(instance_buf[i:end])
            i = end + 1
        return names

    def _create_query(self) -> Any:
        import ctypes

        proc = self._procs.get("PdhOpenQueryW")
        if proc is None:
            return None
        query = ctypes.c_void_p()
        ret = proc(None, None, ctypes.byref(query))
        if ret != 0:
            return None
        return query

    def _close_query(self, query: Any) -> None:
        proc = self._procs.get("PdhCloseQuery")
        if proc is None or query is None:
            return
        try:
            proc(query)
        except Exception as e:
            logger.debug("pdh-ctypes: PdhCloseQuery error: %s", e)

    def _add_counter(self, query: Any, path: str) -> Any:
        import ctypes

        proc = self._procs.get("PdhAddCounterW")
        if proc is None:
            return None
        counter = ctypes.c_void_p()
        ret = proc(query, path, None, ctypes.byref(counter))
        if ret != 0:
            return None
        return counter

    def _remove_counter(self, counter: Any) -> None:
        proc = self._procs.get("PdhRemoveCounter")
        if proc is None or counter is None:
            return
        try:
            proc(counter)
        except Exception:
            pass

    def _collect(self, query: Any) -> int:
        proc = self._procs.get("PdhCollectQueryData")
        if proc is None or query is None:
            return -1
        return proc(query)

    def _get_value(self, counter: Any) -> Optional[float]:
        import ctypes

        proc = self._procs.get("PdhGetFormattedCounterValue")
        if proc is None or counter is None:
            return None

        class PDH_FMT_COUNTERVALUE(ctypes.Structure):
            _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]

        value = PDH_FMT_COUNTERVALUE()
        ret = proc(counter, self.PDH_FMT_DOUBLE, None, ctypes.byref(value))
        if ret != 0:
            return None
        if value.CStatus != self.PDH_CSTATUS_VALID_DATA:
            return None
        return float(value.doubleValue)

    def query_counter(self, path: str, interval: float = 0.1) -> Optional[float]:
        """单次查询指定计数器路径。"""
        query = self._create_query()
        if query is None:
            return None
        counter = self._add_counter(query, path)
        if counter is None:
            self._close_query(query)
            return None

        try:
            # 第一次采集建立基线
            if self._collect(query) != 0:
                return None
            if interval > 0:
                time.sleep(interval)
            if self._collect(query) != 0:
                return None
            return self._get_value(counter)
        finally:
            self._remove_counter(counter)
            self._close_query(query)


class WindowsPdhProvider(BaseGPUProvider):
    """基于 Windows PDH 性能计数器的 GPU 数据提供者。"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="windows-pdh", priority=5, config=config)
        self._pdh: Optional[_PDHWrapper] = None
        self._util_instances: Dict[int, List[str]] = {}
        self._mem_instances: Dict[int, List[str]] = {}
        self._device_count: int = 0

    @property
    def priority(self) -> int:
        return 5

    def initialize(self) -> bool:
        if platform.system() != "Windows":
            return False

        pdh = _PDHWrapper()
        if not pdh.load():
            logger.info("windows-pdh: 无法加载 pdh.dll")
            return False

        # 枚举 GPU Engine 实例并按 phys_N 分组
        engine_instances = pdh.enum_instances("GPU Engine")
        self._util_instances = self._group_by_phys(engine_instances)

        # 枚举 GPU Process Memory 实例并按 phys_N 分组
        mem_instances = pdh.enum_instances("GPU Process Memory")
        self._mem_instances = self._group_by_phys(mem_instances)

        if not self._util_instances and not self._mem_instances:
            logger.warning("windows-pdh: 未找到任何 GPU 计数器实例")
            return False

        self._pdh = pdh
        self._device_count = max(len(self._util_instances), len(self._mem_instances))
        self._device_names = [f"GPU {i}" for i in range(self._device_count)]
        self._initialized = True

        logger.info(
            "windows-pdh provider initialized: %d device(s)",
            self._device_count,
        )
        return True

    def shutdown(self) -> None:
        self._pdh = None
        self._util_instances = {}
        self._mem_instances = {}
        self._device_count = 0
        self._initialized = False
        self._device_names = []

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"GPU {device_id}"

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        if not self._initialized or self._pdh is None:
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        gpu_util = self._sum_instances(
            self._util_instances.get(device_id, []),
            "GPU Engine",
            "Utilization Percentage",
        )

        vram_used = self._sum_instances(
            self._mem_instances.get(device_id, []),
            "GPU Process Memory",
            "Dedicated Usage",
        )

        # PDH 无法提供总量；尝试 PyTorch 校验，否则显示 0
        torch_total, _ = self._get_pytorch_vram(device_id)

        return GPUMetrics(
            gpu_utilization=round(gpu_util, 1) if gpu_util is not None else 0.0,
            vram_used=max(0, int(vram_used / (1024 * 1024))) if vram_used is not None else 0,
            vram_total=max(0, int(torch_total or 0)),
            temperature=None,
            power_usage=None,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="",
        )

    @staticmethod
    def _group_by_phys(instances: List[str]) -> Dict[int, List[str]]:
        """按实例名中的 phys_N 标记分组。"""
        groups: Dict[int, List[str]] = {}
        for inst in instances:
            # 实例名示例：
            # pid_1234_luid_0x00000000_0x0000C5A1_phys_0_engtype_3D
            m = re.search(r"_phys_(\d+)", inst)
            if m:
                idx = int(m.group(1))
            else:
                idx = 0
            groups.setdefault(idx, []).append(inst)
        return groups

    def _sum_instances(
        self,
        instances: List[str],
        object_name: str,
        counter_name: str,
    ) -> Optional[float]:
        if self._pdh is None or not instances:
            return None

        total = 0.0
        has_value = False
        for inst in instances:
            # 只取 *_Total 聚合实例以获取整体利用率/内存
            if "_Total" not in inst and object_name == "GPU Engine":
                continue
            path = f"\\{object_name}({inst})\\{counter_name}"
            value = self._pdh.query_counter(path, interval=0.05)
            if value is not None:
                total += value
                has_value = True
        return total if has_value else None

    @staticmethod
    def _get_pytorch_vram(device_id: int) -> Tuple[int, int]:
        try:
            import torch

            if not torch.cuda.is_available():
                return 0, 0
            if device_id >= torch.cuda.device_count():
                return 0, 0

            props = torch.cuda.get_device_properties(device_id)
            total = getattr(props, "total_memory", 0)
            used = torch.cuda.memory_allocated(device_id)
            return int(total) // (1024 * 1024), int(used) // (1024 * 1024)
        except Exception:
            return 0, 0
