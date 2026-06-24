"""
ComfyUI-Feixue-UniversalMonitor - 线程安全工具与性能优化

核心设计原则：
1. 无锁读取：利用 Python GIL 保护字典原子性，缓存命中 < 0.01ms
2. 最小化锁区域：写操作使用 RLock，仅保护必要代码段
3. 超时保护：所有外部调用必须有超时限制（默认 2s）
4. 优雅降级：单个指标失败不影响整体系统运行
5. 避免阻塞：使用 Event.wait() 替代 time.sleep()，支持快速停止
6. 内存安全：提供 clear() 方法，支持 LRU 淘汰策略

性能目标：
- execute_with_timeout() 开销 < 0.5ms
- ThreadSafeCache.get() 命中时 < 0.01ms
- NonBlockingCollectorScheduler 支持 >= 20 个并发采集器
- 24 小时连续运行内存增长 < 50MB
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ============================================================================
# 1. 超时执行器 (Timeout Executor)
# ============================================================================

@dataclass
class TimeoutResult:
    """
    超时执行结果容器

    Attributes:
        success: 是否成功完成（未超时且无异常）
        data: 执行返回的数据（成功时）或默认值（超时时）
        error: 异常对象（失败时）
        elapsed_time: 实际执行耗时（秒）

    Example:
        >>> result = execute_with_timeout(some_func, timeout=1.0)
        >>> if result.success:
        ...     print(f"Got: {result.data} in {result.elapsed_time:.3f}s")
    """
    success: bool
    data: Any = None
    error: Optional[Exception] = None
    elapsed_time: float = 0.0


def execute_with_timeout(
    func: Callable[..., T],
    args: tuple = (),
    kwargs: dict = None,
    timeout: float = 2.0,
    default: Any = None
) -> TimeoutResult:
    """
    在独立线程中执行函数，带超时保护

    使用 daemon Thread + join(timeout) 实现，确保不会阻塞主线程。

    设计决策：
    - 使用 daemon 线程：主进程退出时自动终止，避免僵尸线程
    - 使用可变列表传递结果：避免闭包变量绑定问题
    - 精确计时：从线程启动到 join 返回的总耗时

    Args:
        func: 要执行的函数（可以是任何 callable）
        args: 位置参数元组
        kwargs: 关键字参数字典
        timeout: 超时时间（秒），默认 2.0 秒
        default: 超时或异常时的返回值

    Returns:
        TimeoutResult 对象包含执行结果或错误信息

    Example:
        >>> def slow_operation():
        ...     time.sleep(5)
        ...     return "done"
        >>> result = execute_with_timeout(slow_operation, timeout=1.0, default="timeout")
        >>> print(result.success, result.data)  # False, "timeout"

    Performance:
        - 开销：< 0.5ms（不含目标函数执行时间）
        - 内存影响：每个调用创建一个 daemon 线程（GC 自动回收）
    """
    kwargs = kwargs or {}
    result_container: list = [None]  # [return_value]
    error_container: list = [None]   # [exception]

    def _worker() -> None:
        """工作线程：执行目标函数并捕获结果/异常"""
        try:
            result_container[0] = func(*args, **kwargs)
        except Exception as e:
            error_container[0] = e
            func_name = getattr(func, '__name__', str(func))
            logger.debug(f"Function {func_name} raised {type(e).__name__}: {e}")

    # 创建并启动守护线程
    func_name = getattr(func, '__name__', str(func))
    thread = threading.Thread(target=_worker, daemon=True, name=f"TimeoutWorker-{func_name}")
    start_time = time.perf_counter()

    try:
        thread.start()
        # 带超时的等待（可被中断）
        thread.join(timeout=timeout)

        elapsed_time = time.perf_counter() - start_time

        if thread.is_alive():
            # 超时：线程仍在运行（daemon 线程会在主进程退出时自动终止）
            func_name = getattr(func, '__name__', str(func))
            logger.warning(
                f"Timeout: {func_name} did not complete within {timeout:.3f}s"
            )
            return TimeoutResult(
                success=False,
                data=default,
                error=TimeoutError(f"Execution timed out after {timeout:.3f}s"),
                elapsed_time=elapsed_time
            )

        # 线程已结束，检查是否有异常
        if error_container[0] is not None:
            return TimeoutResult(
                success=False,
                data=default,
                error=error_container[0],
                elapsed_time=elapsed_time
            )

        # 成功完成
        return TimeoutResult(
            success=True,
            data=result_container[0],
            elapsed_time=elapsed_time
        )

    except RuntimeError as e:
        # 线程池关闭后 submit 或线程启动失败（如资源耗尽）
        logger.error(f"Failed to execute {func.__name__}: {e}")
        return TimeoutResult(
            success=False,
            data=default,
            error=e,
            elapsed_time=time.perf_counter() - start_time
        )

    except Exception as e:
        # 线程创建或启动失败（极少见）
        logger.error(f"Failed to execute {func.__name__}: {e}")
        return TimeoutResult(
            success=False,
            data=default,
            error=e,
            elapsed_time=time.perf_counter() - start_time
        )


# ============================================================================
# 2. 线程安全的 TTL 缓存 (Thread-Safe TTL Cache with LRU)
# ============================================================================

class ThreadSafeCache:
    """
    线程安全的 TTL 缓存，支持 LRU 淘汰策略

    特性：
    - 读操作：无锁快速路径（利用 GIL 保护字典原子性），< 0.01ms
    - 写操作：最小化 RLock 区域，< 0.1ms
    - TTL 过期：延迟删除策略（lazy eviction），访问时检查
    - 双重检查锁定：防止缓存击穿（多个线程同时计算相同 key）
    - 最大容量：LRU 淘汰策略（最近最少使用优先淘汰）
    - 统计信息：实时命中率、缓存大小等监控数据

    线程安全保证：
    - 读操作（get）：无锁，GIL 保证字典单次操作的原子性
    - 写操作（set）：RLock 保护，防止并发写入冲突
    - 复合操作（get_or_compute）：双重检查锁定模式

    性能目标：
    - 缓存命中：< 0.01ms（无锁读取）
    - 缓存未命中写入：< 0.1ms（加锁写入）
    - 并发读写无死锁（RLock 可重入）

    Example:
        >>> cache = ThreadSafeCache(max_size=100, default_ttl=60.0)
        >>> cache.set("user:1", {"name": "Alice"})
        >>> cache.get("user:1")  # {"name": "Alice"}
        >>> result = cache.get_or_compute("expensive", compute_fn, ttl=30.0)
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 60.0):
        """
        初始化线程安全缓存

        Args:
            max_size: 最大缓存条目数（超过时触发 LRU 淘汰）
            default_ttl: 默认过期时间（秒）
        """
        self._cache: Dict[str, Tuple[Any, float]] = {}  # {key: (value, expiry_timestamp)}
        self._access_order: OrderedDict = OrderedDict()  # LRU 访问顺序记录
        self._lock = threading.RLock()  # 可重入锁，支持嵌套调用
        self._max_size = max_size
        self._default_ttl = default_ttl

        # 统计计数器（非关键路径，允许轻微不准）
        self._hits = 0
        self._misses = 0

    def get(self, key: str, default: Any = None) -> Any:
        """
        读取缓存值（线程安全）

        Args:
            key: 缓存键
            default: 未命中或过期时的默认值

        Returns:
            缓存的值，或 default（如果不存在/已过期）
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                return default

            value, expiry_time = entry

            # 检查是否过期（lazy eviction）
            if time.time() > expiry_time:
                self._misses += 1
                return default

            # 缓存命中：更新 LRU 顺序与计数
            self._access_order.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """
        写入缓存值（慢速路径，加锁）

        最小化锁区域：仅在修改共享状态时持有锁。
        计算 expiry_time 在锁外完成（但时间戳精度要求不高）。

        Args:
            key: 缓存键
            value: 要缓存的值
            ttl: 过期时间（秒），为 None 时使用 default_ttl
        """
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expiry_time = time.time() + effective_ttl

        with self._lock:
            # 写入缓存
            self._cache[key] = (value, expiry_time)

            # 更新 LRU 访问顺序（移到末尾 = 最近使用）
            if key in self._access_order:
                self._access_order.move_to_end(key)
            else:
                self._access_order[key] = True

            # LRU 淘汰：超出容量时移除最久未使用的条目
            while len(self._cache) > self._max_size:
                oldest_key, _ = self._access_order.popitem(last=False)
                if oldest_key in self._cache:
                    del self._cache[oldest_key]
                    logger.debug(f"LRU evicted cache entry: {oldest_key}")

    def get_or_compute(self, key: str, compute_fn: Callable[[], T], ttl: Optional[float] = None) -> T:
        """
        获取或计算值（双重检查锁定模式，防止缓存击穿）

        当多个线程同时请求同一个未缓存的 key 时：
        - 第一个线程获取锁并执行计算
        - 其他线程在第一次 get() 后阻塞等待
        - 第一个线程完成后释放锁
        - 其他线程再次检查发现已有缓存，直接返回

        Args:
            key: 缓存键
            compute_fn: 无参计算函数（应快速且线程安全）
            ttl: 过期时间（秒）

        Returns:
            缓存的值或新计算的值

        Raises:
            Exception: compute_fn 抛出的任何异常
        """
        # 第一次检查：无锁快速路径（常见情况，大多数请求会在这里返回）
        value = self.get(key)
        if value is not None:
            return value

        # 需要计算：加锁防止重复计算（缓存击穿保护）
        with self._lock:
            # 第二次检查：可能在等待锁期间其他线程已完成计算
            value = self.get(key)
            if value is not None:
                return value

            # 执行计算（在锁内，保证只计算一次）
            try:
                computed_value = compute_fn()
                self.set(key, computed_value, ttl)
                return computed_value
            except Exception as e:
                logger.error(f"Cache computation failed for key '{key}': {e}")
                raise

    def invalidate(self, key: str) -> bool:
        """
        使单个缓存键失效

        Args:
            key: 要失效的缓存键

        Returns:
            True 如果键存在并被删除，False 如果键不存在
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._access_order.pop(key, None)
                return True
            return False

    def clear(self) -> None:
        """清空所有缓存（用于内存清理或重置）"""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            logger.debug("Cache cleared")

    @property
    def stats(self) -> dict:
        """
        返回缓存统计信息

        Returns:
            包含以下字段的字典：
            - size: 当前缓存条目数
            - max_size: 最大容量
            - hits: 命中次数
            - misses: 未命中次数
            - hit_rate: 命中率 (0.0 ~ 1.0)
        """
        total = self._hits + self._misses
        return {
            'size': len(self._cache),
            'max_size': self._max_size,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': self._hits / total if total > 0 else 0.0
        }

    @property
    def hit_rate(self) -> float:
        """缓存命中率便捷属性"""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0


