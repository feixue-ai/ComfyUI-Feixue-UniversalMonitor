"""
ComfyUI-Feixue-UniversalMonitor - 核心数据模型定义

定义所有监控指标的数据结构，确保类型安全和序列化兼容性。

模块职责：
1. 提供类型安全的数据容器（使用 dataclass）
2. 支持高效的 JSON 序列化/反序列化（使用 orjson）
3. 实现数据合理性校验和边界值检查
4. 定义统一的异常类体系

设计原则：
- 所有字段必须有明确的类型注解
- 使用 Optional 处理平台相关的可选指标（特别是 Windows/Linux 差异）
- 序列化方法保持与前端 JavaScript 的兼容性
- 校验逻辑采用宽松策略：记录警告但不阻断数据流

版本: 1.0.0
作者: Feixue
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import time
from typing import Any, ClassVar, Dict, List, Optional, Type, TypeVar, Union

# 配置日志
logger = logging.getLogger(__name__)

# 类型变量，用于泛型方法
T = TypeVar("T")


# ============================================================================
# 日志频率限制工具类
# ============================================================================

class LogFrequencyLimiter:
    """
    日志频率限制器，用于防止重复警告刷屏。
    
    支持两种模式：
    1. 首次记录模式：只在第一次触发时记录
    2. 间隔限制模式：在指定时间间隔内只记录一次
    
    Example:
        limiter = LogFrequencyLimiter(min_interval_seconds=60)
        if limiter.should_log("unique_key"):
            logger.warning("This message won't spam")
    """
    
    def __init__(self, min_interval_seconds: float = 60.0, first_only: bool = False):
        """
        初始化日志频率限制器
        
        Args:
            min_interval_seconds: 最小记录间隔（秒），默认60秒
            first_only: 如果为True，只记录第一次触发，后续不再记录
        """
        self._min_interval = min_interval_seconds
        self._first_only = first_only
        self._last_log_time: Dict[str, float] = {}
        self._logged_once: set = set()
    
    def should_log(self, key: str) -> bool:
        """
        判断是否应该记录日志
        
        Args:
            key: 唯一标识该日志消息的键
        
        Returns:
            True 如果应该记录日志，False 否则
        """
        if self._first_only:
            if key in self._logged_once:
                return False
            self._logged_once.add(key)
            return True
        
        now = time.time()
        last_time = self._last_log_time.get(key, 0)
        
        if now - last_time >= self._min_interval:
            self._last_log_time[key] = now
            return True
        
        return False


# 全局日志限制器实例
# 用于防止频繁的校验警告刷屏
_validation_limiter = LogFrequencyLimiter(min_interval_seconds=60)
_first_only_limiter = LogFrequencyLimiter(first_only=True)

# 导出限制器供其他模块使用
log_limiter = _validation_limiter
first_only_log_limiter = _first_only_limiter


# ============================================================================
# 枚举类型定义
# ============================================================================

class GPUVendor(enum.Enum):
    """GPU 厂商枚举

    用于标识 GPU 硬件制造商，影响数据采集方式的选择。
    """
    AMD = "amd"
    NVIDIA = "nvidia"
    UNKNOWN = "unknown"


class Platform(enum.Enum):
    """操作系统平台枚举

    不同平台的系统 API 差异显著，需要针对性处理。
    """
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"


class MetricType(enum.Enum):
    """监控指标类型枚举

    用于指标注册、查询和过滤。
    覆盖系统资源、GPU 资源、功耗、预测等维度。
    """
    # 系统资源
    CPU_USAGE = "cpu_usage"
    CPU_TEMPERATURE = "cpu_temperature"
    RAM_USAGE = "ram_usage"
    RAM_AVAILABLE = "ram_available"

    # GPU 资源
    GPU_USAGE = "gpu_usage"
    GPU_TEMPERATURE = "gpu_temperature"
    GPU_CLOCK = "gpu_clock"
    VRAM_USAGE = "vram_usage"
    VRAM_TOTAL = "vram_total"
    VRAM_FREE = "vram_free"
    VRAM_RESERVED = "vram_reserved"  # PyTorch 缓存池

    # 功耗
    POWER_DRAW = "power_draw"
    POWER_LIMIT = "power_limit"


# ============================================================================
# 异常类体系
# ============================================================================

class MonitorError(Exception):
    """监控器基础异常类

    所有监控相关异常的基类，提供统一的错误处理接口。
    支持上下文信息附加，便于日志记录和问题定位。

    Attributes:
        message: 错误描述信息
        context: 可选的上下文字典，包含额外的调试信息
    """

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} [{context_str}]"
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，用于 JSON 序列化和日志记录"""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "context": self.context,
        }


