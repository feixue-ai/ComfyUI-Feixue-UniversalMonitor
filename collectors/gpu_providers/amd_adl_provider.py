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
from typing import Any, Dict, List, Optional, Tuple

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)


class _ADLWrapper:
    """ctypes 封装：加载 atiadlxx.dll 并映射关键函数。"""

    ADL_OK = 0
    _DLL_NAMES = ("atiadlxx.dll", "atiadlxy.dll")

    # ADL 内存分配回调类型：void* (*)(int size)
    # ADL_Main_Control_Create 的第一个参数是此类型的函数指针
    _AllocCallback = None  # 延迟初始化（需在 import ctypes 后定义）

    def __init__(self):
        self._dll: Any = None
        self._procs: Dict[str, Any] = {}
        self._buffer: List[Any] = []  # 保持回调分配的内存不被回收

    def load(self) -> bool:
        """尝试加载 AMD ADL DLL。"""
        import ctypes

        if platform.system() != "Windows":
            return False

        # 定义 ADL 内存分配回调类型（必须在设置 argtypes 前定义）
        # ADL_MAIN_MALLOC_CALLBACK: void* (*)(int)
        if _ADLWrapper._AllocCallback is None:
            _ADLWrapper._AllocCallback = ctypes.CFUNCTYPE(
                ctypes.c_void_p, ctypes.c_int
            )

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
            # 第一个参数是内存分配回调（函数指针），不是 POINTER(c_int)
            "ADL_Main_Control_Create": (_ADLWrapper._AllocCallback, int_arg),
            "ADL_Main_Control_Destroy": (),
            "ADL_Adapter_NumberOfAdapters_Get": (int_p,),
            "ADL_Adapter_AdapterInfo_Get": (ctypes.c_void_p, ctypes.c_int),
            "ADL_Adapter_Active_Get": (int_arg, ctypes.POINTER(ctypes.c_int)),
            # Overdrive5（旧 GCN 架构）
            "ADL_Overdrive5_Temperature_Get": (int_arg, int_arg, ctypes.c_void_p),
            "ADL_Overdrive5_CurrentActivity_Get": (int_arg, ctypes.c_void_p),
            # Overdrive6（GCN 1.2+ / Vega）
            "ADL_Overdrive6_CurrentPower_Get": (int_arg, int_arg, ctypes.c_void_p),
            "ADL_Overdrive6_Temperature_Get": (int_arg, ctypes.c_void_p),
            "ADL_Overdrive6_CurrentActivity_Get": (int_arg, ctypes.c_void_p),
            # Overdrive7（RDNA1/RDNA2 — RX 5000/6000 系列，如 RX 6800）
            "ADL_Overdrive7_CurrentActivity_Get": (int_arg, ctypes.c_void_p),
            # Overdrive8（RDNA3 — RX 7000 系列）
            "ADL_Overdrive8_CurrentActivity_Get": (int_arg, ctypes.c_void_p),
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

        # ADL 需要一个内存分配回调。使用与 argtypes 一致的 CFUNCTYPE 类型。
        # ADL_MAIN_MALLOC_CALLBACK: void* (*)(int)
        libc = ctypes.CDLL("msvcrt.dll")
        malloc_cb = _ADLWrapper._AllocCallback(libc.malloc)

        # ADL_Main_Control_Create 接收一个 ADL_MAIN_MEMORY_ALLOC 回调指针，
        # 和连接类型 1（默认连接）。
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
        """获取适配器信息列表。

        ADLAdapterInfo 结构体布局（ADL SDK 标准）：
          偏移 0:   iSize (int)
          偏移 4:   iAdapterIndex (int)
          偏移 8:   strUDID (char[256]) — 包含 "PCI_VEN_1002&DEV_..."
          偏移 276: iVendorID (int) — 十进制 1002 = AMD（不是 0x1002!）
          偏移 280: strAdapterName (char[256])

        策略：
        1. 如果 iSize > 0，用作条目大小
        2. 如果 iSize == 0（某些驱动版本），扫描 "PCI_VEN" 确定条目大小
        3. 用 strUDID 中的 "VEN_1002" 过滤 AMD 适配器（最可靠）
        4. 去重相同索引的适配器
        """
        import ctypes

        proc = self._procs.get("ADL_Adapter_AdapterInfo_Get")
        if proc is None or count <= 0:
            return []

        max_entry = 4096
        buf_size = max_entry * count
        buf = (ctypes.c_ubyte * buf_size)()

        ret = proc(ctypes.cast(buf, ctypes.c_void_p), buf_size)
        if ret != self.ADL_OK:
            logger.debug("adl-ctypes: ADL_Adapter_AdapterInfo_Get returned %d", ret)
            return []

        int_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_int))
        actual_entry_size = int_ptr[0]

        # 如果 iSize == 0（某些驱动版本不填此字段），扫描 "PCI_VEN" 确定条目大小
        if actual_entry_size <= 0 or actual_entry_size > max_entry:
            actual_entry_size = self._detect_entry_size(buf, buf_size, count)
            logger.debug("adl-ctypes: iSize=0, detected entry size=%d", actual_entry_size)

        logger.debug("adl-ctypes: ADLAdapterInfo entry_size=%d, count=%d", actual_entry_size, count)

        seen_indices = set()
        result = []

        for i in range(count):
            base = actual_entry_size * i
            if base + 280 >= buf_size:
                break

            # iAdapterIndex 在偏移 4
            adapter_index = int_ptr[base // 4 + 1]

            # strUDID 在偏移 8，用于判断是否 AMD
            udid_raw = bytes(buf[base + 8:base + 8 + 256])
            udid_null = udid_raw.find(b'\x00')
            udid = udid_raw[:udid_null].decode("ascii", errors="ignore") if udid_null > 0 else ""

            # 用 strUDID 中的 "VEN_1002" 过滤（最可靠，不依赖 iVendorID 偏移）
            if "VEN_1002" not in udid:
                logger.debug("adl-ctypes: adapter[%d] udid=%s (not AMD), skip", i, udid[:40])
                continue

            # 跳过无效索引
            if adapter_index < 0 or adapter_index >= count:
                continue

            # 去重
            if adapter_index in seen_indices:
                continue
            seen_indices.add(adapter_index)

            # strAdapterName 在偏移 280
            name = ""
            try:
                name_offset = base + 280
                raw = bytes(buf[name_offset:name_offset + 256])
                null_pos = raw.find(b'\x00')
                if null_pos > 0:
                    raw = raw[:null_pos]
                if raw:
                    name = raw.decode("ascii", errors="ignore").strip()
            except Exception:
                pass

            if not name:
                name = "AMD Radeon GPU"

            logger.debug("adl-ctypes: adapter[%d] index=%d name=%s", i, adapter_index, name)
            result.append({
                "index": adapter_index,
                "name": name,
            })

        return result

    @staticmethod
    def _detect_entry_size(buf, buf_size: int, count: int) -> int:
        """当 iSize=0 时，通过扫描 'PCI_VEN' 字符串确定条目大小。"""
        marker = b"PCI_VEN"
        positions = []
        start = 0
        while len(positions) < count + 1:
            pos = bytes(buf[start:buf_size]).find(marker)
            if pos < 0:
                break
            positions.append(start + pos)
            start = start + pos + 1

        if len(positions) >= 2:
            entry_size = positions[1] - positions[0]
            if 100 < entry_size < 4096:
                return entry_size

        # 回退：常见 ADLAdapterInfo 大小
        return 1536

    def get_activity(self, adapter_index: int) -> Optional[float]:
        """获取 GPU 利用率（百分比）。

        优先级：Overdrive8 → Overdrive7 → Overdrive5
        RX 6800 (RDNA2) 使用 Overdrive7，Overdrive5 返回失败。
        """
        # Overdrive7/8: ADLPMLogDataOutput 通道 6 = GPU_USAGE
        for od_ver in ("ADL_Overdrive8_CurrentActivity_Get",
                       "ADL_Overdrive7_CurrentActivity_Get"):
            proc = self._procs.get(od_ver)
            if proc is None:
                continue
            usage = self._get_pmlog_value(adapter_index, proc, 6)
            if usage is not None and usage >= 0:
                return float(usage)
            logger.debug("adl-ctypes: %s returned no usage", od_ver)

        # Overdrive5 降级
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

    def get_temperature(self, adapter_index: int) -> Optional[float]:
        """获取 GPU 温度（摄氏度）。

        优先级：Overdrive7/8 PMLog 通道 3 → Overdrive6 → Overdrive5
        """
        # Overdrive7/8: ADLPMLogDataOutput 通道 3 = TEMPERATURE_GPU (0.001°C)
        for od_ver in ("ADL_Overdrive8_CurrentActivity_Get",
                       "ADL_Overdrive7_CurrentActivity_Get"):
            proc = self._procs.get(od_ver)
            if proc is None:
                continue
            temp_raw = self._get_pmlog_value(adapter_index, proc, 3)
            if temp_raw is not None and temp_raw > 0:
                return round(temp_raw / 1000.0, 1)
            logger.debug("adl-ctypes: %s returned no temp", od_ver)

        # Overdrive6 降级
        proc = self._procs.get("ADL_Overdrive6_Temperature_Get")
        if proc is not None:
            class ADLTemperature6(ctypes.Structure):
                _fields_ = [("iSize", ctypes.c_int), ("iTemperature", ctypes.c_int)]
            temp = ADLTemperature6()
            temp.iSize = ctypes.sizeof(ADLTemperature6)
            ret = proc(adapter_index, ctypes.byref(temp))
            if ret == self.ADL_OK and temp.iTemperature > 0:
                return round(temp.iTemperature / 1000.0, 1)

        # Overdrive5 降级
        proc = self._procs.get("ADL_Overdrive5_Temperature_Get")
        if proc is None:
            return None

        class ADLTemperature(ctypes.Structure):
            _fields_ = [("iSize", ctypes.c_int), ("iTemperature", ctypes.c_int)]

        temp = ADLTemperature()
        temp.iSize = ctypes.sizeof(ADLTemperature)
        ret = proc(adapter_index, 0, ctypes.byref(temp))
        if ret != self.ADL_OK:
            return None
        return round(temp.iTemperature / 1000.0, 1)

    def get_power(self, adapter_index: int) -> Optional[float]:
        """获取 GPU 功耗（瓦特）。

        优先级：Overdrive7/8 PMLog 通道 7 → Overdrive6 CurrentPower
        """
        # Overdrive7/8: ADLPMLogDataOutput 通道 7 = GPU_POWER
        for od_ver in ("ADL_Overdrive8_CurrentActivity_Get",
                       "ADL_Overdrive7_CurrentActivity_Get"):
            proc = self._procs.get(od_ver)
            if proc is None:
                continue
            power_raw = self._get_pmlog_value(adapter_index, proc, 7)
            if power_raw is not None and power_raw > 0:
                # PMLog 功耗单位通常是 0.001W
                return round(power_raw / 1000.0, 1)

        # Overdrive6 CurrentPower 降级
        proc = self._procs.get("ADL_Overdrive6_CurrentPower_Get")
        if proc is None:
            return None
        power_val = ctypes.c_int(0)
        # 第二个参数 0 = GPU 总功耗
        ret = proc(adapter_index, 0, ctypes.byref(power_val))
        if ret != self.ADL_OK:
            return None
        return round(power_val.value / 1000.0, 1) if power_val.value > 0 else None

    def _get_pmlog_value(self, adapter_index: int, proc: Any, channel: int) -> Optional[int]:
        """调用 Overdrive7/8 CurrentActivity，从 ADLPMLogDataOutput 读取指定通道值。

        ADLPMLogDataOutput 布局：
          偏移 0:  iSize (int)
          偏移 4:  ulRevision (uint)
          偏移 8:  ulOutputFlags (uint)
          偏移 12: ulReserved[16] (64 字节)
          偏移 76: ulChannelIndex (uint)
          偏移 80: ulChannelValue[256] (1024 字节)

        通道值在偏移 80 + channel*4 处（unsigned int）。
        """
        import ctypes

        buf_size = 1200  # 80 + 256*4 = 1104，留余量
        buf = (ctypes.c_ubyte * buf_size)()
        # 设置 iSize
        int_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_int))
        int_ptr[0] = buf_size

        try:
            ret = proc(adapter_index, ctypes.cast(buf, ctypes.c_void_p))
        except Exception as e:
            logger.debug("adl-ctypes: PMLog call failed: %s", e)
            return None

        if ret != self.ADL_OK:
            logger.debug("adl-ctypes: PMLog returned %d for adapter %d", ret, adapter_index)
            return None

        # 读取通道值：偏移 80 + channel*4，作为 unsigned int
        uint_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint))
        value_offset = (80 + channel * 4) // 4
        if value_offset >= buf_size // 4:
            return None
        return int(uint_ptr[value_offset])

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
        super().__init__(name="amd-adl", priority=10, config=config)
        self._adl: Optional[_ADLWrapper] = None
        self._adapters: List[Dict[str, Any]] = []

    @property
    def priority(self) -> int:
        return 10

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
        power = self._adl.get_power(adapter_index)

        # VRAM：PyTorch 设备属性（物理显存大小，准确）
        # 若 PyTorch 不可用则返回 (0, 0)，由 DXGI 字段级降级补全
        vram_total, vram_used = self._get_pytorch_vram(device_id)

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
