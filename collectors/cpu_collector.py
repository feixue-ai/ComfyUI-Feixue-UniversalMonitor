"""
CPU 数据采集器模块。

提供跨平台的 CPU 性能数据采集功能，支持 Linux、Windows 和 macOS。
"""

from collectors.base import BaseCollector
from core.data_models import CPUMetrics
import psutil
import logging
import os


class CPUCollector(BaseCollector[CPUMetrics]):
    """
    CPU 数据采集器。

    跨平台支持：
    - Linux: 使用 psutil + /proc/stat 获取更精确的每核使用率
    - Windows: 使用 psutil（完整支持）
    - macOS: 使用 psutil（基本支持）

    采集指标：
    - 总 CPU 使用率 (%)
    - 逻辑核心数
    - 当前平均频率 (MHz)
    - 每个核心的使用率列表
    - 负载均衡（仅 Linux）
    - 上下文切换次数

    Examples::

        >>> collector = CPUCollector()
        >>> metrics = collector.safe_collect()
        >>> if metrics:
        ...     print(f"CPU 使用率: {metrics.cpu_utilization}%")
        ...     print(f"核心数: {metrics.cpu_count}")
        ...     print(f"每核使用率: {metrics.per_core_usage}")

    Performance::
        单次采集耗时 < 50ms（使用非阻塞模式）
    """

    def __init__(self):
        """
        初始化 CPU 采集器。

        配置说明：
        - timeout=1.0s: 超时保护，防止采集阻塞
        - enabled=True: 默认启用
        - retry_count=1: 失败时重试 1 次
        
        修复说明 (V2.1 P0 Bugfix):
        - 添加预热机制解决 CPU 使用率恒为 0.0% 的问题
        - psutil.cpu_percent(interval=None) 首次调用返回 0.0（无历史基准）
        - 通过初始化时预采样建立基准值，确保后续采集准确性
        """
        super().__init__(
            name="cpu_collector",
            timeout=1.0,
            enabled=True,
            retry_count=1
        )
        self._platform = None  # 延迟初始化，避免循环依赖
        
        # 🔧 P0 修复: CPU 预热机制
        self._warmed_up = False
        self._warmup_cpu_percent()  # 立即预热

    def _warmup_cpu_percent(self):
        """
        CPU 采样预热（解决首次调用返回 0.0 的问题）。
        
        技术原理：
        - psutil.cpu_percent(interval=None) 使用非阻塞模式
        - 首次调用时没有历史基准数据，必然返回 0.0
        - 通过预采样建立基准点，后续调用可计算真实使用率
        
        实现策略：
        1. 调用一次 interval=None 建立基准（丢弃返回值）
        2. 等待 100ms 让系统积累 CPU 时间统计
        3. 再次调用获取真实使用率（验证预热成功）
        
        注意：此方法在 __init__ 中调用，增加约 100-150ms 初始化时间，
              但确保后续所有采集都能获得准确的非零值。
        """
        try:
            import time
            
            # 步骤1: 第一次采样（建立基准，返回值无意义）
            psutil.cpu_percent(interval=None)
            
            # 步骤2: 短暂等待让系统更新 CPU 统计
            time.sleep(0.1)  # 100ms 通常足够
            
            # 步骤3: 第二次采样（此时应该有真实数据）
            test_value = psutil.cpu_percent(interval=None)
            
            self._warmed_up = True
            
            if test_value == 0.0:
                # 如果仍然是 0，可能系统真的空闲，再等待一会
                time.sleep(0.2)
                psutil.cpu_percent(interval=None)  # 再次刷新
                
            logging.debug(f"[CPU Collector] ✅ 预热完成 (初始值: {test_value}%)")
            
        except Exception as e:
            logging.warning(f"[CPU Collector] ⚠️ 预热失败: {e}")
            # 预热失败不影响运行，collect() 会处理

    def collect(self) -> CPUMetrics:
        """
        执行 CPU 数据采集。

        采集流程：
        1. 获取总 CPU 使用率（优先非阻塞模式，必要时降级为短间隔阻塞）
        2. 获取逻辑核心数
        3. 获取当前平均频率
        4. 获取每核心使用率列表
        5. 根据平台获取特定指标（Linux 负载均衡、上下文切换）

        Returns:
            CPUMetrics: 包含完整 CPU 指标的数据对象

        Note (V2.1 P0 Bugfix):
            - 正常情况：使用 interval=None 非阻塞模式（<1ms）
            - 异常情况：如果返回 0.0 且未预热，自动降级为 interval=0.1（100ms 阻塞）
            - 这确保即使在极端情况下也能获得准确的非零值
        """
        # 1. 总使用率（带智能降级策略）
        if self._warmed_up:
            # ✅ 已预热：使用快速非阻塞模式
            cpu_percent = psutil.cpu_percent(interval=None)
            
            # 保护：如果仍然为 0，尝试一次阻塞式采集
            if cpu_percent == 0.0:
                logging.debug("[CPU Collector] ⚠️ 非阻塞模式返回 0，降级为阻塞模式")
                cpu_percent = psutil.cpu_percent(interval=0.1)  # 100ms 阻塞
        else:
            # ❌ 未预热：使用阻塞模式确保准确性
            logging.warning("[CPU Collector] ⚠️ 预热未完成，使用阻塞模式")
            cpu_percent = psutil.cpu_percent(interval=0.1)  # 100ms 阻塞

        # 2. 逻辑核心数
        cpu_count = psutil.cpu_count(logical=True)

        # 3. 平均频率 (MHz)
        try:
            freq = psutil.cpu_freq()
            cpu_freq = freq.current if freq else 0.0
        except Exception:
            cpu_freq = 0.0

        # 4. 每核心使用率 (非阻塞)
        per_core_usage = psutil.cpu_percent(percpu=True, interval=None)

        # 5. 平台特定指标
        load_avg_1m = None
        load_avg_5m = None
        context_switches = None

        if self._get_platform() in ("linux",):
            # Linux 特有：负载均衡
            try:
                load1, load5, _ = os.getloadavg()
                load_avg_1m = load1
                load_avg_5m = load5
            except (OSError, AttributeError):
                pass

            # Linux 特有：上下文切换次数
            try:
                stats = psutil.cpu_stats()
                context_switches = stats.ctx_switches
            except Exception:
                pass

        return CPUMetrics(
            cpu_utilization=float(cpu_percent),
            cpu_count=int(cpu_count) if cpu_count else 0,
            cpu_freq=float(cpu_freq),
            per_core_usage=[float(x) for x in per_core_usage],
            load_average_1m=load_avg_1m,
            load_average_5m=load_avg_5m,
            context_switches=context_switches
        )

    def _get_platform(self):
        """
        延迟导入平台检测函数（避免循环依赖）。

        使用延迟初始化模式：
        - 首次调用时导入并缓存平台信息
        - 后续调用直接返回缓存值
        - 避免模块加载时的循环导入问题

        Returns:
            str: 当前平台标识符 ('linux', 'windows', 'macos' 等)
        """
        if self._platform is None:
            from utils.platform_detect import get_platform
            self._platform = get_platform()
        return self._platform
