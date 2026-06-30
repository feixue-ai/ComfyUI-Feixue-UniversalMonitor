"""
ComfyUI-Feixue-UniversalMonitor - 数据采集层抽象基类体系

本模块定义了整个数据采集层的核心抽象接口，采用策略模式 + 模板方法模式设计。

模块职责：
1. BaseCollector: 一次性采集模式的泛型抽象基类（支持 CPU/RAM/GPU 等各类采集器）
2. BaseGPUProvider: 连接会话模式的 GPU 数据提供者抽象基类（生命周期管理）
3. CollectorRegistry: 全局采集器和 Provider 注册表（线程安全单例）

设计原则：
- 开闭原则：对扩展开放（添加新 Collector/Provider），对修改关闭
- 里氏替换原则：任何子类都可以替换父类使用
- 依赖倒置原则：高层模块依赖抽象基类，不依赖具体实现
- 接口隔离原则：BaseGPUProvider 接口粒度合理
- 异常隔离：采集失败不影响其他采集器
- 超时保护：防止某个采集器阻塞整个系统
- 可观测性：记录采集耗时和成功率

版本: 2.0.0 (重构版)
作者: Feixue
"""

from __future__ import annotations

import abc
import logging
import threading
import time
from typing import Any, Dict, Generic, List, Optional, TypeVar

from core.data_models import (
    CPUMetrics,
    DataCollectionError,
    GPUMetrics,
    MonitorError,
    RAMMetrics,
)
from fxm_utils.thread_safe import execute_with_timeout, retry_on_failure


# ============================================================================
# 类型变量定义
# ============================================================================

T = TypeVar("T")


# ============================================================================
# 异常定义（采集层专用）
# ============================================================================

class CollectorError(Exception):
    """采集器基础异常

    所有采集层异常的基类，与 core.data_models.MonitorError 区分：
    - MonitorError: 核心业务异常（数据校验、配置错误等）
    - CollectorError: 采集层运行时异常（超时、设备未找到、权限不足等）
    """

    pass


class InitializationError(CollectorError):
    """初始化失败异常

    当 Provider 或 Collector 的依赖库缺失、连接建立失败时抛出。
    """
    pass


class DeviceNotFoundError(CollectorError):
    """设备未找到异常

    当请求的 GPU device_id 不在有效范围内时抛出。
    """
    pass


class PermissionDeniedError(CollectorError):
    """权限不足异常

    当需要 root/admin 权限但当前用户不具备时抛出。
    """
    pass


class DependencyNotFoundError(CollectorError):
    """依赖库未找到异常

    当必需的外部库（如 pynvml、amdsmi）未安装时抛出。
    """
    pass


class CollectionTimeoutError(CollectorError):
    """采集超时异常

    当数据采集操作超过设定的超时时间限制时抛出。
    """

    def __init__(self, collector_name: str, timeout: float):
        self.collector_name = collector_name
        self.timeout = timeout
        super().__init__(
            f"Collection '{collector_name}' timed out after {timeout:.1f}s"
        )


# ============================================================================
# 1. BaseCollector - 数据采集器抽象基类（泛型）
# ============================================================================