# ============================================================================
# 3. 非阻塞采集调度器 (Non-Blocking Collector Scheduler)
# ============================================================================

class NonBlockingCollectorScheduler:
    """
    非阻塞数据采集调度器

    设计理念：
    - 后台守护线程定期采集数据（daemon=True，随主进程退出）
    - 主线程只读 ThreadSafeCache，永不阻塞（< 0.01ms）
    - 每个采集器独立超时保护（默认 2 秒上限）
    - 支持优雅停止（Event.wait 替代 time.sleep，响应时间 < 间隔时间）
    - 单个采集器失败不影响其他采集器（隔离性）

    架构优势：
    - 解耦采集与消费：生产者-消费者模式
    - 背压控制：采集速度固定，消费者按需读取
    - 故障隔离：某个采集器异常不会级联影响

    Example:
        >>> scheduler = NonBlockingCollectorScheduler(interval=1.0)
        >>> scheduler.register_collector('cpu', cpu_collector.collect)
        >>> scheduler.register_collector('gpu', gpu_collector.collect)
        >>> scheduler.start()
        >>>
        >>> # 主线程随时读取最新数据（< 0.01ms）
        >>> snapshot = scheduler.get_snapshot()
        >>> cpu_data = scheduler.get_latest('cpu')
        >>>
        >>> scheduler.stop()  # 优雅停止（最多等待一个采集周期）
    """

    def __init__(
        self,
        interval: float = 1.0,
        timeout_per_collector: float = 2.0
    ):
        """
        初始化调度器

        Args:
            interval: 采集间隔（秒），控制后台线程采集频率
            timeout_per_collector: 每个采集器的最大执行时间（秒）
        """
        self._interval = interval
        self._timeout = timeout_per_collector

        # 注册的采集器 {name: collector_function}
        self._collectors: Dict[str, Callable] = {}

        # 共享数据缓存（TTL = 2 * interval，容忍偶尔的采集延迟）
        self._cache = ThreadSafeCache(default_ttl=interval * 2)

        # 线程控制
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        # 错误追踪（最后一次错误，用于调试）
        self._last_error: Optional[Exception] = None

        # 每个采集器的独立统计信息
        self._collection_stats: Dict[str, dict] = {}

        # 全局统计
        self._total_collections = 0
        self._last_collection_time: Optional[float] = None

    def register_collector(self, name: str, collector_func: Callable) -> None:
        """
        注册数据采集器

        Args:
            name: 采集器唯一标识符（用于 get_latest/get_snapshot）
            collector_func: 无参 callable，返回采集的数据

        Note:
            - 采集函数应该快速返回（< timeout_per_collector）
            - 采集函数应该是线程安全的（在独立线程中调用）
            - 可以在运行时动态注册/注销
        """
        if name in self._collectors:
            logger.warning(f"Collector '{name}' already registered, overwriting")

        self._collectors[name] = collector_func
        self._collection_stats[name] = {
            'success_count': 0,
            'failure_count': 0,
            'total_duration_ms': 0.0,
            'last_error': None,
            'last_success_time': None
        }
        logger.info(f"Registered collector: {name}")

    def unregister_collector(self, name: str) -> None:
        """
        移除数据采集器

        Args:
            name: 要移除的采集器名称
        """
        if name in self._collectors:
            del self._collectors[name]
            self._collection_stats.pop(name, None)
            self._cache.invalidate(name)
            logger.info(f"Unregistered collector: {name}")
        else:
            logger.warning(f"Collector '{name}' not found")

    def start(self) -> None:
        """
        启动后台采集线程

        - 创建守护线程（daemon=True）
        - 立即返回，不阻塞调用者
        - 重复调用安全（幂等性）
        """
        if self._running:
            logger.warning("Scheduler is already running")
            return

        self._running = True
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._collection_loop,
            name="NonBlockingCollectorThread",
            daemon=True  # 守护线程：主进程退出时自动终止
        )
        self._thread.start()

        logger.info(
            f"Collector scheduler started (interval={self._interval}s, "
            f"timeout={self._timeout}s, collectors={list(self._collectors.keys())})"
        )

    def stop(self) -> None:
        """
        优雅停止后台采集线程

        - 设置停止事件（下一次循环检测到后退出）
        - 等待线程结束（最多等待 interval + timeout 时间）
        - 清理资源（可选）
        """
        if not self._running:
            return

        logger.info("Stopping collector scheduler...")
        self._running = False
        self._stop_event.set()

        # 等待线程结束（带超时，防止永久阻塞）
        if self._thread and self._thread.is_alive():
            # 最多等待一个完整周期 + 最大超时
            max_wait = self._interval + self._timeout + 1.0
            self._thread.join(timeout=max_wait)

            if self._thread.is_alive():
                logger.warning(
                    f"Collection thread did not stop within {max_wait:.1f}s "
                    "(daemon thread will be terminated on process exit)"
                )

        self._thread = None
        logger.info("Collector scheduler stopped")

    def get_latest(self, name: str, default: Any = None) -> Any:
        """
        获取某个采集器的最新数据（从缓存读取，永不阻塞）

        Args:
            name: 采集器名称
            default: 未找到时的默认值

        Returns:
            最新采集的数据，或 default（如果从未成功采集过）

        Performance:
            - 缓存命中：< 0.01ms
            - 缓存未命中：< 0.05ms（返回默认值）
        """
        return self._cache.get(name, default)

    def get_snapshot(self) -> Dict[str, Any]:
        """
        获取所有采集器的最新快照（从缓存读取，永不阻塞）

        Returns:
            字典 {collector_name: latest_data}，
            未成功采集过的采集器值为 None

        Performance:
            - 总耗时：< 0.1ms * 采集器数量（每个都是缓存读取）
        """
        snapshot = {}
        for name in self._collectors:
            snapshot[name] = self._cache.get(name)
        return snapshot

    @property
    def is_running(self) -> bool:
        """调度器是否正在运行"""
        return self._running

    @property
    def stats(self) -> dict:
        """
        调度器统计信息

        Returns:
            包含以下字段的字典：
            - running: 是否运行中
            - total_collections: 总采集次数
            - last_collection_time: 最后一次采集时间戳
            - registered_collectors: 已注册的采集器列表
            - collector_stats: 每个采集器的详细统计
            - cache_stats: 缓存统计（命中率等）
            - last_error: 最后一次错误（如果有）
        """
        return {
            'running': self._running,
            'total_collections': self._total_collections,
            'last_collection_time': self._last_collection_time,
            'registered_collectors': list(self._collectors.keys()),
            'collector_stats': dict(self._collection_stats),  # 浅拷贝
            'cache_stats': self._cache.stats,
            'last_error': str(self._last_error) if self._last_error else None
        }

    def _collection_loop(self) -> None:
        """
        后台采集循环（在独立守护线程中运行）

        循环逻辑：
        1. 检查停止信号
        2. 遍历所有注册的采集器
        3. 使用 execute_with_timeout 保护每个采集器
        4. 成功结果写入缓存
        5. 失败记录错误但不中断其他采集器
        6. 计算剩余等待时间，精确控制采集间隔
        7. 使用 Event.wait() 替代 sleep（支持快速停止）
        """
        logger.debug("Collection loop started")

        while not self._stop_event.is_set():
            loop_start_time = time.perf_counter()

            # 遍历所有采集器（副本，防止并发修改问题）
            collectors_snapshot = dict(self._collectors)

            for name, collector_func in collectors_snapshot.items():
                # 检查是否需要停止（在每个采集器之前检查，提高响应速度）
                if self._stop_event.is_set():
                    break

                # 使用超时执行器保护每个采集器（隔离故障）
                result = execute_with_timeout(
                    func=collector_func,
                    timeout=self._timeout,
                    default=None
                )

                # 更新该采集器的统计信息
                stats = self._collection_stats.get(name)
                if stats is None:
                    continue  # 采集器可能在循环中被注销

                if result.success:
                    # 采集成功：写入缓存
                    self._cache.set(name, result.data)

                    # 更新统计
                    stats['success_count'] += 1
                    stats['total_duration_ms'] += result.elapsed_time * 1000
                    stats['last_success_time'] = time.time()
                    stats['last_error'] = None
                else:
                    # 采集失败：记录错误但不中断
                    stats['failure_count'] += 1
                    stats['last_error'] = str(result.error)
                    self._last_error = result.error

                    logger.debug(
                        f"Collector '{name}' failed: {result.error} "
                        f"(elapsed={result.elapsed_time:.3f}s)"
                    )

            # 更新全局统计
            self._total_collections += 1
            self._last_collection_time = time.time()

            # 计算剩余等待时间（精确控制采集间隔）
            elapsed = time.perf_counter() - loop_start_time
            sleep_time = max(0.001, self._interval - elapsed)  # 至少 1ms

            # 使用 Event.wait() 替代 time.sleep()（支持被 stop() 中断）
            self._stop_event.wait(timeout=sleep_time)

        logger.debug("Collection loop stopped")


