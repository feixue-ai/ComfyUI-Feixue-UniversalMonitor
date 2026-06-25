"""
Windows DXGI VRAM Provider — 通过 COM vtable 获取与任务管理器同步的 VRAM 数据

DXGI（DirectX Graphics Infrastructure）是微软的 COM 接口，ABI 官方稳定，
ctypes 调用安全可靠。

数据获取策略（分两级）：
1. IDXGIAdapter3::QueryVideoMemoryInfo — 返回 CurrentUsage/Budget（已用/总量）
   与 Windows 任务管理器同源（WDDM 驱动层）。需要 DXGI 1.4+ 运行时。
2. IDXGIAdapter1::GetDesc1 — 仅返回 DedicatedVideoMemory（总量）
   作为 IDXGIAdapter3 不可用时的降级。

用途：作为 ADLX VRAM 字段的降级保底（priority=20），仅提供 VRAM 数据。
当 ADLX bridge DLL 的 VRAM 数据无效时，从此 Provider 补全 VRAM 字段。

Version: 1.1.0
Author: Feixue Team
"""

from __future__ import annotations

import ctypes
import logging
import platform
from typing import Optional

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)

# AMD 厂商 ID
_AMD_VENDOR_ID = 0x1002
# NVIDIA 厂商 ID
_NVIDIA_VENDOR_ID = 0x10DE


class _GUID(ctypes.Structure):
    """Windows GUID 结构体（与 byte 数组内存布局一致，但类型安全）。"""

    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _make_guid(a: int, b: int, c: int, d: tuple) -> _GUID:
    return _GUID(a, b, c, (ctypes.c_ubyte * 8)(*d))


# IID_IDXGIFactory1 = {770aae78-f26f-4dba-a829-253c83d1b387}
_IID_IDXGIFactory1 = _make_guid(
    0x770AAE78, 0xF26F, 0x4DBA, (0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87)
)

# IID_IDXGIAdapter3 = {645967a6-3d97-4c89-9b73-854f6fc37233}
_IID_IDXGIAdapter3 = _make_guid(
    0x645967A6, 0x3D97, 0x4C89, (0x9B, 0x73, 0x85, 0x4F, 0x6F, 0xC3, 0x72, 0x33)
)

# DXGI_MEMORY_SEGMENT_GROUP
_DXGI_MEMORY_SEGMENT_GROUP_LOCAL = 0


class _DXGI_ADAPTER_DESC1(ctypes.Structure):
    """DXGI_ADAPTER_DESC1 结构体。"""

    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint),
        ("DeviceId", ctypes.c_uint),
        ("SubSysId", ctypes.c_uint),
        ("Revision", ctypes.c_uint),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", ctypes.c_int64),
        ("Flags", ctypes.c_uint),
    ]


class _DXGI_QUERY_VIDEO_MEMORY_INFO(ctypes.Structure):
    """DXGI_QUERY_VIDEO_MEMORY_INFO 结构体。"""

    _fields_ = [
        ("Budget", ctypes.c_uint64),
        ("CurrentUsage", ctypes.c_uint64),
        ("AvailableForReservation", ctypes.c_uint64),
        ("CurrentReservation", ctypes.c_uint64),
    ]


def _read_vtable_func(vtable_ptr: int, slot: int, restype, *argtypes):
    """从 COM vtable 指定 slot 读取函数指针并构造 CFUNCTYPE。"""
    func_ptr = ctypes.c_void_p.from_address(
        vtable_ptr + slot * ctypes.sizeof(ctypes.c_void_p)
    ).value
    return ctypes.CFUNCTYPE(restype, *argtypes)(func_ptr)