class BaseCollector(abc.ABC, Generic[T]):
    """
    数据采集器抽象基类。

    所有具体的采集器（CPU、RAM、GPU 等）都必须继承此类，
    并实现 collect() 方法。

    设计原则：
    - 单一职责：每个采集器只负责一种指标类型
    - 异常隔离：采集失败不影响其他采集器
    - 超时保护：防止某个采集器阻塞整个系统
    - 可观测性：记录采集耗时和成功率
    - 泛型支持：通过 Generic[T] 实现强类型约束

    使用示例::

        class MyCollector(BaseCollector[MyDataType]):
            def __init__(self):
                super().__init__(name="my_collector", timeout=2.0)

            def collect(self) -> MyDataType:
                # 实际的数据采集逻辑
                return MyDataType(...)

        collector = MyCollector()
        data = collector.safe_collect()  # 安全调用，异常时返回 None

    继承关系::

        BaseCollector[T]
        ├── CPUCollector(BaseCollector[CPUMetrics])
        ├── RAMCollector(BaseCollector[RAMMetrics])
        ├── GPUCollector(BaseCollector[List[GPUMetrics]])
        └── PowerCollector(BaseCollector[Dict[int, float]])
    """

    def __init__(
        self,
        name: str,
        timeout: float = 2.0,
        enabled: bool = True,
        retry_count: int = 1,
    ):
        """
        初始化采集器。

        Args:
            name: 采集器唯一标识名称（用于日志和注册表查找）
            timeout: 单次采集的超时时间（秒），默认 2.0 秒
            enabled: 是否启用该采集器，禁用后 safe_collect() 直接返回默认值
            retry_count: 失败重试次数，0 表示不重试，默认 1 次

        Raises:
            ValueError: 如果 timeout 或 retry_count 为负数
        """
        if timeout < 0:
            raise ValueError(f"timeout must be non-negative, got {timeout}")
        if retry_count < 0:
            raise ValueError(f"retry_count must be non-negative, got {retry_count}")

        self.name = name
        self.timeout = timeout
        self.enabled = enabled
        self.retry_count = retry_count
        self.logger = logging.getLogger(f"{__name__}.{name}")

        # ----- 统计信息 -----
        self._total_collections: int = 0
        self._successful_collections: int = 0
        self._failed_collections: int = 0
        self._total_collection_time: float = 0.0
        self._last_collection_time: Optional[float] = None
        self._last_error: Optional[Exception] = None

    @abc.abstractmethod
    def collect(self) -> T:
        """
        执行实际的数据采集逻辑。

        子类必须实现此方法。实现时应注意：
        - 保持方法轻量级，避免重量级 I/O 操作
        - 失败时抛出 DataCollectionError 或其子类
        - 不应在此方法中处理异常（由 safe_collect 统一处理）

        Returns:
            采集到的数据对象，具体类型由泛型参数 T 决定

        Raises:
            DataCollectionError: 采集失败时应抛出此异常
        """
        ...

    def safe_collect(self, default: Optional[T] = None) -> Optional[T]:
        """
        带异常捕获的安全调用入口。

        自动处理以下场景：
        - 采集器被禁用时直接返回默认值
        - 超时保护（通过 execute_with_timeout 实现）
        - 异常捕获和日志记录
        - 统计信息更新（成功/失败计数、耗时统计）
        - 重试机制（如果配置了 retry_count > 0）

        Args:
            default: 采集失败时返回的默认值，默认为 None

        Returns:
            采集成功返回数据对象（类型 T），失败返回 default

        示例::

            cpu_collector = CPUCollector(name="cpu", timeout=1.5)

            # 正常使用
            metrics = cpu_collector.safe_collect()
            if metrics is not None:
                print(f"CPU 使用率: {metrics.cpu_utilization}%")

            # 自定义默认值
            fallback = CPUMetrics(
                cpu_utilization=0.0, cpu_count=1, cpu_freq=0.0,
                per_core_usage=[0.0]
            )
            metrics = cpu_collector.safe_collect(default=fallback)
        """
        if not self.enabled:
            self.logger.debug("Collector '%s' is disabled, skipping", self.name)
            return default

        start_time = time.time()

        try:
            if self.retry_count > 0:
                # 使用重试机制包装 collect() 调用
                result = self._collect_with_retry()
            else:
                # 无重试模式：直接调用（带超时保护）
                timeout_result = execute_with_timeout(
                    func=self.collect,
                    timeout=self.timeout,
                    default=default,
                )
                if not timeout_result.success:
                    raise timeout_result.error or CollectionTimeoutError(
                        self.name, self.timeout
                    )
                result = timeout_result.data

            # 更新成功统计
            self._successful_collections += 1
            elapsed = time.time() - start_time
            self._last_collection_time = elapsed
            self._total_collection_time += elapsed
            self._last_error = None

            return result

        except Exception as e:
            # 更新失败统计
            self._failed_collections += 1
            self._last_error = e
            self.logger.warning(
                "Collector '%s' failed: %s", self.name, e
            )
            return default

        finally:
            self._total_collections += 1

    def _collect_with_retry(self) -> T:
        """
        带重试机制的内部采集方法。

        使用 retry_on_failure 装饰器包装 collect() 调用，
        在每次重试之间应用指数退避策略。

        内部实现细节：
        - 重试次数 = self.retry_count（即总共尝试 retry_count + 1 次）
        - 退避延迟从 0.05 秒开始，退避因子为 2.0
        - 每次重试都受 self.timeout 保护

        Returns:
            采集成功的返回值

        Raises:
            Exception: 所有重试耗尽后抛出的最后一次异常
        """
        # 构建带超时的采集函数
        def _timed_collect() -> T:
            timeout_result = execute_with_timeout(
                func=self.collect,
                timeout=self.timeout,
            )
            if not timeout_result.success:
                raise timeout_result.error or CollectionTimeoutError(
                    self.name, self.timeout
                )
            return timeout_result.data

        # 应用重试装饰器
        retry_decorator = retry_on_failure(
            max_retries=self.retry_count,
            delay=0.05,
            backoff=2.0,
            exceptions=(Exception,),  # 重试所有异常
        )
        return retry_decorator(_timed_collect)()

    # ----- 统计属性 -----

    @property
    def success_rate(self) -> float:
        """
        采集成功率 (0-100%)。

        基于 _total_collections 和 _successful_collections 计算，
        首次调用前（无任何采集记录）返回 100.0 以避免除零。

        Returns:
            成功率百分比，范围 [0.0, 100.0]
        """
        if self._total_collections == 0:
            return 100.0
        return (self._successful_collections / self._total_collections) * 100

    @property
    def avg_collection_time(self) -> float:
        """
        平均采集耗时（秒）。

        仅基于成功采集计算平均值，
        避免因长时间阻塞的失败采集拉高平均值。

        Returns:
            平均耗时（秒），无成功记录时返回 0.0
        """
        if self._successful_collections == 0:
            return 0.0
        return self._total_collection_time / self._successful_collections

    @property
    def stats(self) -> Dict[str, Any]:
        """
        完整统计信息字典。

        返回当前采集器的所有运行时统计数据，
        用于调试、监控面板展示和性能分析。

        Returns:
            包含以下键的字典：

            .. code-block:: python

                {
                    'name': str,           # 采集器名称
                    'enabled': bool,       # 是否启用
                    'total': int,          # 总采集次数
                    'successful': int,     # 成功次数
                    'failed': int,         # 失败次数
                    'success_rate': float, # 成功率 (%)
                    'avg_time_ms': float,  # 平均耗时 (ms)
                    'last_time_ms': float, # 最近一次耗时 (ms)
                    'last_error': str|None # 最近一次错误信息
                }
        """
        return {
            "name": self.name,
            "enabled": self.enabled,
            "total": self._total_collections,
            "successful": self._successful_collections,
            "failed": self._failed_collections,
            "success_rate": round(self.success_rate, 2),
            "avg_time_ms": round(self.avg_collection_time * 1000, 2),
            "last_time_ms": round((self._last_collection_time or 0) * 1000, 2),
            "last_error": str(self._last_error) if self._last_error else None,
        }

    def reset_stats(self) -> None:
        """
        重置所有统计信息归零。

        通常在以下场景调用：
        - 采集器重新初始化后
        - 定期统计窗口切换时
        - 调试测试前后
        """
        self._total_collections = 0
        self._successful_collections = 0
        self._failed_collections = 0
        self._total_collection_time = 0.0
        self._last_collection_time = None
        self._last_error = None
        self.logger.debug("Stats reset for collector '%s'", self.name)

    # ----- 启停控制 -----

    def enable(self) -> None:
        """
        启用采集器。

        启用后 safe_collect() 将正常执行采集逻辑。
        """
        self.enabled = True
        self.logger.debug("Collector '%s' enabled", self.name)

    def disable(self) -> None:
        """
        禁用采集器。

        禁用后 safe_collect() 将跳过采集并直接返回 default 值，
        适用于临时排除有问题的采集器而不影响整体系统运行。
        """
        self.enabled = False
        self.logger.debug("Collector '%s' disabled", self.name)