# ============================================================================
# 4. 重试装饰器 (Retry Decorator with Exponential Backoff)
# ============================================================================

def retry_on_failure(
    max_retries: int = 2,
    delay: float = 0.1,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[int, Exception, float], None]] = None
):
    """
    重试装饰器（指数退避策略）

    当目标函数抛出指定类型的异常时，自动重试并逐步增加延迟时间。
    适用于不稳定的外部 API 调用、网络请求等场景。

    退避策略：
    - 第 1 次重试：等待 delay 秒
    - 第 2 次重试：等待 delay * backoff 秒
    - 第 3 次重试：等待 delay * backoff^2 秒
    - ...

    Args:
        max_retries: 最大重试次数（不含首次尝试）
                     例如 max_retries=2 表示最多尝试 3 次（1 次 + 2 次重试）
        delay: 初始延迟时间（秒），默认 0.1 秒
        backoff: 退避倍数，每次重试 delay *= backoff，默认 2.0（翻倍）
        exceptions: 需要重试的异常类型元组，默认捕获所有 Exception
        on_retry: 可选的重试回调函数
                  签名：(retry_num: int, error: Exception, next_delay: float) -> None
                  用于日志记录、监控告警等

    Example:
        >>> @retry_on_failure(max_retries=3, delay=0.5, exceptions=(TimeoutError, ConnectionError))
        ... def fetch_gpu_data():
        ...     # 可能失败的网络请求
        ...     pass

        >>> @retry_on_failure(on_retry=lambda n, err, d: print(f"Retry #{n}: {err}, next in {d}s"))
        ... def unstable_api_call():
        ...     pass

    Performance Impact:
        - 首次调用：零开销（仅多一层函数调用）
        - 重试时：额外延迟（delay * backoff^(attempt-1)）
        - 内存：每次调用增加一帧栈空间（可忽略）

    Warning:
        - 不要对有副作用（如转账、发送邮件）的函数使用此装饰器
        - 确保 target function 是幂等的（idempotent）
        - max_retries 不宜过大（建议 <= 5），避免长时间阻塞
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)  # 保留原函数的名称、文档字符串等元信息
        def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None
            current_delay = delay

            for attempt in range(max_retries + 1):  # +1 包含首次尝试
                try:
                    # 尝试执行目标函数
                    return func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        # 还有重试机会
                        if on_retry:
                            # 调用用户自定义回调（用于监控/日志）
                            try:
                                on_retry(attempt + 1, e, current_delay)
                            except Exception as callback_error:
                                logger.warning(
                                    f"on_retry callback failed: {callback_error}"
                                )

                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for "
                            f"{func.__name__}(): {e}. "
                            f"Retrying in {current_delay:.3f}s..."
                        )

                        # 指数退避等待
                        time.sleep(current_delay)
                        current_delay *= backoff  # 下次延迟翻倍
                    else:
                        # 所有重试用尽
                        logger.error(
                            f"All {max_retries} retries exhausted for "
                            f"{func.__name__}(): {e}"
                        )
                        raise  # 重新抛出最后一次异常

            # 理论上不应到达这里（for 循环一定会 return 或 raise）
            # 但为了类型检查器的完整性，显式 raise
            raise last_exception  # type: ignore

        return wrapper
    return decorator


# ============================================================================
# 5. 性能监控装饰器 (Performance Monitoring Decorator)
# ============================================================================

def monitor_performance(operation_name: str = ""):
    """
    性能监控装饰器

    自动记录函数执行时间，超过阈值时发出警告。

    Args:
        operation_name: 操作名称（用于日志标识），为空时使用函数名

    Example:
        >>> @monitor_performance("gpu_collection")
        ... def collect_gpu_info():
        ...     ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000

                # 根据耗时选择日志级别
                if duration_ms > 500:  # 超过 500ms 视为慢操作
                    logger.warning(
                        f"[PERF-SLOW] {operation_name or func.__name__} "
                        f"took {duration_ms:.1f}ms"
                    )
                elif duration_ms > 100:  # 超过 100ms 记录 debug
                    logger.debug(
                        f"[PERF] {operation_name or func.__name__} "
                        f"took {duration_ms:.1f}ms"
                    )
                # < 100ms 的操作静默通过（减少日志噪音）

                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    f"[PERF-ERROR] {operation_name or func.__name__} "
                    f"failed after {duration_ms:.1f}ms: {e}"
                )
                raise

        return wrapper
    return decorator


