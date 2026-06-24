"""
CPU 采集器对比基准测试。

对比 /proc/stat 与 psutil 两种采集方式在 100 次采样中的：
- 采集耗时（单次与累计）
- 总 CPU 使用率数值差异
- 每核使用率数值差异

运行方式::

    python benchmarks/cpu_collector_benchmark.py

说明：
- 本脚本不是插件加载的一部分，仅用于开发/验证。
- 由于 psutil 内部在 Linux 上也会读取 /proc/stat，两者理论上应非常接近；
  差异主要来源于采样时刻、计算精度和实现开销。
"""

from __future__ import annotations

import os
import sys
import time
from statistics import mean
from typing import List, Tuple

# 将项目根目录加入模块搜索路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import psutil  # noqa: E402

from collectors.proc_stat_collector import ProcStatCollector  # noqa: E402


# ============================================================================
# 辅助函数
# ============================================================================

def _mean_absolute_error(a: List[float], b: List[float]) -> float:
    """计算两组数之间的平均绝对误差。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    return mean(abs(x - y) for x, y in zip(a, b))


def _max_absolute_diff(a: List[float], b: List[float]) -> float:
    """计算两组数之间的最大绝对差。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    return max(abs(x - y) for x, y in zip(a, b))


def _sample_psutil() -> Tuple[float, List[float], float]:
    """使用 psutil 采集一次 CPU 使用率并返回（总使用率，每核使用率，耗时）。"""
    start = time.perf_counter()
    total = psutil.cpu_percent(interval=None)
    per_core = psutil.cpu_percent(percpu=True, interval=None)
    elapsed = time.perf_counter() - start
    return float(total), [float(x) for x in per_core], elapsed


def _sample_procstat(
    collector: ProcStatCollector,
) -> Tuple[float, List[float], float]:
    """使用 /proc/stat 采集一次 CPU 使用率并返回（总使用率，每核使用率，耗时）。"""
    start = time.perf_counter()
    total, per_core = collector.get_cpu_percent(interval=None)
    elapsed = time.perf_counter() - start
    return float(total), [float(x) for x in per_core], elapsed


def run_benchmark(sample_count: int = 100, sleep_interval: float = 0.05) -> dict:
    """
    运行对比基准测试。

    Args:
        sample_count: 采样次数，默认 100。
        sleep_interval: 每次采样之间的间隔（秒），默认 0.05 秒。

    Returns:
        包含统计结果的字典。
    """
    collector = ProcStatCollector()
    if not collector.available:
        print("错误：当前系统不支持 /proc/stat，无法运行本基准测试。")
        sys.exit(1)

    # 预热：让两个采集器都建立历史基准
    collector.get_cpu_percent(interval=None)
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(percpu=True, interval=None)
    time.sleep(0.1)

    proc_total_samples: List[float] = []
    proc_core_samples: List[List[float]] = []
    proc_times: List[float] = []

    psutil_total_samples: List[float] = []
    psutil_core_samples: List[List[float]] = []
    psutil_times: List[float] = []

    total_mae_list: List[float] = []
    core_mae_list: List[float] = []

    print(f"开始采集 {sample_count} 个样本，间隔 {sleep_interval * 1000:.0f} ms...")

    for i in range(sample_count):
        # 先采集 /proc/stat，再采集 psutil，尽量减小时间差
        p_total, p_cores, p_time = _sample_procstat(collector)
        s_total, s_cores, s_time = _sample_psutil()

        proc_total_samples.append(p_total)
        proc_core_samples.append(p_cores)
        proc_times.append(p_time)

        psutil_total_samples.append(s_total)
        psutil_core_samples.append(s_cores)
        psutil_times.append(s_time)

        if len(p_cores) == len(s_cores):
            total_mae_list.append(abs(p_total - s_total))
            core_mae_list.append(_mean_absolute_error(p_cores, s_cores))

        if (i + 1) % 10 == 0:
            print(f"  已完成 {i + 1}/{sample_count} 个样本")

        if i < sample_count - 1:
            time.sleep(sleep_interval)

    # 汇总统计
    total_diff_mae = mean(total_mae_list) if total_mae_list else 0.0
    total_diff_max = max(total_mae_list) if total_mae_list else 0.0
    core_diff_mae = mean(core_mae_list) if core_mae_list else 0.0

    proc_total_mean = mean(proc_total_samples) if proc_total_samples else 0.0
    psutil_total_mean = mean(psutil_total_samples) if psutil_total_samples else 0.0

    return {
        "sample_count": sample_count,
        "proc": {
            "total_mean": proc_total_mean,
            "total_min": min(proc_total_samples) if proc_total_samples else 0.0,
            "total_max": max(proc_total_samples) if proc_total_samples else 0.0,
            "avg_time_ms": mean(proc_times) * 1000 if proc_times else 0.0,
            "total_time_ms": sum(proc_times) * 1000,
        },
        "psutil": {
            "total_mean": psutil_total_mean,
            "total_min": min(psutil_total_samples) if psutil_total_samples else 0.0,
            "total_max": max(psutil_total_samples) if psutil_total_samples else 0.0,
            "avg_time_ms": mean(psutil_times) * 1000 if psutil_times else 0.0,
            "total_time_ms": sum(psutil_times) * 1000,
        },
        "accuracy": {
            "total_mae": total_diff_mae,
            "total_max_diff": total_diff_max,
            "core_mae": core_diff_mae,
        },
    }


def print_report(report: dict) -> None:
    """打印基准测试报告。"""
    print("\n" + "=" * 60)
    print("CPU 采集器对比基准测试报告")
    print("=" * 60)

    print(f"\n采样次数: {report['sample_count']}")

    print("\n--- /proc/stat ---")
    print(f"  总使用率均值: {report['proc']['total_mean']:.2f}%")
    print(f"  总使用率范围: {report['proc']['total_min']:.2f}% ~ {report['proc']['total_max']:.2f}%")
    print(f"  单次平均耗时: {report['proc']['avg_time_ms']:.4f} ms")
    print(f"  累计耗时:     {report['proc']['total_time_ms']:.2f} ms")

    print("\n--- psutil ---")
    print(f"  总使用率均值: {report['psutil']['total_mean']:.2f}%")
    print(
        f"  总使用率范围: {report['psutil']['total_min']:.2f}% ~ {report['psutil']['total_max']:.2f}%"
    )
    print(f"  单次平均耗时: {report['psutil']['avg_time_ms']:.4f} ms")
    print(f"  累计耗时:     {report['psutil']['total_time_ms']:.2f} ms")

    print("\n--- 准确性对比（以 /proc/stat 为基准）---")
    print(f"  总使用率 MAE:  {report['accuracy']['total_mae']:.3f}%")
    print(f"  总使用率最大差:{report['accuracy']['total_max_diff']:.3f}%")
    print(f"  每核使用率 MAE:{report['accuracy']['core_mae']:.3f}%")

    speedup = (
        report["psutil"]["avg_time_ms"] / report["proc"]["avg_time_ms"]
        if report["proc"]["avg_time_ms"] > 0
        else 0.0
    )
    print(f"\n  /proc/stat 相对 psutil 耗时比: {speedup:.2f}x")
    print("=" * 60)


if __name__ == "__main__":
    report = run_benchmark(sample_count=100, sleep_interval=0.05)
    print_report(report)