# ============================================================================
# 具体采集器类型定义（基于 BaseCollector 的特化）
# ============================================================================

class CPUCollector(BaseCollector[CPUMetrics]):
    """
    CPU 数据采集器。

    继承 BaseCollector[CPUMetrics]，强制 collect() 返回 CPUMetrics 类型。

    子类需要实现的平台适配：
    - Linux: 通过 /proc/stat、psutil 或 os 读取
    - Windows: 通过 WMI 或 psutil 读取
    - macOS: 通过 host_statistics 或 psutil 读取
    """

    @abc.abstractmethod
    def collect(self) -> CPUMetrics:
        ...


class RAMCollector(BaseCollector[RAMMetrics]):
    """
    内存（RAM）数据采集器。

    继承 BaseCollector[RAMMetrics]，强制 collect() 返回 RAMMetrics 类型。

    采集内容包括物理内存和交换分区的使用情况。
    """

    @abc.abstractmethod
    def collect(self) -> RAMMetrics:
        ...


class GPUCollector(BaseCollector[List[GPUMetrics]]):
    """
    GPU 数据采集器。

    继承 BaseCollector[List[GPUMetrics]]，支持多卡场景。
    collect() 返回所有可用 GPU 的指标列表。

    注意：此类通常不直接实例化，而是通过 BaseGPUProvider 组合使用。
    """

    @abc.abstractmethod
    def collect(self) -> List[GPUMetrics]:
        """返回所有 GPU 的指标列表"""
        ...

    @abc.abstractmethod
    def collect_device(self, device_id: int) -> GPUMetrics:
        """
        采集指定设备的指标。

        Args:
            device_id: GPU 设备 ID（从 0 开始）

        Returns:
            指定设备的 GPUMetrics

        Raises:
            DeviceNotFoundError: 设备 ID 超出范围
        """
        ...

    @property
    @abc.abstractmethod
    def device_count(self) -> int:
        """返回可用 GPU 设备数量"""
        ...