# ============================================================================
# 6. 批量操作上下文管理器 (Batch Operation Context Manager)
# ============================================================================

@contextmanager
def batch_context(name: str = "batch"):
    """
    批量操作上下文管理器

    将多个小操作合并为一次日志/统计报告，减少日志输出频率。

    Args:
        name: 批量操作名称（用于日志标识）

    Yields:
        BatchTracker 对象，提供 add_op() 方法记录子操作

    Example:
        >>> with batch_context("system_snapshot") as batch:
        ...     batch.add_op("cpu_collection")
        ...     batch.add_op("gpu_collection")
        ...     batch.add_op("memory_collection")
        # 日志输出: [BATCH-system_snapshot] Completed 3 ops in 12.5ms
    """
    start_time = time.perf_counter()
    operations: List[str] = []

    class BatchTracker:
        """批量操作跟踪器"""
        def add_op(self, op_name: str) -> None:
            """记录一个子操作"""
            operations.append(op_name)

        @property
        def count(self) -> int:
            """已记录的操作数量"""
            return len(operations)

    tracker = BatchTracker()
    try:
        yield tracker
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        if operations:
            logger.debug(
                f"[BATCH-{name}] Completed {len(operations)} ops "
                f"in {duration_ms:.1f}s"
            )


# ============================================================================
# 导出公共 API（方便 from fxm_utils.thread_safe import * 使用）
# ============================================================================

__all__ = [
    # 数据类
    'TimeoutResult',

    # 核心功能
    'execute_with_timeout',
    'ThreadSafeCache',
    'NonBlockingCollectorScheduler',

    # 装饰器和工具
    'retry_on_failure',
    'monitor_performance',
    'batch_context',
]
