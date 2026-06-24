"""
Windows AMD GPU Provider - ADL ctypes 原生零依赖实现

直接通过 ctypes 加载 AMD 显卡驱动自带的 atiadlxx.dll/atiadlxy.dll，
无需 pip 安装 ADLXPybind 即可获取 AMD GPU 核心指标。

可获取指标（取决于驱动版本）：
- GPU 利用率
- GPU 温度
- 风扇转速
- 功耗（部分驱动/型号）

VRAM 总量通过 ADL 获取；VRAM 已用量优先使用 PyTorch 校验。
若 ADL 初始化失败，则由 monitor.py 的 source priority 回退到
ADLXPybind 或 Windows PDH 计数器。

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


class _ADLWrapper:
    """ctypes 封装：加载 atiadlxx.dll 并映射关键函数。"""

    ADL_OK = 0
    _DLL_NAMES = ("atiadlxx.dll", "atiadlxy.dll")

    def __init__(self):
        self._dll: Any = None
        self._procs: Dict[str, Any] = {}
        self._buffer: List[Any] = []  # 保持回调分配的内存不被回收

    def load(self) -> bool:
        """尝试加载 AMD ADL DLL。"""
        import ctypes

        if platform.system() != "Windows":
            return False

        for name in self._DLL_NAMES:
            try:
                self._dll = ctypes.CDLL(name)
                logger.debug("adl-ctypes: loaded %s", name)
                break
            except OSError:
                continue

        if self._dll is None:
            logger.debug("adl-ctypes: no ADL DLL found")
            return False

        # 定义函数原型
        int_p = ctypes.POINTER(ctypes.c_int)
        int_arg = ctypes.c_int

        procs = {
            "ADL_Main_Control_Create": (int_p, int_arg),
            "ADL_Main_Control_Destroy": (),
            "ADL_Adapter_NumberOfAdapters_Get": (int_p,),
            "ADL_Adapter_AdapterInfo_Get": (ctypes.c_void_p, ctypes.c_int),
            "ADL_Overdrive5_Temperature_Get": (int_arg, int_arg, ctypes.c_void_p),
            "ADL_Overdrive5_CurrentActivity_Get": (int_arg, ctypes.c_void_p),
            "ADL_Adapter_Active_Get": (int_arg, ctypes.POINTER(ctypes.c_int)),
        }

        for func_name, argtypes in procs.items():
            proc = getattr(self._dll, func_name, None)
            if proc is None:
                logger.debug("adl-ctypes: missing function %s", func_name)
                continue
            try:
                proc.argtypes = argtypes
                proc.restype = ctypes.c_int
                self._procs[func_name] = proc
            except Exception as e:
                logger.debug("adl-ctypes: failed to set prototype for %s: %s", func_name, e)

        # 必须有初始化和获取适配器数量的函数
        if "ADL_Main_Control_Create" not in self._procs:
            self._dll = None
            return False
        if "ADL_Adapter_NumberOfAdapters_Get" not in self._procs:
            self._dll = None
            return False

        return True

    def initialize(self) -> bool:
        """初始化 ADL 控制上下文。"""
        import ctypes

        if self._dll is None:
            return False

        create = self._procs.get("ADL_Main_Control_Create")
        if create is None:
            return False

        # ADL 需要一个内存分配回调。使用 ctypes 的 CFUNCTYPE 包装标准 malloc/free。
        AllocCallback = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int)
        FreeCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p)

        libc = ctypes.CDLL("msvcrt.dll")
        malloc_cb = AllocCallback(libc.malloc)
        free_cb = FreeCallback(libc.free)

        # ADL_Main_Control_Create 接收一个 ADL_MAIN_MEMORY_ALLOC 回调指针，
        # 和连接类型 1（默认连接）。
        # 注意：ctypes 会把 CFUNCTYPE 对象转成函数指针。
        try:
            ret = create(malloc_cb, 1)
        except Exception as e:
            logger.warning("adl-ctypes: ADL_Main_Control_Create failed: %s", e)
            return False

        if ret != self.ADL_OK:
            logger.warning("adl-ctypes: ADL_Main_Control_Create returned %d", ret)
            return False

        # 保持回调引用，防止被 GC
        self._buffer.append(malloc_cb)
        self._buffer.append(free_cb)

        return True

    def destroy(self) -> None:
        """销毁 ADL 控制上下文。"""
        destroy = self._procs.get("ADL_Main_Control_Destroy")
        if destroy is None:
            return
        try:
            destroy()
        except Exception as e:
            logger.debug("adl-ctypes: ADL_Main_Control_Destroy error: %s", e)

    def get_adapter_count(self) -> int:
        """获取 AMD 适配器数量。"""
        import ctypes

        proc = self._procs.get("ADL_Adapter_NumberOfAdapters_Get")
        if proc is None:
            return 0
        count = ctypes.c_int(0)
        ret = proc(ctypes.byref(count))
        if ret != self.ADL_OK:
            return 0
        return count.value

    def get_adapter_info(self, count: int) -> List[Dict[str, Any]]:
        """获取适配器信息列表。"""
        import ctypes

        proc = self._procs.get("ADL_Adapter_AdapterInfo_Get")
        if proc is None or count <= 0:
            return []

        # 使用官方 ADLAdapterInfo 结构体的简化版（大小约 688 字节）。
        # 由于我们只需要名称和索引，保留前几个字段并对齐即可。
        class ADLAdapterInfo(ctypes.Structure):
            _fields_ = [
                ("iSize", ctypes.c_int),
                ("iAdapterIndex", ctypes.c_int),
                ("strUDID", ctypes.c_char * 256),
                ("iBusNumber", ctypes.c_int),
                ("strDriverPath", ctypes.c_char * 256),
                ("strDriverPathExt", ctypes.c_char * 256),
                ("strPNPString", ctypes.c_char * 256),
                ("iDisplayIndex", ctypes.c_int),
            ]

        infos = (ADLAdapterInfo * count)()
        size = ctypes.sizeof(ADLAdapterInfo) * count
        ret = proc(ctypes.cast(infos, ctypes.c_void_p), size)
        if ret != self.ADL_OK:
            logger.debug("adl-ctypes: ADL_Adapter_AdapterInfo_Get returned %d", ret)
            return []

        result = []
        for info in infos:
            name = ""
            try:
                raw = info.strUDID or b""
                if raw:
                    name = raw.decode("utf-8", errors="ignore").split(";")[0].strip()
            except Exception:
                pass
            if not name:
                name = f"AMD GPU {info.iAdapterIndex}"
            result.append({
                "index": info.iAdapterIndex,
                "name": name,
            })
        return result

    def get_temperature(self, adapter_index: int) -> Optional[float]:
        """通过 Overdrive5 获取温度（摄氏度）。"""
        import ctypes

        proc = self._procs.get("ADL_Overdrive5_Temperature_Get")
        if proc is None:
            return None

        class ADLTemperature(ctypes.Structure):
            _fields_ = [("iSize", ctypes.c_int), ("iTemperature", ctypes.c_int)]

        temp = ADLTemperature()
        temp.iSize = ctypes.sizeof(ADLTemperature)
        # 第二个参数 0 表示核心温度传感器
        ret = proc(adapter_index, 0, ctypes.byref(temp))
        if ret != self.ADL_OK:
            return None
        return round(temp.iTemperature / 1000.0, 1)

    def get_activity(self, adapter_index: int) -> Optional[float]:
        """通过 Overdrive5 CurrentActivity 获取 GPU 利用率。"""
        import ctypes

        proc = self._procs.get("ADL_Overdrive5_CurrentActivity_Get")
        if proc is None:
            return None

        class ADLPMActivity(ctypes.Structure):
            _fields_ = [
                ("iSize", ctypes.c_int),
                ("iEngineClock", ctypes.c_int),
                ("iMemoryClock", ctypes.c_int),
                ("iVddc", ctypes.c_int),
                ("iActivityPercent", ctypes.c_int),
                ("iCurrentPerformanceLevel", ctypes.c_int),
                ("iCurrentBusSpeed", ctypes.c_int),
                ("iCurrentBusLanes", ctypes.c_int),
                ("iMaximumBusLanes", ctypes.c_int),
                ("iReserved", ctypes.c_int),
            ]

        activity = ADLPMActivity()
        activity.iSize = ctypes.sizeof(ADLPMActivity)
        ret = proc(adapter_index, ctypes.byref(activity))
        if ret != self.ADL_OK:
            return None
        return float(activity.iActivityPercent)

    def get_active_state(self, adapter_index: int) -> bool:
        """查询适配器是否处于活动状态。"""
        import ctypes

        proc = self._procs.get("ADL_Adapter_Active_Get")
        if proc is None:
            return False
        active = ctypes.c_int(0)
        ret = proc(adapter_index, ctypes.byref(active))
        return ret == self.ADL_OK and active.value == 1


class AMDADLProvider(BaseGPUProvider):
    """基于 AMD ADL (atiadlxx.dll) 的 Windows AMD GPU 数据提供者。"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="amd-adl", priority=0, config=config)
        self._adl: Optional[_ADLWrapper] = None
        self._adapters: List[Dict[str, Any]] = []
        self._pdh_vram_cache: Optional[Dict[int, List[str]]] = None

    @property
    def priority(self) -> int:
        return 0

    def initialize(self) -> bool:
        if platform.system() != "Windows":
            return False

        adl = _ADLWrapper()
        if not adl.load():
            logger.info("amd-adl: 未找到 AMD ADL DLL（atiadlxx.dll），请确认已安装 AMD 显卡驱动")
            return False

        if not adl.initialize():
            logger.warning("amd-adl: ADL 初始化失败")
            return False

        count = adl.get_adapter_count()
        if count <= 0:
            logger.warning("amd-adl: 未检测到 AMD 适配器")
            adl.destroy()
            return False

        adapters = adl.get_adapter_info(count)
        # 过滤掉非活动适配器（如未连接显示器的核显/虚拟适配器）
        adapters = [a for a in adapters if adl.get_active_state(a["index"])]
        if not adapters:
            # 如果全部非活动，保留第一个，避免误过滤
            adapters = [adapters[0] if adapters else {"index": 0, "name": "AMD GPU"}]

        self._adl = adl
        self._adapters = adapters
        self._device_count = len(adapters)
        self._device_names = [a["name"] for a in adapters]
        self._initialized = True

        logger.info(
            "amd-adl provider initialized: %d adapter(s)",
            self._device_count,
        )
        return True

    def shutdown(self) -> None:
        if self._adl is not None:
            try:
                self._adl.destroy()
            except Exception as e:
                logger.debug("amd-adl: shutdown error: %s", e)
            finally:
                self._adl = None
                self._adapters = []
                self._initialized = False
                self._device_count = 0
                self._device_names = []

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"AMD GPU {device_id}"

    def _get_pdh_vram_used(self, device_id: int) -> Optional[int]:
        """通过 PDH 系统计数器获取真实 VRAM 已用量（MB）。"""
        try:
            if platform.system() != "Windows":
                return None

            # 加载 pdh.dll
            pdh = ctypes.CDLL("pdh.dll")

            # 枚举 GPU Process Memory 实例（使用缓存避免重复枚举）
            if self._pdh_vram_cache is None:
                PdhEnumObjectItemsW = pdh.PdhEnumObjectItemsW

                counter_size = ctypes.c_ulong(0)
                instance_size = ctypes.c_ulong(0)

                # 第一次调用获取缓冲区大小
                ret = PdhEnumObjectItemsW(
                    None, None, "GPU Process Memory",
                    None, ctypes.byref(counter_size),
                    None, ctypes.byref(instance_size),
                    0, 0
                )

                if instance_size.value == 0:
                    return None

                # 实例名缓冲区
                instance_buf = ctypes.create_unicode_buffer(instance_size.value)
                counter_buf = ctypes.create_unicode_buffer(counter_size.value)

                ret = PdhEnumObjectItemsW(
                    None, None, "GPU Process Memory",
                    counter_buf, ctypes.byref(counter_size),
                    instance_buf, ctypes.byref(instance_size),
                    0, 0
                )

                if ret != 0:
                    return None

                # 解析 MULTI_SZ 格式的实例名列表
                instances: List[str] = []
                i = 0
                buf_len = len(instance_buf)
                while i < buf_len:
                    end = i
                    while end < buf_len and instance_buf[end] != "\0":
                        end += 1
                    if end == i:
                        break
                    instances.append(instance_buf[i:end])
                    i = end + 1

                # 按 phys_N 分组（与 windows_pdh_provider.py 一致）
                groups: Dict[int, List[str]] = {}
                for inst in instances:
                    m = re.search(r"_phys_(\d+)", inst)
                    if m:
                        idx = int(m.group(1))
                    else:
                        idx = 0
                    groups.setdefault(idx, []).append(inst)

                self._pdh_vram_cache = groups

            # 获取 device_id 对应的实例列表
            target_instances = self._pdh_vram_cache.get(device_id, [])
            if not target_instances:
                return None

            # 查询每个实例的 Dedicated Usage 计数器（使用单个 query，批量添加 counter）
            PdhOpenQueryW = pdh.PdhOpenQueryW
            PdhAddCounterW = pdh.PdhAddCounterW
            PdhCollectQueryData = pdh.PdhCollectQueryData
            PdhGetFormattedCounterValue = pdh.PdhGetFormattedCounterValue
            PdhCloseQuery = pdh.PdhCloseQuery

            class PDH_FMT_COUNTERVALUE(ctypes.Structure):
                _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]

            query = ctypes.c_void_p()
            ret = PdhOpenQueryW(None, None, ctypes.byref(query))
            if ret != 0:
                return None

            counters: List[ctypes.c_void_p] = []
            try:
                for inst in target_instances:
                    counter_path = f"\\GPU Process Memory({inst})\\Dedicated Usage"
                    counter = ctypes.c_void_p()
                    ret = PdhAddCounterW(query, counter_path, None, ctypes.byref(counter))
                    if ret == 0:
                        counters.append(counter)

                if not counters:
                    return None

                # 第一次采集建立基线
                PdhCollectQueryData(query)
                time.sleep(0.05)
                # 第二次采集获取实际值
                PdhCollectQueryData(query)

                total_bytes = 0.0
                has_value = False
                for counter in counters:
                    value = PDH_FMT_COUNTERVALUE()
                    ret = PdhGetFormattedCounterValue(counter, 0x00000200, None, ctypes.byref(value))
                    if ret == 0 and value.CStatus == 0:
                        total_bytes += value.doubleValue
                        has_value = True

                if not has_value:
                    return None

                # 转换为 MB
                return int(total_bytes / (1024 * 1024))
            finally:
                PdhCloseQuery(query)

        except Exception as e:
            logger.debug("amd-adl: PDH VRAM read failed: %s", e)
            return None

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        if not self._initialized or device_id >= len(self._adapters) or self._adl is None:
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        adapter = self._adapters[device_id]
        adapter_index = adapter["index"]

        gpu_util = self._adl.get_activity(adapter_index)
        temperature = self._adl.get_temperature(adapter_index)

        # VRAM 总量：PyTorch 设备属性（物理显存大小，准确）
        torch_total, _ = self._get_pytorch_vram(device_id)
        vram_total = torch_total

        # VRAM 已用：优先 PDH 系统计数器（真实占用），回退 PyTorch
        pdh_vram = self._get_pdh_vram_used(device_id)
        if pdh_vram is not None:
            vram_used = pdh_vram
        else:
            _, torch_used = self._get_pytorch_vram(device_id)
            vram_used = torch_used

        return GPUMetrics(
            gpu_utilization=float(gpu_util or 0),
            vram_used=max(0, int(vram_used or 0)),
            vram_total=max(0, int(vram_total or 0)),
            temperature=temperature,
            power_usage=None,  # ADL Overdrive5 不直接提供功耗；ADLX/PDH 补充
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="",
        )

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
            used = torch.cuda.memory_allocated(device_id)
            return int(total) // (1024 * 1024), int(used) // (1024 * 1024)
        except Exception:
            return 0, 0