class PowerCollector(BaseCollector[Dict[int, float]]):
    """
    功耗数据采集器。

    继承 BaseCollector[Dict[int, float]]，
    collect() 返回 {device_id: power_watts} 字典。

    可能集成到 GPUCollector 中作为独立采集器存在，
    取决于功耗数据的获取方式是否独立于 GPU 主流程。
    """

    @abc.abstractmethod
    def collect(self) -> Dict[int, float]:
        """返回 {device_id: power_watts} 字典"""
        ...


# ============================================================================
# 2. BaseGPUProvider - GPU 数据提供者抽象基类（连接会话模式）
# ============================================================================

class BaseGPUProvider(abc.ABC):
    """
    GPU 数据提供者抽象基类。

    与 BaseCollector 的核心区别::

        BaseCollector (一次性采集模式):
            每次 collect() → 返回当前状态快照
            无状态 / 无连接管理
            适用：CPU、RAM 等简单指标

        BaseGPUProvider (连接会话模式):
            initialize() → 建立连接/加载库
            get_xxx(device_id) → 按需查询细粒度指标
            shutdown() → 释放连接/卸载库
            有状态 / 有生命周期管理
            适用：NVML、ROCm SMI、sysfs 等 GPU API

    设计特点：
    - 优先级排序：数值越小优先级越高，用于自动选择最佳 Provider
    - 上下文管理器：支持 with 语句自动管理生命周期
    - 细粒度接口：按指标类型拆分为独立方法，便于部分降级

    实现示例::

        class AMDLinuxProvider(BaseGPUProvider):
            def initialize(self) -> bool:
                self._lib = ctypes.CDLL("libamd_smi.so")
                self._lib.amdsmi_init(1 << 1)
                return True

            def get_gpu_utilization(self, device_id=0) -> float:
                # 通过 ctypes 调用系统 libamd_smi.so 获取利用率
                ...

            def shutdown(self) -> None:
                if self._lib:
                    self._lib.amdsmi_shut_down()
    """

    def __init__(self, name: str, priority: int = 100, config: dict | None = None):
        """
        初始化 GPU Provider。

        Args:
            name: Provider 唯一标识名称（用于注册表和日志）
            priority: 优先级数值，越小优先级越高。
                      例如 NVML=1(最高), ROCm SMI=10, sysfs=50(最低)

        Raises:
            ValueError: 如果 name 为空字符串
        """
        if not name or not name.strip():
            raise ValueError("Provider name must be a non-empty string")

        self.name = name
        self._priority = priority
        self.config = config or {}
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self._initialized: bool = False
        self._device_count: int = 0
        self._device_names: List[str] = []

    @property
    def priority(self) -> int:
        """
        Provider 优先级（数值越小优先级越高）。

        Returns:
            优先级整数值
        """
        return self._priority

    # ----- 生命周期管理（抽象方法）-----

    @abc.abstractmethod
    def initialize(self) -> bool:
        """
        初始化 GPU 连接。

        此方法应完成以下工作：
        1. 加载必要的动态链接库（如 libnvidia-ml.so、libamdsmi.so）
        2. 建立 GPU 驱动程序的通信通道
        3. 枚举可用设备并填充 _device_count 和 _device_names
        4. 设置初始状态

        Returns:
            True 表示初始化成功且可以正常使用，
            False 表示当前环境不支持此 Provider（不应抛出异常）

        注意：
        - 应捕获所有可能的异常并返回 False
        - 初始化失败不应影响程序继续运行（允许回退到其他 Provider）
        """
        ...

    @abc.abstractmethod
    def shutdown(self) -> None:
        """
        释放 GPU 连接资源。

        此方法应完成以下工作：
        1. 关闭所有打开的设备句柄
        2. 卸载动态链接库
        3. 清理内部缓冲区和缓存
        4. 重置 _initialized 标志

        注意：
        - 即使 initialize() 未成功也应能安全调用（幂等性）
        - 不应抛出异常（使用 try/except 保护）
        """
        ...

    # ----- 核心指标查询（抽象方法）-----

    @abc.abstractmethod
    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """
        一次性采集指定 GPU 的完整指标。

        这是 Provider 的核心采集接口，子类必须实现或依赖下面的
        细粒度方法默认实现。推荐高性能/低延迟场景直接覆写此方法，
        避免多次库调用。

        Args:
            device_id: GPU 设备 ID（从 0 开始）

        Returns:
            完整的 GPUMetrics 对象
        """
        ...

    def get_gpu_utilization(self, device_id: int = 0) -> float:
        """
        获取 GPU 利用率。

        默认实现从 get_metrics() 提取。子类可覆写以提供更高效的查询。

        Args:
            device_id: GPU 设备 ID（从 0 开始）

        Returns:
            GPU 计算单元利用率百分比 (0.0-100.0)
        """
        return self.get_metrics(device_id).gpu_utilization

    def get_memory_info(self, device_id: int = 0) -> Dict[str, int]:
        """
        获取显存信息。

        默认实现从 get_metrics() 提取。

        Args:
            device_id: GPU 设备 ID

        Returns:
            包含以下键的字典：

            .. code-block:: python

                {
                    'used': int,   # 已用显存 (MB)
                    'total': int,  # 总显存 (MB)
                    'free': int    # 空闲显存 (MB)
                }
        """
        metrics = self.get_metrics(device_id)
        return {
            "used": metrics.vram_used,
            "total": metrics.vram_total,
            "free": max(0, metrics.vram_total - metrics.vram_used),
        }

    def get_temperature(self, device_id: int = 0) -> Optional[float]:
        """
        获取核心温度。

        默认实现从 get_metrics() 提取。

        Args:
            device_id: GPU 设备 ID

        Returns:
            核心温度 (°C)，如果不支持温度读取则返回 None
        """
        return self.get_metrics(device_id).temperature

    def get_power_usage(self, device_id: int = 0) -> Optional[Dict[str, float]]:
        """
        获取功耗信息。

        默认实现从 get_metrics() 提取。

        Args:
            device_id: GPU 设备 ID

        Returns:
            包含功耗信息的字典，或不支持时返回 None：

            .. code-block:: python

                {
                    'current': float,  # 当前功耗 (W)
                    'limit': float,    # 功耗上限 (W)，可能不存在
                }
        """
        power = self.get_metrics(device_id).power_usage
        if power is None:
            return None
        return {"current": power, "limit": 0.0}

    # ----- 设备信息查询（可覆写的默认实现）-----

    def get_device_name(self, device_id: int = 0) -> str:
        """
        获取设备型号名称。

        默认实现从 _device_names 列表中获取，
        子类可以在 initialize() 时填充该列表，
        或覆写此方法提供实时查询能力。

        Args:
            device_id: GPU 设备 ID

        Returns:
            设备型号字符串（如 "NVIDIA GeForce RTX 4090"），
            超出范围时返回 "Unknown"
        """
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return "Unknown"

    def get_device_count(self) -> int:
        """
        获取可用 GPU 数量。

        Returns:
            当前系统中由此 Provider 管理的 GPU 数量
        """
        return self._device_count

    def is_available(self) -> bool:
        """
        快速健康检查。

        用于判断 Provider 是否处于可用状态，
        不执行完整的初始化流程（仅检查已缓存的初始化状态）。

        Returns:
            True 表示已初始化且可用，False 表示未初始化或不可用
        """
        return self._initialized

    # ----- 上下文管理器协议 -----

    def __enter__(self) -> "BaseGPUProvider":
        """
        上下文管理器入口（with 语句开始时调用）。

        自动执行 initialize() 并返回自身。

        示例::

            with NvidiaProvider(priority=1) as provider:
                util = provider.get_gpu_utilization(0)

        Returns:
            self（初始化后的 Provider 实例）
        """
        self.initialize()
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Any,
    ) -> bool:
        """
        上下文管理器出口（with 语句结束时调用）。

        自动执行 shutdown() 清理资源。
        不抑制 with 块中的任何异常（始终返回 False）。

        Args:
            exc_type: 异常类型（无异常时为 None）
            exc_val: 异常实例（无异常时为 None）
            exc_tb: 异常 traceback（无异常时为 None）

        Returns:
            始终返回 False，表示不抑制异常
        """
        self.shutdown()
        return False

    # ----- 信息属性 -----

    @property
    def info(self) -> Dict[str, Any]:
        """
        Provider 信息摘要。

        返回当前 Provider 的完整元信息，
        用于调试面板展示和注册表状态查询。

        Returns:
            包含以下信息的字典：

            .. code-block:: python

                {
                    'name': str,              # Provider 名称
                    'priority': int,          # 优先级
                    'initialized': bool,       # 是否已初始化
                    'device_count': int,       # GPU 数量
                    'devices': List[str]       # 设备型号列表
                }
        """
        return {
            "name": self.name,
            "priority": self.priority,
            "initialized": self._initialized,
            "device_count": self._device_count,
            "devices": list(self._device_names),
        }