class DataCollectionError(MonitorError):
    """数据采集失败异常

    当采集器无法获取数据时抛出，包含原始异常信息以便排查。

    Attributes:
        collector_name: 失败的采集器名称
        original_error: 导致失败的原始异常
    """

    def __init__(
        self,
        collector_name: str,
        original_error: Exception,
        context: Optional[Dict[str, Any]] = None,
    ):
        message = f"[{collector_name}] Data collection failed: {original_error}"
        super().__init__(message, context)
        self.collector_name = collector_name
        self.original_error = original_error

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update({
            "collector_name": self.collector_name,
            "original_error": str(self.original_error),
            "original_error_type": type(self.original_error).__name__,
        })
        return result


class GPUNotAvailableError(MonitorError):
    """GPU 不可用或未检测到异常

    当系统中没有检测到 GPU 或 GPU 驱动未正确安装时抛出。
    此异常通常在初始化阶段出现，提示用户检查硬件配置。
    """

    def __init__(
        self,
        message: str = "No GPU detected or GPU driver not available",
        gpu_vendor: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, context)
        self.gpu_vendor = gpu_vendor


class ConfigurationError(MonitorError):
    """配置错误异常

    当配置参数缺失、格式错误或值超出合理范围时抛出。
    用于在初始化阶段进行配置验证。

    Attributes:
        config_key: 有问题的配置项键名
        expected: 期望的值类型或范围描述
    """

    def __init__(
        self,
        config_key: str,
        message: str,
        expected: Optional[str] = None,
        actual_value: Any = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        full_message = f"Configuration error [{config_key}]: {message}"
        if expected:
            full_message += f" (expected: {expected})"
        super().__init__(full_message, context)
        self.config_key = config_key
        self.expected = expected
        self.actual_value = actual_value

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update({
            "config_key": self.config_key,
            "expected": self.expected,
            "actual_value": str(self.actual_value),
        })
        return result


class ProviderInitializationError(MonitorError):
    """GPU Provider 初始化失败异常

    当 GPU 数据提供者（如 NVML、ROCm SMI）无法初始化时抛出。
    通常表示依赖库缺失或权限不足。

    Attributes:
        provider_name: 初始化失败的提供者名称
        reason: 失败原因描述
    """

    def __init__(
        self,
        provider_name: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
    ):
        message = f"Provider '{provider_name}' initialization failed: {reason}"
        super().__init__(message, context)
        self.provider_name = provider_name
        self.reason = reason


class TimeoutError(MonitorError):
    """操作超时异常

    当数据采集或其他操作超过指定时间限制时抛出。
    用于实现超时保护和资源释放。

    Attributes:
        operation: 超时的操作名称
        timeout: 超时时间限制（秒）
    """

    def __init__(
        self,
        operation: str,
        timeout: float,
        context: Optional[Dict[str, Any]] = None,
    ):
        message = f"Operation '{operation}' timed out after {timeout:.1f}s"
        super().__init__(message, context)
        self.operation = operation
        self.timeout = timeout


# ============================================================================
# 基础数据类 - GPU 指标
# ============================================================================

@dataclasses.dataclass
class GPUMetrics:
    """GPU 监控指标数据类

    封装单个 GPU 设备的所有监控指标，包括利用率、显存、温度、功耗等。

    设计说明：
    - 使用 MB 作为显存单位，避免浮点精度问题
    - 温度和功耗标记为 Optional，因为某些平台或驱动可能不支持
    - 提供 vram_percent 计算属性，方便直接获取百分比

    Attributes:
        gpu_utilization: GPU 利用率 (0-100%)
        vram_used: 已用显存 (MB)
        vram_total: 总显存 (MB)
        temperature: 核心温度 (°C), 可能为 None（某些驱动不支持）
        power_usage: 当前功耗 (W), 可能为 None（集成显卡或旧驱动）
        clock_speed: 核心频率 (MHz), 可能为 None
        device_id: GPU 设备 ID（从 0 开始）
        device_name: GPU 型号名称
        driver_version: 驱动版本字符串
    """

    gpu_utilization: float          # GPU 利用率 (0-100%)
    vram_used: int                  # 已用显存 (MB)
    vram_total: int                 # 总显存 (MB)
    temperature: Optional[float] = None  # 核心温度 (°C), 可能为 None
    power_usage: Optional[float] = None  # 当前功耗 (W), 可能为 None
    clock_speed: Optional[int] = None   # 核心频率 (MHz), 可能为 None
    device_id: int = 0              # GPU 设备 ID
    device_name: str = ""           # GPU 型号名称
    driver_version: str = ""        # 驱动版本

    @property
    def vram_percent(self) -> float:
        """计算显存使用百分比

        Returns:
            显存使用百分比 (0.0-100.0)，如果总显存为 0 则返回 0.0
        """
        if self.vram_total > 0:
            return (self.vram_used / self.vram_total) * 100
        return 0.0

    @property
    def vram_free(self) -> int:
        """计算空闲显存 (MB)

        Returns:
            空闲显存量，如果已用超过总量则返回 0
        """
        return max(0, self.vram_total - self.vram_used)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 JSON 序列化）

        对数值字段进行合理的精度处理：
        - 百分比保留 1 位小数
        - 温度保留 1 位小数
        - 功耗保留 2 位小数

        Returns:
            包含所有字段的字典，Optional 字段为 None 时保持 None
        """
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "gpu_utilization": round(self.gpu_utilization, 1),
            "vram_used": self.vram_used,
            "vram_total": self.vram_total,
            "vram_percent": round(self.vram_percent, 1),
            "vram_free": self.vram_free,
            "temperature": round(self.temperature, 1) if self.temperature is not None else None,
            "power_usage": round(self.power_usage, 2) if self.power_usage is not None else None,
            "clock_speed": self.clock_speed,
            "driver_version": self.driver_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GPUMetrics":
        """从字典创建实例（反序列化）

        Args:
            data: 包含 GPUMetrics 字段的字典

        Returns:
            GPUMetrics 实例

        Raises:
            KeyError: 如果缺少必需字段
        """
        # 必需字段验证
        required_fields = ["gpu_utilization", "vram_used", "vram_total"]
        for field in required_fields:
            if field not in data:
                raise KeyError(f"Missing required field: {field}")

        return cls(
            gpu_utilization=float(data["gpu_utilization"]),
            vram_used=int(data["vram_used"]),
            vram_total=int(data["vram_total"]),
            temperature=data.get("temperature"),
            power_usage=data.get("power_usage"),
            clock_speed=data.get("clock_speed"),
            device_id=data.get("device_id", 0),
            device_name=data.get("device_name", ""),
            driver_version=data.get("driver_version", ""),
        )

    def validate(self) -> bool:
        """校验数据合理性

        检查数值是否在合理范围内：
        - 利用率: 0-100
        - 显存: 非负整数
        - 温度: 合理的物理温度范围（-10 到 150°C）
        - 功耗: 非负（消费级 GPU 通常 < 1000W）

        Returns:
            True 如果数据合理，False 如果发现异常值
        """
        try:
            # 基础范围检查
            if not 0 <= self.gpu_utilization <= 100:
                logger.warning(f"GPU utilization out of range: {self.gpu_utilization}")
                return False

            if self.vram_used < 0 or self.vram_total < 0:
                logger.warning(f"VRAM values negative: used={self.vram_used}, total={self.vram_total}")
                return False

            if self.vram_used > self.vram_total:
                logger.warning(
                    f"VRAM used exceeds total: {self.vram_used} > {self.vram_total}"
                )
                # 不返回 False，可能是缓存延迟导致的暂时不一致

            # Optional 字段检查（仅当有值时）
            if self.temperature is not None:
                if not -10 <= self.temperature <= 150:
                    logger.warning(f"GPU temperature out of range: {self.temperature}")
                    return False

            if self.power_usage is not None:
                if self.power_usage < 0 or self.power_usage > 1000:
                    logger.warning(f"GPU power usage suspicious: {self.power_usage}W")
                    return False

            if self.clock_speed is not None:
                if self.clock_speed <= 0 or self.clock_speed > 100000:
                    # 只在初始化时记录一次，避免刷屏
                    if _first_only_limiter.should_log("gpu_clock_suspicious"):
                        logger.warning(f"GPU clock speed suspicious: {self.clock_speed} MHz")
                    return False

            return True

        except (TypeError, AttributeError) as e:
            logger.error(f"GPUMetrics validation error: {e}")
            return False

    def copy(self) -> "GPUMetrics":
        """创建深拷贝，用于快照历史记录

        Returns:
            新的 GPUMetrics 实例，与原始对象完全独立
        """
        return dataclasses.replace(self)


# ============================================================================
# 基础数据类 - CPU 指标
# ============================================================================

@dataclasses.dataclass
class CPUMetrics:
    """CPU 监控指标数据类

    封装 CPU 的使用率、频率、核心状态等信息。

    平台差异说明：
    - load_average_* 字段仅在 Linux/macOS 上可用，Windows 为 None
    - per_core_usage 长度应与 cpu_count 一致
    - context_switches 可能需要特殊权限才能获取

    Attributes:
        cpu_utilization: 总 CPU 使用率 (0-100%)
        cpu_count: 逻辑 CPU 核心数
        cpu_freq: 当前平均频率 (MHz)
        per_core_usage: 每个核心的使用率列表
        load_average_1m: 1 分钟负载均衡（仅 Linux/macOS）
        load_average_5m: 5 分钟负载均衡（仅 Linux/macOS）
        context_switches: 上下文切换次数（可能需要 root 权限）
    """

    cpu_utilization: float          # 总 CPU 使用率 (0-100%)
    cpu_count: int                  # 逻辑 CPU 核心数
    cpu_freq: float                 # 当前平均频率 (MHz)
    per_core_usage: List[float]     # 每个核心的使用率列表
    load_average_1m: Optional[float] = None  # 1 分钟负载均衡 (仅 Linux)
    load_average_5m: Optional[float] = None  # 5 分钟负载均衡 (仅 Linux)
    context_switches: Optional[int] = None   # 上下文切换次数

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式

        对列表和数值进行精度处理。

        Returns:
            包含所有 CPU 指标的字典
        """
        return {
            "cpu_utilization": round(self.cpu_utilization, 1),
            "cpu_count": self.cpu_count,
            "cpu_freq": round(self.cpu_freq, 0),
            "per_core_usage": [round(x, 1) for x in self.per_core_usage],
            "load_average_1m": (
                round(self.load_average_1m, 2) if self.load_average_1m is not None else None
            ),
            "load_average_5m": (
                round(self.load_average_5m, 2) if self.load_average_5m is not None else None
            ),
            "context_switches": self.context_switches,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CPUMetrics":
        """从字典创建实例

        Args:
            data: 包含 CPUMetrics 字段的字典

        Returns:
            CPUMetrics 实例
        """
        required_fields = ["cpu_utilization", "cpu_count", "cpu_freq", "per_core_usage"]
        for field in required_fields:
            if field not in data:
                raise KeyError(f"Missing required field: {field}")

        per_core = data["per_core_usage"]
        if not isinstance(per_core, list):
            raise TypeError(f"per_core_usage must be a list, got {type(per_core)}")

        return cls(
            cpu_utilization=float(data["cpu_utilization"]),
            cpu_count=int(data["cpu_count"]),
            cpu_freq=float(data["cpu_freq"]),
            per_core_usage=[float(x) for x in per_core],
            load_average_1m=data.get("load_average_1m"),
            load_average_5m=data.get("load_average_5m"),
            context_switches=data.get("context_switches"),
        )

    def validate(self) -> bool:
        """校验 CPU 数据合理性

        检查项目：
        - 使用率范围: 0-100%（多核系统可能略超 100%）
        - 核心数: 正整数
        - 频率: 合理范围（100 MHz - 10 GHz）
        - 每核使用率列表长度与 core_count 匹配

        Returns:
            True 如果数据合理
        """
        try:
            # 使用率检查（允许轻微超出 100%，由于采样时间差）
            if not -1 <= self.cpu_utilization <= 101:
                logger.warning(f"CPU utilization out of range: {self.cpu_utilization}")
                return False

            # 核心数检查
            if self.cpu_count <= 0 or self.cpu_count > 1024:
                logger.warning(f"CPU count suspicious: {self.cpu_count}")
                return False

            # 频率检查（现代 CPU 通常在 500 MHz - 6 GHz）
            if not 100 <= self.cpu_freq <= 10000:
                logger.warning(f"CPU frequency out of range: {self.cpu_freq} MHz")
                return False

            # 每核使用率检查
            if len(self.per_core_usage) != self.cpu_count:
                logger.warning(
                    f"per_core_usage length ({len(self.per_core_usage)}) != "
                    f"cpu_count ({self.cpu_count})"
                )
                # 不严格拒绝，但记录警告

            for i, usage in enumerate(self.per_core_usage):
                if not -1 <= usage <= 101:
                    logger.warning(f"Core {i} usage out of range: {usage}")
                    return False

            # 负载检查（如果有值）
            for name, value in [
                ("load_1m", self.load_average_1m),
                ("load_5m", self.load_average_5m),
            ]:
                if value is not None:
                    if value < 0 or value > self.cpu_count * 10:
                        logger.warning(f"{name} suspicious: {value}")
                        return False

            return True

        except (TypeError, AttributeError) as e:
            logger.error(f"CPUMetrics validation error: {e}")
            return False

    def copy(self) -> "CPUMetrics":
        """创建深拷贝"""
        return dataclasses.replace(
            self,
            per_core_usage=list(self.per_core_usage),  # 列表需要复制
        )


# ============================================================================
# 基础数据类 - 内存指标
# ============================================================================

@dataclasses.dataclass
class RAMMetrics:
    """内存（RAM）监控指标数据类

    封装物理内存和交换分区的使用情况。

    单位统一使用 MB（兆字节），避免 GB 换算的浮点精度问题。

    Attributes:
        ram_used: 已用物理内存 (MB)
        ram_total: 总物理内存 (MB)
        ram_percent: 内存使用百分比 (0-100%)
        swap_used: 已用交换分区 (MB)
        swap_total: 总交换分区 (MB)
        cached: 缓存占用 (MB)（Linux 特有，Windows 为 0）
        available: 可用内存 (MB)
    """

    ram_used: int                   # 已用物理内存 (MB)
    ram_total: int                  # 总物理内存 (MB)
    ram_percent: float              # 内存使用百分比 (0-100%)
    swap_used: int = 0              # 已用交换分区 (MB)
    swap_total: int = 0             # 总交换分区 (MB)
    cached: int = 0                 # 缓存占用 (MB)
    available: int = 0              # 可用内存 (MB)

    @property
    def ram_free(self) -> int:
        """计算空闲物理内存 (MB)

        Returns:
            空闲内存量
        """
        return max(0, self.ram_total - self.ram_used)

    @property
    def swap_percent(self) -> float:
        """计算交换分区使用百分比

        Returns:
            交换分区使用百分比，如果没有交换分区则返回 0.0
        """
        if self.swap_total > 0:
            return (self.swap_used / self.swap_total) * 100
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式

        Returns:
            包含所有内存指标的字典
        """
        return {
            "ram_used": self.ram_used,
            "ram_total": self.ram_total,
            "ram_percent": round(self.ram_percent, 1),
            "ram_free": self.ram_free,
            "swap_used": self.swap_used,
            "swap_total": self.swap_total,
            "swap_percent": round(self.swap_percent, 1),
            "cached": self.cached,
            "available": self.available,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RAMMetrics":
        """从字典创建实例

        Args:
            data: 包含 RAMMetrics 字段的字典

        Returns:
            RAMMetrics 实例
        """
        required_fields = ["ram_used", "ram_total", "ram_percent"]
        for field in required_fields:
            if field not in data:
                raise KeyError(f"Missing required field: {field}")

        return cls(
            ram_used=int(data["ram_used"]),
            ram_total=int(data["ram_total"]),
            ram_percent=float(data["ram_percent"]),
            swap_used=int(data.get("swap_used", 0)),
            swap_total=int(data.get("swap_total", 0)),
            cached=int(data.get("cached", 0)),
            available=int(data.get("available", 0)),
        )

    def validate(self) -> bool:
        """校验内存数据合理性

        检查项目：
        - 数值非负
        - 使用率在 0-100 范围
        - 已用量不超过总量

        Returns:
            True 如果数据合理
        """
        try:
            # 非负检查
            for name, value in [
                ("ram_used", self.ram_used),
                ("ram_total", self.ram_total),
                ("swap_used", self.swap_used),
                ("swap_total", self.swap_total),
                ("cached", self.cached),
                ("available", self.available),
            ]:
                if value < 0:
                    logger.warning(f"{name} is negative: {value}")
                    return False

            # 总量检查
            if self.ram_total == 0:
                logger.warning("RAM total is zero")
                return False

            # 使用率检查
            if not 0 <= self.ram_percent <= 100:
                logger.warning(f"RAM percent out of range: {self.ram_percent}")
                return False

            # 一致性检查
            if self.ram_used > self.ram_total:
                logger.warning(
                    f"RAM used exceeds total: {self.ram_used} > {self.ram_total}"
                )

            if self.swap_used > self.swap_total and self.swap_total > 0:
                logger.warning(
                    f"Swap used exceeds total: {self.swap_used} > {self.swap_total}"
                )

            return True

        except (TypeError, AttributeError) as e:
            logger.error(f"RAMMetrics validation error: {e}")
            return False

    def copy(self) -> "RAMMetrics":
        """创建深拷贝"""
        return dataclasses.replace(self)


# ============================================================================
# 基础数据类 - 功耗指标
# ============================================================================

@dataclasses.dataclass
class PowerMetrics:
    """功耗监控指标数据类

    封装 GPU 或系统的功耗相关信息。

    注意事项：
    - 并非所有 GPU 都支持功耗读取（如集成显卡）
    - average_power 是基于滑动窗口计算的平均值
    - power_efficiency 是自定义的效率指标（性能/功耗比）

    Attributes:
        current_power: 当前功耗 (W)
        limit_power: 功耗限制/上限 (W)
        average_power: 平均功耗 (W, 滑动窗口)
        power_efficiency: 功耗效率比（无量纲，越高越好）
    """

    current_power: float            # 当前功耗 (W)
    limit_power: float              # 功耗限制 (W)
    average_power: float            # 平均功耗 (W, 滑动窗口)
    power_efficiency: float         # 功耗效率比

    @property
    def power_percent(self) -> float:
        """计算当前功耗占限制的百分比

        Returns:
            功耗使用百分比 (0.0-100.0+)，可能超过 100% 如果瞬时功耗超标
        """
        if self.limit_power > 0:
            return (self.current_power / self.limit_power) * 100
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式

        Returns:
            包含所有功耗指标的字典
        """
        return {
            "current_power": round(self.current_power, 2),
            "limit_power": round(self.limit_power, 2),
            "average_power": round(self.average_power, 2),
            "power_efficiency": round(self.power_efficiency, 3),
            "power_percent": round(self.power_percent, 1),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PowerMetrics":
        """从字典创建实例

        Args:
            data: 包含 PowerMetrics 字段的字典

        Returns:
            PowerMetrics 实例
        """
        required_fields = ["current_power", "limit_power", "average_power", "power_efficiency"]
        for field in required_fields:
            if field not in data:
                raise KeyError(f"Missing required field: {field}")

        return cls(
            current_power=float(data["current_power"]),
            limit_power=float(data["limit_power"]),
            average_power=float(data["average_power"]),
            power_efficiency=float(data["power_efficiency"]),
        )

    def validate(self) -> bool:
        """校验功耗数据合理性

        检查项目：
        - 数值非负
        - 在合理范围内（消费级 GPU 通常 0-600W）

        Returns:
            True 如果数据合理
        """
        try:
            # 非负检查
            for name, value in [
                ("current_power", self.current_power),
                ("limit_power", self.limit_power),
                ("average_power", self.average_power),
            ]:
                if value < 0:
                    logger.warning(f"{name} is negative: {value}")
                    return False

            # 合理范围检查
            if self.current_power > 1000:
                logger.warning(f"Current power suspiciously high: {self.current_power}W")
                return False

            if self.limit_power > 1000:
                logger.warning(f"Power limit suspiciously high: {self.limit_power}W")
                return False

            # 平均功率应在当前功率附近（允许一定波动）
            if abs(self.average_power - self.current_power) > self.current_power * 2:
                logger.warning(
                    f"Average power deviates significantly from current: "
                    f"avg={self.average_power}, cur={self.current_power}"
                )
                # 不严格拒绝

            return True

        except (TypeError, AttributeError, ZeroDivisionError) as e:
            logger.error(f"PowerMetrics validation error: {e}")
            return False

    def copy(self) -> "PowerMetrics":
        """创建深拷贝"""
        return dataclasses.replace(self)


# ============================================================================
# 复合数据类 - 系统监控快照
# ============================================================================

@dataclasses.dataclass
class MonitorSnapshot:
    """系统监控快照数据类

    一次完整的数据采集结果，聚合所有硬件指标和元数据。

    这是整个监控系统最核心的数据结构，用于：
    1. 传递给前端展示层
    2. 写入历史数据库
    3. 导出为报告或日志

    设计特点：
    - timestamp 使用 Unix 时间戳，便于排序和比较
    - gpu_metrics 标记为 Optional，适应无 GPU 场景
    - version 字段用于未来格式升级时的向后兼容处理

    Attributes:
        timestamp: Unix 时间戳（秒级精度）
        gpu_metrics: GPU 指标（单卡场景），多卡场景请使用 MonitorSnapshotMultiGPU
        cpu_metrics: CPU 指标（必须存在）
        ram_metrics: 内存指标（必须存在）
        power_metrics: 功耗指标（可选）
        data_source: 当前使用的 GPU 数据源标识
        version: 快照版本号，用于格式演进
    """

    timestamp: float                # Unix 时间戳
    gpu_metrics: Optional[GPUMetrics]
    cpu_metrics: CPUMetrics
    ram_metrics: RAMMetrics
    power_metrics: Optional[PowerMetrics] = None
    data_source: str = ""           # 当前使用的 GPU 数据源标识
    version: str = "1.0.0"          # 快照版本号

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 JSON 序列化）

        将嵌套的对象递归转换为字典，Optional 字段为 None 时输出 null。

        Returns:
            可直接 JSON 序列化的字典
        """
        return {
            "timestamp": self.timestamp,
            "version": self.version,
            "data_source": self.data_source,
            "gpu": self.gpu_metrics.to_dict() if self.gpu_metrics else None,
            "cpu": self.cpu_metrics.to_dict(),
            "ram": self.ram_metrics.to_dict(),
            "power": self.power_metrics.to_dict() if self.power_metrics else None,
        }

    def to_json(self) -> str:
        """序列化为 JSON 字符串（使用 orjson 以获得最佳性能）

        orjson 是目前 Python 中最快的 JSON 库，
        特别适合高频采集场景下的序列化需求。

        Returns:
            UTF-8 编码的 JSON 字符串

        Raises:
            ImportError: 如果 orjson 未安装，回退到标准 json 库
        """
        try:
            import orjson
            # orjson 返回 bytes，需要解码为 str
            return orjson.dumps(self.to_dict()).decode("utf-8")
        except ImportError:
            import json
            logger.warning(
                "orjson not installed, falling back to standard json. "
                "Install orjson for better performance: pip install orjson"
            )
            return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorSnapshot":
        """从字典创建实例（反序列化）

        支持 version 字段检查，未来可用于格式迁移。
        兼容两种键名格式：简短形式 (cpu, ram, gpu) 和完整形式 (cpu_metrics, ram_metrics)。

        Args:
            data: 包含 MonitorSnapshot 字段的字典

        Returns:
            MonitorSnapshot 实例

        Raises:
            KeyError: 缺少必需字段
            ValueError: 版本不兼容
        """
        # 必需字段检查（支持两种键名格式）
        cpu_data = data.get("cpu") or data.get("cpu_metrics")
        ram_data = data.get("ram") or data.get("ram_metrics")

        if cpu_data is None:
            raise KeyError("Missing required field: cpu (or cpu_metrics)")
        if ram_data is None:
            raise KeyError("Missing required field: ram (or ram_metrics)")

        # 版本检查（宽松模式，只记录警告）
        version = data.get("version", "1.0.0")
        if version != "1.0.0":
            logger.warning(f"Snapshot version mismatch: expected 1.0.0, got {version}")

        # 反序列化嵌套对象
        gpu_data = data.get("gpu") or data.get("gpu_metrics")
        gpu_metrics = GPUMetrics.from_dict(gpu_data) if gpu_data else None

        cpu_metrics = CPUMetrics.from_dict(cpu_data)
        ram_metrics = RAMMetrics.from_dict(ram_data)

        power_data = data.get("power") or data.get("power_metrics")
        power_metrics = PowerMetrics.from_dict(power_data) if power_data else None

        return cls(
            timestamp=float(data["timestamp"]),
            gpu_metrics=gpu_metrics,
            cpu_metrics=cpu_metrics,
            ram_metrics=ram_metrics,
            power_metrics=power_metrics,
            data_source=data.get("data_source", ""),
            version=version,
        )

    @classmethod
    def from_json(cls, json_str: str) -> "MonitorSnapshot":
        """从 JSON 字符串创建实例

        Args:
            json_str: JSON 格式的字符串

        Returns:
            MonitorSnapshot 实例
        """
        try:
            import orjson
            data = orjson.loads(json_str)
        except ImportError:
            import json
            data = json.loads(json_str)

        return cls.from_dict(data)

    def validate(self) -> bool:
        """校验整个快照的数据合理性

        执行全面的数据完整性检查：
        1. 时间戳合理性（不能是未来时间，不能太旧）
        2. CPU/RAM 必须存在且通过各自校验
        3. GPU 可选但如果存在则需要校验
        4. 版本号格式检查

        Returns:
            True 如果所有数据都合理
        """
        try:
            # 时间戳检查
            current_time = time.time()
            if self.timestamp > current_time + 60:
                logger.warning(f"Timestamp is in the future: {self.timestamp}")
                return False

            if self.timestamp < current_time - 86400 * 365:  # 超过一年前
                logger.warning(f"Timestamp is too old: {self.timestamp}")
                # 不严格拒绝，但记录

            # 必须存在的指标校验
            if self.cpu_metrics is None:
                logger.error("CPU metrics is required but missing")
                return False

            if self.ram_metrics is None:
                logger.error("RAM metrics is required but missing")
                return False

            if not self.cpu_metrics.validate():
                logger.error("CPU metrics validation failed")
                return False

            if not self.ram_metrics.validate():
                logger.error("RAM metrics validation failed")
                return False

            # 可选指标校验（存在时才校验）
            if self.gpu_metrics is not None:
                if not self.gpu_metrics.validate():
                    # 使用频率限制器，避免刷屏
                    if _validation_limiter.should_log("gpu_metrics_validation_failed"):
                        logger.warning("GPU metrics validation failed")

            if self.power_metrics is not None:
                if not self.power_metrics.validate():
                    # 使用频率限制器，避免刷屏
                    if _validation_limiter.should_log("power_metrics_validation_failed"):
                        logger.warning("Power metrics validation failed")

            # 版本号格式检查（简单的语义版本检查）
            parts = self.version.split(".")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                logger.warning(f"Invalid version format: {self.version}")

            return True

        except Exception as e:
            logger.error(f"MonitorSnapshot validation error: {e}")
            return False

    def copy(self) -> "MonitorSnapshot":
        """创建深拷贝，用于历史记录存储

        Returns:
            新的 MonitorSnapshot 实例
        """
        return MonitorSnapshot(
            timestamp=self.timestamp,
            gpu_metrics=self.gpu_metrics.copy() if self.gpu_metrics else None,
            cpu_metrics=self.cpu_metrics.copy(),
            ram_metrics=self.ram_metrics.copy(),
            power_metrics=self.power_metrics.copy() if self.power_metrics else None,
            data_source=self.data_source,
            version=self.version,
        )

    def get_summary(self) -> Dict[str, Any]:
        """生成快照摘要（精简版，用于日志或通知）

        Returns:
            包含关键指标的摘要字典
        """
        summary = {
            "timestamp": self.timestamp,
            "cpu_usage": self.cpu_metrics.cpu_utilization,
            "ram_usage_percent": self.ram_metrics.ram_percent,
            "has_gpu": self.gpu_metrics is not None,
        }

        if self.gpu_metrics:
            summary.update({
                "gpu_usage": self.gpu_metrics.gpu_utilization,
                "vram_percent": self.gpu_metrics.vram_percent,
                "gpu_temp": self.gpu_metrics.temperature,
            })

        return summary


# ============================================================================
# 向后兼容性别名（保持与现有代码的兼容性）
# ============================================================================

# SystemSnapshot 作为 MonitorSnapshot 的别名，确保现有代码无需修改
SystemSnapshot = MonitorSnapshot