class _DXGIVramReader:
    """DXGI COM vtable 封装（仅 VRAM 读取）。

    两级数据获取：
    - Level 1: IDXGIAdapter3::QueryVideoMemoryInfo（已用+总量，需 DXGI 1.4+）
    - Level 2: IDXGIAdapter1::GetDesc1（仅总量，兼容所有 DXGI 版本）
    """

    def __init__(self):
        self._dxgi_dll: Optional[ctypes.CDLL] = None
        self._factory: Optional[int] = None
        # [(adapter_ptr_val, adapter3_ptr_val_or_0, desc1, index)]
        self._adapters: list = []
        self._initialized = False

    def initialize(self) -> bool:
        """初始化 DXGI，枚举适配器，缓存 AMD/NVIDIA 适配器信息。"""
        if platform.system() != "Windows":
            return False

        try:
            self._dxgi_dll = ctypes.windll.dxgi
        except (OSError, AttributeError):
            try:
                self._dxgi_dll = ctypes.CDLL("dxgi.dll")
            except OSError:
                logger.debug("dxgi: dxgi.dll 加载失败")
                return False

        # CreateDXGIFactory1(IID*, void**)
        create_factory = getattr(self._dxgi_dll, "CreateDXGIFactory1", None)
        if create_factory is None:
            logger.debug("dxgi: CreateDXGIFactory1 不存在")
            return False

        try:
            create_factory.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
            create_factory.restype = ctypes.c_long
        except Exception:
            pass  # windll 可能不支持设置 argtypes

        factory_ptr = ctypes.c_void_p()
        try:
            hr = create_factory(ctypes.byref(_IID_IDXGIFactory1), ctypes.byref(factory_ptr))
        except Exception as e:
            logger.debug("dxgi: CreateDXGIFactory1 调用异常: %s", e)
            return False

        if hr != 0 or not factory_ptr.value:
            logger.debug("dxgi: CreateDXGIFactory1 失败 hr=0x%08x", hr & 0xFFFFFFFF)
            return False

        self._factory = factory_ptr.value

        # IDXGIFactory1 vtable: EnumAdapters1 在 slot 12
        factory_vtable = ctypes.c_void_p.from_address(self._factory).value
        EnumAdapters1 = _read_vtable_func(
            factory_vtable, 12,
            ctypes.c_long,  # HRESULT
            ctypes.c_void_p,  # this
            ctypes.c_uint,   # Adapter index
            ctypes.POINTER(ctypes.c_void_p),  # ppAdapter
        )

        # 枚举适配器
        index = 0
        while True:
            adapter_ptr = ctypes.c_void_p()
            hr = EnumAdapters1(factory_ptr, index, ctypes.byref(adapter_ptr))
            if hr != 0 or not adapter_ptr.value:
                break

            # GetDesc1 在 IDXGIAdapter1 vtable slot 10
            adapter_vtable = ctypes.c_void_p.from_address(adapter_ptr.value).value
            GetDesc1 = _read_vtable_func(
                adapter_vtable, 10,
                ctypes.c_long,  # HRESULT
                ctypes.c_void_p,  # this
                ctypes.POINTER(_DXGI_ADAPTER_DESC1),
            )

            desc = _DXGI_ADAPTER_DESC1()
            hr = GetDesc1(adapter_ptr, ctypes.byref(desc))
            if hr != 0:
                index += 1
                continue

            # 仅缓存 AMD 和 NVIDIA 适配器
            if desc.VendorId in (_AMD_VENDOR_ID, _NVIDIA_VENDOR_ID):
                # 尝试 QueryInterface 获取 IDXGIAdapter3（可能不支持）
                adapter3_val = self._try_query_adapter3(adapter_ptr, adapter_vtable)
                self._adapters.append((adapter_ptr.value, adapter3_val, desc, index))
                logger.debug(
                    "dxgi: 缓存适配器 [%d] %s (vendor=0x%04x, VRAM=%d MB, Adapter3=%s)",
                    index, desc.Description[:32], desc.VendorId,
                    desc.DedicatedVideoMemory // (1024 * 1024),
                    "yes" if adapter3_val else "no",
                )

            index += 1

        if not self._adapters:
            logger.debug("dxgi: 未找到 AMD/NVIDIA 适配器")
            self._cleanup()
            return False

        self._initialized = True
        return True

    def _try_query_adapter3(self, adapter_ptr: ctypes.c_void_p, adapter_vtable: int) -> int:
        """尝试 QueryInterface 获取 IDXGIAdapter3，失败返回 0。"""
        try:
            QueryInterface = _read_vtable_func(
                adapter_vtable, 0,  # IUnknown::QueryInterface = slot 0
                ctypes.c_long,  # HRESULT
                ctypes.c_void_p,  # this
                ctypes.POINTER(_GUID),  # riid
                ctypes.POINTER(ctypes.c_void_p),  # ppvObject
            )
            adapter3_ptr = ctypes.c_void_p()
            hr = QueryInterface(
                adapter_ptr,
                ctypes.byref(_IID_IDXGIAdapter3),
                ctypes.byref(adapter3_ptr),
            )
            if hr == 0 and adapter3_ptr.value:
                return adapter3_ptr.value
        except Exception as e:
            logger.debug("dxgi: QueryInterface(IDXGIAdapter3) 异常: %s", e)
        return 0

    def get_vram(self, device_id: int = 0) -> tuple:
        """获取指定 GPU 的 VRAM (used_mb, total_mb)。

        优先使用 IDXGIAdapter3::QueryVideoMemoryInfo（已用+总量），
        降级使用 GetDesc1::DedicatedVideoMemory（仅总量，used=0）。

        Returns:
            (vram_used_mb, vram_total_mb)，失败返回 (0, 0)
        """
        if not self._initialized or device_id < 0 or device_id >= len(self._adapters):
            return 0, 0

        adapter_val, adapter3_val, desc, _ = self._adapters[device_id]

        # Level 1: IDXGIAdapter3::QueryVideoMemoryInfo（已用+总量）
        if adapter3_val:
            try:
                vram_used, vram_total = self._query_video_memory(adapter3_val)
                if vram_total > 0:
                    return vram_used, vram_total
            except Exception as e:
                logger.debug("dxgi: QueryVideoMemoryInfo 异常 (device %d): %s", device_id, e)

        # Level 2: GetDesc1 的 DedicatedVideoMemory（仅总量，used=0）
        vram_total_mb = int(desc.DedicatedVideoMemory // (1024 * 1024))
        return 0, vram_total_mb

    def _query_video_memory(self, adapter3_val: int) -> tuple:
        """通过 IDXGIAdapter3::QueryVideoMemoryInfo 获取 VRAM。"""
        adapter3_vtable = ctypes.c_void_p.from_address(adapter3_val).value
        QueryVideoMemoryInfo = _read_vtable_func(
            adapter3_vtable, 12,  # IDXGIAdapter3::QueryVideoMemoryInfo = slot 12
            ctypes.c_long,  # HRESULT
            ctypes.c_void_p,  # this
            ctypes.c_uint,   # NodeIndex
            ctypes.c_uint,   # MemorySegmentGroup
            ctypes.POINTER(_DXGI_QUERY_VIDEO_MEMORY_INFO),
        )

        info = _DXGI_QUERY_VIDEO_MEMORY_INFO()
        hr = QueryVideoMemoryInfo(
            ctypes.c_void_p(adapter3_val),
            0,  # NodeIndex
            _DXGI_MEMORY_SEGMENT_GROUP_LOCAL,
            ctypes.byref(info),
        )

        if hr != 0:
            return 0, 0

        vram_used_mb = int(info.CurrentUsage // (1024 * 1024))
        vram_total_mb = int(info.Budget // (1024 * 1024))
        return vram_used_mb, vram_total_mb

    def get_adapter_count(self) -> int:
        return len(self._adapters)

    def get_adapter_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._adapters):
            return self._adapters[device_id][2].Description
        return f"GPU {device_id}"

    def _cleanup(self):
        """释放所有 COM 对象。"""
        for adapter_val, adapter3_val, _, _ in self._adapters:
            if adapter3_val:
                self._release_com(adapter3_val)
            self._release_com(adapter_val)

        self._adapters.clear()

        if self._factory:
            self._release_com(self._factory)
            self._factory = None

        self._initialized = False

    @staticmethod
    def _release_com(ptr_val: int):
        """调用 IUnknown::Release (vtable slot 2)。"""
        try:
            vtable = ctypes.c_void_p.from_address(ptr_val).value
            Release = _read_vtable_func(
                vtable, 2,
                ctypes.c_ulong,  # ULONG
                ctypes.c_void_p,  # this
            )
            Release(ctypes.c_void_p(ptr_val))
        except Exception:
            pass


class DXGIProvider(BaseGPUProvider):
    """Windows DXGI VRAM Provider（字段级降级保底）。

    priority=20，仅提供 VRAM 数据（与任务管理器同源）。
    当 ADLX bridge 的 VRAM 无效时，从此 Provider 补全。
    """

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="dxgi", priority=20, config=config)
        self._reader: Optional[_DXGIVramReader] = None

    def initialize(self) -> bool:
        if platform.system() != "Windows":
            return False
        if self._initialized:
            return True

        self._reader = _DXGIVramReader()
        if not self._reader.initialize():
            logger.debug("dxgi: 初始化失败（可能无独立显卡或 DXGI 版本受限）")
            self._reader = None
            return False

        self._device_count = self._reader.get_adapter_count()
        self._device_names = [
            self._reader.get_adapter_name(i) for i in range(self._device_count)
        ]
        self._initialized = True
        logger.info(
            "dxgi: ✅ 初始化成功，%d 个适配器: %s",
            self._device_count,
            ", ".join(self._device_names),
        )
        return True

    def shutdown(self) -> None:
        if self._reader is not None:
            self._reader._cleanup()
            self._reader = None
        self._initialized = False
        self._device_count = 0
        self._device_names = []

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"GPU {device_id}"

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """仅返回 VRAM 数据（其他字段为 0/None，由聚合层补全）。"""
        if not self._initialized or self._reader is None:
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        vram_used, vram_total = self._reader.get_vram(device_id)
        return GPUMetrics(
            gpu_utilization=0.0,
            vram_used=vram_used,
            vram_total=vram_total,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
        )

    def get_vram(self, device_id: int = 0) -> tuple:
        """直接获取 VRAM（used_mb, total_mb），供字段级降级调用。"""
        if not self._initialized or self._reader is None:
            return 0, 0
        return self._reader.get_vram(device_id)
