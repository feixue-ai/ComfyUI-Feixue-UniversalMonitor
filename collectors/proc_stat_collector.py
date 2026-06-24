"""
Linux /proc/stat 解析器，用于高精度 CPU 使用率采集。

相比 psutil.cpu_percent，本模块直接读取内核暴露的原始 CPU 时间片计数，
避免 psutil 内部转换和额外的系统调用开销，在 Linux 上具有更高的准确性。

支持：
- 总 CPU 使用率与每核使用率
- 阻塞模式（interval > 0）与非阻塞模式（interval=None）
- 线程安全：每个实例独立维护历史状态，状态更新受锁保护
- 优雅降级：/proc/stat 不可读时抛出异常，由调用方决定是否回退到 psutil
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class CPUTimeSnapshot:
    """
    单个 CPU（总 CPU 或某逻辑核）在某一时刻的时间片快照。

    字段顺序与 /proc/stat 中的列保持一致：
    user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice。

    注意：
    - guest 已经包含在 user 中
    - guest_nice 已经包含在 nice 中
    因此计算 total/active 时不应重复累加这两个字段。
    """

    user: int
    nice: int
    system: int
    idle: int
    iowait: int
    irq: int
    softirq: int
    steal: int
    guest: int
    guest_nice: int
    timestamp: float

    @property
    def active(self) -> int:
        """
        活跃时间片 = 非空闲时间。

        Returns:
            活跃 CPU 时间片 tick 数。
        """
        return (
            self.user
            + self.nice
            + self.system
            + self.irq
            + self.softirq
            + self.steal
        )

    @property
    def total(self) -> int:
        """
        总时间片 = 活跃时间 + 空闲时间。

        Returns:
            总 CPU 时间片 tick 数（不重复计算 guest/guest_nice）。
        """
        return self.active + self.idle + self.iowait


class ProcStatCollector:
    """
    基于 /proc/stat 的 CPU 使用率采集器。

    用法::

        collector = ProcStatCollector()
        # 非阻塞（基于上一次状态）
        total, per_core = collector.get_cpu_percent(interval=None)
        # 阻塞 0.1 秒采样
        total, per_core = collector.get_cpu_percent(interval=0.1)

    线程安全：
        每个实例独立保存上一次采样状态，所有状态读写均受 _lock 保护。
    """

    PROC_STAT_PATH: Path = Path("/proc/stat")

    def __init__(self) -> None:
        """
        初始化采集器并探测 /proc/stat 是否可用。

        探测阶段会尝试读取一次 /proc/stat；
        若读取失败，available 属性为 False，后续调用会抛出异常。
        """
        self._logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._previous: Dict[str, CPUTimeSnapshot] = {}
        self._available: bool = self._probe()

    def _probe(self) -> bool:
        """
        探测 /proc/stat 是否可读且包含预期的 cpu 行。

        Returns:
            True 表示可用，False 表示不可用。
        """
        if not self.PROC_STAT_PATH.exists():
            self._logger.debug("%s 不存在，/proc/stat 不可用", self.PROC_STAT_PATH)
            return False
        try:
            snapshots = self._read_proc_stat()
            if "cpu" not in snapshots:
                self._logger.debug("/proc/stat 中未找到 aggregate cpu 行")
                return False
            return True
        except Exception as e:
            self._logger.debug("探测 /proc/stat 失败: %s", e)
            return False

    @property
    def available(self) -> bool:
        """
        /proc/stat 是否可用。

        Returns:
            True 表示可以正常采集，False 表示应回退到其他方案。
        """
        return self._available

    @classmethod
    def _read_proc_stat(cls) -> Dict[str, CPUTimeSnapshot]:
        """
        读取并解析 /proc/stat。

        Returns:
            {"cpu": aggregate_snapshot, "cpu0": core0_snapshot, ...}

        Raises:
            RuntimeError: 当文件格式异常或读取失败时。
        """
        snapshots: Dict[str, CPUTimeSnapshot] = {}
        try:
            with cls.PROC_STAT_PATH.open("r", encoding="utf-8") as f:
                now = time.monotonic()
                for line in f:
                    if not line.startswith("cpu"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    name = parts[0]
                    # 只保留 aggregate "cpu" 与 "cpuN" 行，忽略 "cpu0XXX" 等变体
                    if name != "cpu" and not (len(name) > 3 and name[3:].isdigit()):
                        continue

                    values = [int(x) for x in parts[1:]]
                    # /proc/stat 早期内核可能只有 7~8 列，缺省列补 0
                    while len(values) < 10:
                        values.append(0)

                    (
                        user,
                        nice,
                        system,
                        idle,
                        iowait,
                        irq,
                        softirq,
                        steal,
                        guest,
                        guest_nice,
                    ) = values[:10]

                    snapshots[name] = CPUTimeSnapshot(
                        user=user,
                        nice=nice,
                        system=system,
                        idle=idle,
                        iowait=iowait,
                        irq=irq,
                        softirq=softirq,
                        steal=steal,
                        guest=guest,
                        guest_nice=guest_nice,
                        timestamp=now,
                    )
        except (OSError, ValueError) as e:
            raise RuntimeError(f"读取 /proc/stat 失败: {e}") from e

        if "cpu" not in snapshots:
            raise RuntimeError("/proc/stat 中未找到 aggregate cpu 行")
        return snapshots

    @staticmethod
    def _calculate_utilization(
        prev: Dict[str, CPUTimeSnapshot],
        curr: Dict[str, CPUTimeSnapshot],
    ) -> Tuple[float, List[float]]:
        """
        根据两次快照计算总使用率与每核使用率。

        公式::

            utilization = (active_delta / total_delta) * 100

        Args:
            prev: 前一次快照。
            curr: 当前快照。

        Returns:
            (总使用率, 每核使用率列表)
        """
        cpu_prev = prev["cpu"]
        cpu_curr = curr["cpu"]

        total_delta = max(1, cpu_curr.total - cpu_prev.total)
        active_delta = max(0, cpu_curr.active - cpu_prev.active)
        total_util = (active_delta / total_delta) * 100.0

        per_core: List[float] = []
        core_names = sorted(
            [k for k in curr.keys() if k != "cpu" and k.startswith("cpu")],
            key=lambda n: int(n[3:]),
        )
        for name in core_names:
            if name not in prev:
                per_core.append(0.0)
                continue
            core_prev = prev[name]
            core_curr = curr[name]
            core_total = max(1, core_curr.total - core_prev.total)
            core_active = max(0, core_curr.active - core_prev.active)
            per_core.append((core_active / core_total) * 100.0)

        return total_util, per_core

    def get_cpu_percent(
        self, interval: Optional[float] = None
    ) -> Tuple[float, List[float]]:
        """
        获取 CPU 使用率。

        Args:
            interval: 采样间隔。
                - None：非阻塞，使用实例中保存的上一次状态计算；
                  若这是首次调用，则返回 0.0 并建立初始状态。
                - 大于 0 的浮点数：阻塞采样，等待 interval 秒后再次读取。

        Returns:
            (总 CPU 使用率, 每核 CPU 使用率列表)

        Raises:
            RuntimeError: /proc/stat 不可用或读取失败。
        """
        if not self._available:
            raise RuntimeError("ProcStatCollector: /proc/stat 不可用")

        with self._lock:
            if interval is not None and interval > 0:
                # 阻塞模式：连续两次采样，中间 sleep
                first = self._read_proc_stat()
                time.sleep(interval)
                second = self._read_proc_stat()
                result = self._calculate_utilization(first, second)
                self._previous = second
                return result

            # 非阻塞模式
            if not self._previous:
                self._previous = self._read_proc_stat()
                # 首次无历史基准，按 psutil 惯例返回 0.0
                return 0.0, []

            current = self._read_proc_stat()
            result = self._calculate_utilization(self._previous, current)
            self._previous = current
            return result

    def warm_up(self, interval: float = 0.1) -> bool:
        """
        预热采集器，建立初始历史基准。

        预热后首次非阻塞调用即可返回真实使用率，而不是 0.0。

        Args:
            interval: 预热采样间隔，默认 0.1 秒。

        Returns:
            True 表示预热成功，False 表示失败。
        """
        if not self._available:
            return False
        try:
            self.get_cpu_percent(interval=interval)
            return True
        except Exception as e:
            self._logger.warning("ProcStatCollector 预热失败: %s", e)
            return False
