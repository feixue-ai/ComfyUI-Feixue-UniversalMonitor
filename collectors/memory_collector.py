"""
内存（RAM）数据采集器模块。

提供跨平台的物理内存和交换分区数据采集功能。
"""

from collectors.base import BaseCollector
from core.data_models import RAMMetrics
import logging
import platform

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore
    _HAS_PSUTIL = False


class RAMCollector(BaseCollector[RAMMetrics]):
    """
    内存数据采集器。

    采集指标：
    - 物理内存已用/总量/百分比 (MB)
    - 交换分区已用/总量 (MB)
    - 缓存占用 (MB)
    - 可用内存 (MB)

    平台差异说明：
    - Linux: 完整支持，包含 cached 字段
    - Windows: 基本支持，cached 为 0
    - macOS: 基本支持，cached 可能不准确

    Examples::

        >>> collector = RAMCollector()
        >>> metrics = collector.safe_collect()
        >>> if metrics:
        ...     print(f"内存使用: {metrics.ram_used}/{metrics.ram_total} MB")
        ...     print(f"使用率: {metrics.ram_percent}%")
        ...     print(f"可用内存: {metrics.available} MB")

    Performance::
        单次采集耗时 < 10ms（纯内存读取操作）
    """

    def __init__(self):
        """
        初始化内存采集器。

        配置说明：
        - timeout=1.0s: 超时保护（实际采集远快于此）
        - enabled=True: 默认启用
        - retry_count=1: 失败时重试 1 次
        """
        super().__init__(
            name="ram_collector",
            timeout=1.0,
            enabled=True,
            retry_count=1
        )

    def collect(self) -> RAMMetrics:
        """
        执行内存数据采集。

        采集流程：
        1. 获取物理内存信息（总量、已用、可用、百分比、缓存）
        2. 获取交换分区信息（总量、已用）
        3. 单位转换：bytes -> MB
        4. 构造并返回 RAMMetrics 对象

        Returns:
            RAMMetrics: 包含完整内存指标的数据对象

        Note:
            所有数值单位统一为 MB（兆字节），避免 GB 换算的浮点精度问题。
            使用整数除法确保返回值为 int 类型。

        Raises:
            DataCollectionError: 当 psutil 调用失败时（由基类 safe_collect 捕获）
        """
        if _HAS_PSUTIL:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            return RAMMetrics(
                ram_used=int(mem.used // (1024 * 1024)),
                ram_total=int(mem.total // (1024 * 1024)),
                ram_percent=float(mem.percent),
                swap_used=int(swap.used // (1024 * 1024)),
                swap_total=int(swap.total // (1024 * 1024)),
                cached=int(getattr(mem, 'cached', 0) // (1024 * 1024)),
                available=int(mem.available // (1024 * 1024))
            )

        # psutil 不可用时，Linux 通过 /proc/meminfo 零依赖采集
        if platform.system() == "Linux":
            return self._collect_from_proc_meminfo()

        logging.warning("RAMCollector: psutil not available and no fallback for %s", platform.system())
        return RAMMetrics(ram_used=0, ram_total=0, ram_percent=0.0,
                          swap_used=0, swap_total=0, cached=0, available=0)

    def _collect_from_proc_meminfo(self) -> RAMMetrics:
        """从 /proc/meminfo 读取内存指标（无 psutil 时 Linux fallback）。"""
        data: dict = {}
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if ":" in line:
                        key, value = line.split(":", 1)
                        data[key.strip().lower()] = int(value.strip().split()[0])  # kB
        except Exception as e:
            logging.warning("RAMCollector: failed to read /proc/meminfo: %s", e)
            return RAMMetrics(ram_used=0, ram_total=0, ram_percent=0.0,
                              swap_used=0, swap_total=0, cached=0, available=0)

        total_kb = data.get("memtotal", 0)
        free_kb = data.get("memfree", 0)
        avail_kb = data.get("memavailable", free_kb)
        buffers_kb = data.get("buffers", 0)
        cached_kb = data.get("cached", 0)
        sreclaimable_kb = data.get("sreclaimable", 0)
        swaptotal_kb = data.get("swaptotal", 0)
        swapfree_kb = data.get("swapfree", 0)

        used_kb = total_kb - free_kb - buffers_kb - cached_kb - sreclaimable_kb
        used_kb = max(0, used_kb)
        percent = round(used_kb / total_kb * 100, 1) if total_kb else 0.0

        return RAMMetrics(
            ram_used=used_kb // 1024,
            ram_total=total_kb // 1024,
            ram_percent=percent,
            swap_used=(swaptotal_kb - swapfree_kb) // 1024,
            swap_total=swaptotal_kb // 1024,
            cached=(cached_kb + sreclaimable_kb) // 1024,
            available=avail_kb // 1024,
        )
