"""
内存（RAM）数据采集器模块。

提供跨平台的物理内存和交换分区数据采集功能。
"""

from collectors.base import BaseCollector
from core.data_models import RAMMetrics
import psutil
import logging


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
        # 1. 物理内存信息
        mem = psutil.virtual_memory()

        # 2. 交换分区信息
        swap = psutil.swap_memory()

        # 3-4. 构造 RAMMetrics 对象（单位：bytes -> MB）
        return RAMMetrics(
            ram_used=int(mem.used // (1024 * 1024)),       # bytes → MB
            ram_total=int(mem.total // (1024 * 1024)),
            ram_percent=float(mem.percent),
            swap_used=int(swap.used // (1024 * 1024)),
            swap_total=int(swap.total // (1024 * 1024)),
            cached=int(getattr(mem, 'cached', 0) // (1024 * 1024)),
            available=int(mem.available // (1024 * 1024))
        )