# ============================================================================
# 3. CollectorRegistry - 全局注册表（线程安全单例）
# ============================================================================

class CollectorRegistry:
    """
    全局采集器和 Provider 注册表（单例模式）。

    功能职责：
    - 管理所有可用的 BaseCollector 和 BaseGPUProvider 实例
    - 按 Provider 优先级自动排序，支持最佳 Provider 选择
    - 支持动态注册/注销（热插拔替换）
    - 提供统一的状态查询和监控接口
    - 确保线程安全的并发访问

    使用示例::

        registry = CollectorRegistry.get_instance()

        # 注册 GPU Provider（按优先级自动排序）
        registry.register_gpu_provider(NvidiaSMIProvider(priority=1))
        registry.register_gpu_provider(AMDRocmProvider(priority=10))

        # 获取最佳可用 Provider
        best = registry.get_best_gpu_provider()
        if best:
            with best:
                util = best.get_gpu_utilization(0)

        # 注册普通采集器
        registry.register_collector('cpu', LinuxCPUCollector())
        registry.register_collector('ram', RAMCollector())

        # 批量安全采集
        for name, collector in registry.get_all_collectors().items():
            data = collector.safe_collect()

    线程安全保证：
    - 所有注册/注销操作使用 threading.RLock 保护
    - 读操作（get_xxx）不加锁，利用 Python GIL 对字典读的保护
    - 单例创建使用双重检查锁定模式
    """

    _instance: Optional["CollectorRegistry"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """
        禁止直接实例化。

        必须通过 get_instance() 类方法获取单例。

        Raises:
            RuntimeError: 如果尝试直接构造
        """
        raise RuntimeError(
            "Use CollectorRegistry.get_instance() instead of direct instantiation"
        )

    @classmethod
    def get_instance(cls) -> "CollectorRegistry":
        """
        获取注册表单例实例（线程安全）。

        使用双重检查锁定（Double-Checked Locking）模式确保：
        - 首次访问时创建实例
        - 后续访问直接返回已有实例
        - 多线程并发首次访问时只创建一个实例

        Returns:
            CollectorRegistry 全局唯一实例
        """
        if cls._instance is None:
            with cls._lock:
                # 双重检查：可能在等待锁期间其他线程已创建
                if cls._instance is None:
                    # 使用 __new__ 绕过 __init__ 中的 RuntimeError
                    instance = object.__new__(cls)
                    # 手动初始化内部状态
                    instance._gpu_providers: List[BaseGPUProvider] = []
                    instance._collectors: Dict[str, BaseCollector] = {}
                    instance._registry_lock = threading.RLock()
                    instance._logger = logging.getLogger(
                        f"{__name__}.CollectorRegistry"
                    )
                    cls._instance = instance
                    instance._logger.info("CollectorRegistry singleton created")
        return cls._instance

    @classmethod
    def _reset_instance(cls) -> None:
        """
        重置单例实例（仅用于测试）。

        警告：生产代码不应调用此方法！
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown_all()
            cls._instance = None

    # ----- GPU Provider 管理 -----

    def register_gpu_provider(self, provider: BaseGPUProvider) -> None:
        """
        注册 GPU Provider。

        注册后 Provider 会按 priority 升序排列（小数值 = 高优先级）。
        如果同名 Provider 已存在，将被替换（热插拔更新）。

        Args:
            provider: 已构建的 BaseGPUProvider 子类实例

        Raises:
            TypeError: 如果 provider 不是 BaseGPUProvider 的实例
        """
        if not isinstance(provider, BaseGPUProvider):
            raise TypeError(
                f"Expected BaseGPUProvider instance, got {type(provider).__name__}"
            )

        with self._registry_lock:
            # 移除同名的旧 Provider（如果有）
            self._gpu_providers = [
                p for p in self._gpu_providers if p.name != provider.name
            ]
            # 添加新 Provider
            self._gpu_providers.append(provider)
            # 按优先级升序排列（数值越小越靠前）
            self._gpu_providers.sort(key=lambda p: p.priority)

        self._logger.debug(
            "Registered GPU provider '%s' (priority=%d, total=%d)",
            provider.name,
            provider.priority,
            len(self._gpu_providers),
        )

    def unregister_gpu_provider(self, name: str) -> None:
        """
        移除指定名称的 GPU Provider。

        如果 Provider 当前处于 initialized 状态，将先调用 shutdown()。

        Args:
            name: 要移除的 Provider 名称
        """
        with self._registry_lock:
            removed = None
            filtered = []
            for p in self._gpu_providers:
                if p.name == name:
                    removed = p
                else:
                    filtered.append(p)
            self._gpu_providers = filtered

        if removed is not None:
            # 安全关闭被移除的 Provider
            try:
                if removed.is_available():
                    removed.shutdown()
            except Exception as e:
                self._logger.warning(
                    "Error shutting down removed provider '%s': %s",
                    name,
                    e,
                )
            self._logger.debug("Unregistered GPU provider '%s'", name)

    def get_best_gpu_provider(self) -> Optional[BaseGPUProvider]:
        """
        获取最佳可用 GPU Provider（仅检查已初始化状态）。

        选择逻辑：
        1. 遍历所有已注册 Provider（按优先级排序）
        2. 返回第一个 is_available() 为 True 的 Provider
        3. 如果没有可用的 Provider，返回 None

        Returns:
            最佳可用 Provider 实例，或 None（当无可用 Provider 时）
        """
        for provider in self._gpu_providers:
            if provider.is_available():
                return provider
        return None

    def select_best_gpu_provider(self) -> Optional[BaseGPUProvider]:
        """
        按优先级尝试初始化并选择第一个可用的 GPU Provider。

        与 get_best_gpu_provider 不同，此方法会主动调用每个 Provider 的
        initialize()，从而完成数据源探测。初始化失败的 Provider 会被安全关闭。

        Returns:
            最佳可用 Provider 实例，或 None（当无可用 Provider 时）
        """
        for provider in self._gpu_providers:
            try:
                if not provider.is_available():
                    provider.initialize()
                if provider.is_available():
                    return provider
            except Exception as e:
                self._logger.debug(
                    "Provider '%s' initialization/selection failed: %s",
                    provider.name,
                    e,
                )
                try:
                    provider.shutdown()
                except Exception:
                    pass
        return None

    def get_all_gpu_providers(self) -> List[BaseGPUProvider]:
        """
        获取所有已注册的 GPU Provider（按优先级排序）。

        Returns:
            Provider 列表，按 priority 升序排列
        """
        return list(self._gpu_providers)

    def get_gpu_provider_by_name(self, name: str) -> Optional[BaseGPUProvider]:
        """
        按名称查找 GPU Provider。

        Args:
            name: Provider 名称

        Returns:
            匹配的 Provider 实例，未找到时返回 None
        """
        for provider in self._gpu_providers:
            if provider.name == name:
                return provider
        return None

    # ----- Collector 管理 -----

    def register_collector(
        self, name: str, collector: BaseCollector
    ) -> None:
        """
        注册数据采集器。

        如果同名采集器已存在，将被静默替换。

        Args:
            name: 采集器的唯一标识名（用于后续查找）
            collector: BaseCollector 子类实例

        Raises:
            TypeError: 如果 collector 不是 BaseCollector 的实例
            ValueError: 如果 name 为空字符串
        """
        if not isinstance(collector, BaseCollector):
            raise TypeError(
                f"Expected BaseCollector instance, got {type(collector).__name__}"
            )
        if not name or not name.strip():
            raise ValueError("Collector name must be a non-empty string")

        with self._registry_lock:
            self._collectors[name] = collector

        self._logger.debug(
            "Registered collector '%s' (type=%s, total=%d)",
            name,
            type(collector).__name__,
            len(self._collectors),
        )

    def unregister_collector(self, name: str) -> None:
        """
        移除指定名称的数据采集器。

        Args:
            name: 要移除的采集器名称
        """
        with self._registry_lock:
            if name in self._collectors:
                del self._collectors[name]
                self._logger.debug("Unregistered collector '%s'", name)

    def get_collector(self, name: str) -> Optional[BaseCollector]:
        """
        按名称获取采集器实例。

        Args:
            name: 采集器名称

        Returns:
            匹配的采集器实例，未找到时返回 None
        """
        return self._collectors.get(name)

    def get_all_collectors(self) -> Dict[str, BaseCollector]:
        """
        获取所有已注册的采集器。

        Returns:
            {name: collector} 字典的浅拷贝
        """
        return dict(self._collectors)

    # ----- 状态查询 -----

    def get_status(self) -> Dict[str, Any]:
        """
        获取注册表完整状态。

        用于调试面板、健康检查端点和问题排查。

        Returns:
            包含完整状态的字典：

            .. code-block:: python

                {
                    'gpu_providers': [
                        {'name': str, 'priority': int, 'available': bool, ...}
                    ],
                    'collectors': [
                        {'name': str, 'type': str, 'enabled': bool, ...}
                    ],
                    'summary': {
                        'provider_count': int,
                        'collector_count': int,
                        'available_provider_count': int
                    }
                }
        """
        provider_statuses = []
        for p in self._gpu_providers:
            info = p.info.copy()
            info["available"] = p.is_available()
            provider_statuses.append(info)

        collector_statuses = []
        for name, c in self._collectors.items():
            collector_statuses.append({
                "name": name,
                "type": type(c).__name__,
                "enabled": c.enabled,
                "success_rate": c.success_rate,
                "avg_time_ms": round(c.avg_collection_time * 1000, 2),
            })

        available_count = sum(
            1 for p in self._gpu_providers if p.is_available()
        )

        return {
            "gpu_providers": provider_statuses,
            "collectors": collector_statuses,
            "summary": {
                "provider_count": len(self._gpu_providers),
                "collector_count": len(self._collectors),
                "available_provider_count": available_count,
            },
        }

    # ----- 生命周期管理 -----

    def shutdown_all(self) -> None:
        """
        关闭所有 Provider 和清理所有 Collector 引用。

        按以下顺序执行：
        1. 关闭所有已初始化的 GPU Provider（调用 shutdown()）
        2. 清空 Collector 字典
        3. 清空 Provider 列表

        注意：此方法是幂等的，多次调用不会产生副作用。
        """
        self._logger.info("Shutting down all providers and collectors...")

        # 关闭所有 Provider
        for provider in list(self._gpu_providers):
            try:
                if provider.is_available():
                    provider.shutdown()
                    self._logger.debug("Shutdown provider '%s'", provider.name)
            except Exception as e:
                self._logger.warning(
                    "Error shutting down provider '%s': %s",
                    provider.name,
                    e,
                )

        # 清空引用
        with self._registry_lock:
            self._gpu_providers.clear()
            self._collectors.clear()

        self._logger.info("All providers and collectors shut down")
