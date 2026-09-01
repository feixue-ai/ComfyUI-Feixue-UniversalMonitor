"""
FeixueMonitor - 监控快照环形缓冲区持久化

DIAG（诊断器）功能子模块：将每次采集到的系统监控快照追加写入磁盘，
保留最近 N 条记录，用于崩溃/黑屏等事后分析。

核心设计原则：
1. 零阻塞：主监控循环仅将快照放入队列，实际 I/O 由后台工作线程完成
2. 静默降级：任何写入/读取失败都不影响主监控流程，仅记录 debug 日志
3. 环形截断：文件仅保留最近 max_entries 条快照，防止磁盘无限增长
4. JSON Lines：每行一条快照，便于追加读取和崩溃后人工查看

接口：
- append_snapshot(snapshot): 将快照追加到环形缓冲区（非阻塞）
- read_recent_snapshots(seconds=30): 读取最近 N 秒的快照列表

Version: 1.0.0
Author: Feixue Team
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.config_manager import get_config_manager

logger = logging.getLogger(__name__)

DEFAULT_RING_PATH = "~/.cache/feixue_monitor/snapshot_ring.jsonl"
DEFAULT_MAX_ENTRIES = 120
BATCH_SIZE = 16          # 每次批量写入的最大条数
TRUNCATE_FRACTION = 2    # 每写入 max_entries // TRUNCATE_FRACTION 条后检查截断
QUEUE_TIMEOUT = 0.1      # 工作线程队列等待超时（秒）
SHUTDOWN_TIMEOUT = 2.0   # 关闭时等待工作线程结束的最大时间（秒）


class SnapshotRingBuffer:
    """
    快照环形缓冲区。

    使用后台工作线程异步追加写入 JSON Lines 文件，并定期截断旧记录。
    所有公共方法都对异常进行捕获，保证调用方（监控循环）永不阻塞、永不崩溃。
    """

    def __init__(
        self,
        ring_path: Optional[str] = None,
        max_entries: Optional[int] = None,
    ):
        """
        初始化环形缓冲区。

        Args:
            ring_path: 环形缓冲区文件路径，默认从 config 读取或回退到 ~/.cache/...
            max_entries: 最大保留条数，默认从 config 读取或回退到 120
        """
        config = get_config_manager()

        path_str = ring_path
        if path_str is None:
            path_str = config.get("diag.snapshot_ring_path", DEFAULT_RING_PATH)
        self._ring_path = Path(path_str).expanduser()

        max_val = max_entries
        if max_val is None:
            max_val = config.get("diag.snapshot_ring_max_entries", DEFAULT_MAX_ENTRIES)
        try:
            self._max_entries = int(max_val)
        except (TypeError, ValueError):
            self._max_entries = DEFAULT_MAX_ENTRIES
        if self._max_entries < 1:
            self._max_entries = DEFAULT_MAX_ENTRIES

        self._queue: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._shutdown = False
        self._lock = threading.Lock()
        self._written_since_truncate = 0
        self._truncate_threshold = max(1, self._max_entries // TRUNCATE_FRACTION)

        self._ensure_dir()
        self._start_worker()

    def _ensure_dir(self) -> None:
        """确保目标目录存在，失败时静默降级。"""
        try:
            self._ring_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug(f"Snapshot ring directory creation failed: {e}")

    def _start_worker(self) -> None:
        """启动后台写入工作线程。"""
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="FeixueSnapshotRing-Worker",
        )
        self._worker_thread.start()

    def append(self, snapshot: Dict[str, Any]) -> None:
        """
        将快照追加到环形缓冲区（非阻塞，立即返回）。

        Args:
            snapshot: 监控快照字典，必须可 JSON 序列化
        """
        if self._shutdown:
            return
        if not isinstance(snapshot, dict):
            return

        try:
            # 仅入队操作，耗时极短（微秒级），不阻塞监控循环
            self._queue.put_nowait(snapshot)
        except Exception:
            # 静默降级：队列满或已关闭时直接丢弃
            pass

    def _worker_loop(self) -> None:
        """后台工作线程：批量取出快照并追加写入文件。"""
        while not self._shutdown:
            batch = self._collect_batch()
            if batch is None:
                # 收到 shutdown 信号
                break
            if batch:
                self._do_append_batch(batch)
                self._maybe_truncate()

    def _collect_batch(self) -> Optional[List[Dict[str, Any]]]:
        """
        从队列中收集一批快照。

        Returns:
            快照列表；若收到 shutdown 信号则返回 None。
        """
        batch: List[Dict[str, Any]] = []
        try:
            item = self._queue.get(timeout=QUEUE_TIMEOUT)
        except queue.Empty:
            return batch

        if item is None:
            return None

        batch.append(item)
        while len(batch) < BATCH_SIZE:
            try:
                item = self._queue.get_nowait()
                if item is None:
                    self._shutdown = True
                    return None
                batch.append(item)
            except queue.Empty:
                break
        return batch

    def _do_append_batch(self, batch: List[Dict[str, Any]]) -> None:
        """将一批快照追加到 JSON Lines 文件。"""
        try:
            lines = [
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                for snapshot in batch
            ]
            with open(self._ring_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
                f.flush()
                # os.fsync 保证崩溃后数据不丢失，但可能耗时；仍在后台线程执行
                os.fsync(f.fileno())
            self._written_since_truncate += len(batch)
        except Exception as e:
            logger.debug(f"Snapshot batch append failed: {e}")

    def _maybe_truncate(self) -> None:
        """当写入量达到阈值时，截断文件只保留最近 max_entries 条。"""
        if self._written_since_truncate < self._truncate_threshold:
            return

        self._written_since_truncate = 0
        try:
            if not self._ring_path.exists():
                return

            with open(self._ring_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if len(lines) <= self._max_entries:
                return

            keep_lines = lines[-self._max_entries :]
            tmp_path = self._ring_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(keep_lines)
                f.flush()
                os.fsync(f.fileno())
            tmp_path.replace(self._ring_path)
        except Exception as e:
            logger.debug(f"Snapshot ring truncate failed: {e}")

    def read_recent(self, seconds: float = 30.0) -> List[Dict[str, Any]]:
        """
        读取最近 N 秒的快照。

        Args:
            seconds: 时间窗口（秒），默认 30

        Returns:
            快照字典列表，按文件中顺序排列
        """
        cutoff = time.time() - seconds
        result: List[Dict[str, Any]] = []
        try:
            if not self._ring_path.exists():
                return result

            with open(self._ring_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        ts = data.get("timestamp", 0)
                        if ts >= cutoff:
                            result.append(data)
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"Read recent snapshots failed: {e}")
        return result

    @property
    def ring_path(self) -> Path:
        """当前环形缓冲区文件路径。"""
        return self._ring_path

    @property
    def max_entries(self) -> int:
        """最大保留条数。"""
        return self._max_entries

    def shutdown(self) -> None:
        """优雅关闭后台工作线程。"""
        self._shutdown = True
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=SHUTDOWN_TIMEOUT)


# ============================================================================
# 全局单例与便捷接口
# ============================================================================

_global_ring: Optional[SnapshotRingBuffer] = None
_instance_lock = threading.Lock()


def get_snapshot_ring(
    ring_path: Optional[str] = None,
    max_entries: Optional[int] = None,
) -> SnapshotRingBuffer:
    """
    获取全局 SnapshotRingBuffer 单例实例。

    Returns:
        SnapshotRingBuffer 全局实例
    """
    global _global_ring

    if _global_ring is None:
        with _instance_lock:
            if _global_ring is None:
                _global_ring = SnapshotRingBuffer(
                    ring_path=ring_path,
                    max_entries=max_entries,
                )

    return _global_ring


def append_snapshot(snapshot: Dict[str, Any]) -> None:
    """
    将快照追加到全局环形缓冲区（非阻塞）。

    Args:
        snapshot: 监控快照字典
    """
    try:
        get_snapshot_ring().append(snapshot)
    except Exception:
        # 最后一层防护：无论如何不影响调用方
        pass


def read_recent_snapshots(seconds: float = 30.0) -> List[Dict[str, Any]]:
    """
    从全局环形缓冲区读取最近 N 秒快照。

    Args:
        seconds: 时间窗口（秒）

    Returns:
        快照字典列表
    """
    try:
        return get_snapshot_ring().read_recent(seconds)
    except Exception:
        return []


def reset_snapshot_ring() -> None:
    """重置全局单例（主要用于测试）。"""
    global _global_ring

    with _instance_lock:
        if _global_ring is not None:
            try:
                _global_ring.shutdown()
            except Exception:
                pass
            _global_ring = None


if __name__ == "__main__":
    # 简单自测
    import tempfile

    tmp_file = tempfile.mktemp(suffix=".jsonl")
    ring = SnapshotRingBuffer(ring_path=tmp_file, max_entries=10)

    for i in range(15):
        ring.append({"timestamp": time.time(), "idx": i, "v": i * 10})
        time.sleep(0.01)

    time.sleep(0.3)  # 等待后台线程写入
    recent = ring.read_recent(seconds=5)
    print(f"Written 15, recent count: {len(recent)}")
    print(f"Ring path: {ring.ring_path}")

    ring.shutdown()
    os.remove(tmp_file)
