#!/usr/bin/env python3
"""
Feixue Monitor - Ubuntu GPU Provider 准确性对比测试

目标：在相同时间点对比 sysfs / amdsmi / rocm_smi 三个 Provider 的读数
      与 sysfs 直接读取、rocm-smi 命令行基准的差异，为优先级调整提供数据。

运行方式（需激活 ComfyUI venv 或系统 Python）：
    cd /home/woman/AI/ComfyUI/custom_nodes/ComfyUI-Feixue-UniversalMonitor
    python tools/provider_accuracy_test.py

可选参数：
    --samples 30          采样次数（默认 30）
    --interval 1.0        采样间隔秒数（默认 1.0）
    --load                是否在采样期间生成轻量 GPU 负载（默认否）
    --output <path>       CSV/报告输出目录（默认 tools/provider_accuracy_report）
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

# 把插件根目录加入 sys.path，确保能导入 collectors/core
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

import torch

from collectors.gpu_providers import AmdRocmProvider, AmdSmiProvider, AmdSysfsProvider


@dataclass
class Sample:
    """单次采样结果"""
    ts: float
    provider: str
    gpu_util: Optional[float] = None
    vram_used_mb: Optional[float] = None
    vram_total_mb: Optional[float] = None
    temp_c: Optional[float] = None
    power_w: Optional[float] = None
    error: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class GroundTruth:
    """基准读数"""
    ts: float
    source: str
    gpu_util: Optional[float] = None
    vram_used_mb: Optional[float] = None
    vram_total_mb: Optional[float] = None
    temp_c: Optional[float] = None
    power_w: Optional[float] = None
    error: Optional[str] = None


class SysfsGroundTruth:
    """直接读取 /sys/class/drm/card*/device 下的文件作为 sysfs 基准"""

    AMD_VENDOR_ID = "0x1002"

    def __init__(self, device_id: int = 0):
        self.device_id = device_id
        self.base = self._resolve_device_path(device_id)

    def _resolve_device_path(self, device_id: int) -> Optional[Path]:
        """按 device_id 顺序找到第 N 个 AMD GPU 的 device 路径"""
        try:
            cards = sorted(Path("/sys/class/drm").glob("card*"))
        except OSError:
            return None

        amd_idx = 0
        for card_path in cards:
            if not re.match(r"^card\d+$", card_path.name):
                continue
            device_link = card_path / "device"
            vendor_file = device_link / "vendor"
            try:
                if vendor_file.exists():
                    vendor = vendor_file.read_text().strip().lower()
                    if self.AMD_VENDOR_ID in vendor or "1002" in vendor:
                        if amd_idx == device_id:
                            return device_link
                        amd_idx += 1
            except (IOError, OSError):
                continue
        return None

    def _read_int(self, rel_path: str, divisor: float = 1.0) -> Optional[float]:
        try:
            if self.base is None:
                return None
            # 支持 hwmon/hwmon*/xxx 的 glob 模式
            if "*" in rel_path:
                matches = sorted(self.base.glob(rel_path))
                for p in matches:
                    if p.exists():
                        val = int(p.read_text().strip())
                        return val / divisor
                return None
            p = self.base / rel_path
            if not p.exists():
                return None
            val = int(p.read_text().strip())
            return val / divisor
        except Exception:
            return None

    def read(self) -> GroundTruth:
        ts = time.time()
        gt = GroundTruth(ts=ts, source="sysfs_direct")
        if self.base is None:
            gt.error = f"AMD GPU device {self.device_id} not found in sysfs"
            return gt
        # VRAM (bytes -> MiB)
        gt.vram_total_mb = self._read_int("mem_info_vram_total", 1024 * 1024)
        gt.vram_used_mb = self._read_int("mem_info_vram_used", 1024 * 1024)
        # GPU busy percent
        gt.gpu_util = self._read_int("gpu_busy_percent")
        # 温度：优先 junction (temp2)，其次 edge (temp1)
        for temp_name in ("hwmon/hwmon*/temp2_input", "hwmon/hwmon*/temp1_input"):
            t = self._read_int(temp_name, 1000)
            if t is not None:
                gt.temp_c = t
                break
        # 功耗
        gt.power_w = self._read_int("hwmon/hwmon*/power1_average", 1_000_000)
        return gt


class RocmSmiGroundTruth:
    """调用 rocm-smi 作为 ROCm 官方基准"""

    def __init__(self, device_id: int = 0):
        self.device_id = device_id

    def read(self) -> GroundTruth:
        ts = time.time()
        gt = GroundTruth(ts=ts, source="rocm-smi")
        try:
            out = subprocess.run(
                [
                    "rocm-smi",
                    "--showmeminfo", "vram",
                    "--showuse",
                    "--showtemp",
                    "--showpower",
                    "--csv",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = out.stdout.strip().splitlines()
            if len(lines) < 2:
                gt.error = "rocm-smi output too short"
                return gt
            headers = [h.strip() for h in lines[0].split(",")]
            values = [v.strip() for v in lines[1].split(",")]
            data = dict(zip(headers, values))

            def get_float(keys):
                for k in keys:
                    if k in data and data[k] not in ("", "N/A"):
                        try:
                            return float(data[k])
                        except ValueError:
                            pass
                return None

            gt.temp_c = get_float([
                "Temperature (Sensor junction) (C)",
                "Temperature (Sensor edge) (C)",
            ])
            gt.power_w = get_float(["Average Graphics Package Power (W)"])
            gt.gpu_util = get_float(["GPU use (%)"])
            gt.vram_total_mb = get_float(["VRAM Total Memory (B)"])
            if gt.vram_total_mb is not None:
                gt.vram_total_mb /= 1024 * 1024
            gt.vram_used_mb = get_float(["VRAM Total Used Memory (B)"])
            if gt.vram_used_mb is not None:
                gt.vram_used_mb /= 1024 * 1024
        except Exception as e:
            gt.error = str(e)
        return gt


def run_provider(provider_cls, device_id: int = 0) -> Sample:
    """初始化并采集单个 Provider"""
    ts = time.time()
    sample = Sample(ts=ts, provider=provider_cls.__name__)
    try:
        provider = provider_cls()
        t0 = time.perf_counter()
        ok = provider.initialize()
        if not ok:
            sample.error = "initialize returned False"
            return sample
        metrics = provider.get_metrics(device_id)
        sample.latency_ms = (time.perf_counter() - t0) * 1000
        sample.gpu_util = metrics.gpu_utilization
        sample.vram_used_mb = metrics.vram_used
        sample.vram_total_mb = metrics.vram_total
        sample.temp_c = metrics.temperature
        sample.power_w = metrics.power_usage
        provider.shutdown()
    except Exception as e:
        sample.error = str(e)
    return sample


def generate_gpu_load(duration_s: float, device_id: int = 0):
    """生成轻量 GPU 负载，使利用率/功耗有变化"""
    try:
        dev = torch.device(f"cuda:{device_id}")
        a = torch.randn(2048, 2048, device=dev)
        b = torch.randn(2048, 2048, device=dev)
        t_end = time.time() + duration_s
        while time.time() < t_end:
            _ = torch.matmul(a, b)
            torch.cuda.synchronize(dev)
    except Exception as e:
        print(f"[WARN] GPU load generation failed: {e}")


def collect_round(
    providers: List[Any],
    device_id: int,
    load: bool,
    load_duration: float = 0.8,
) -> Tuple[List[Sample], List[GroundTruth]]:
    """单次采样轮次：先启动负载，再同时采集 Provider 和基准"""
    if load:
        # 用后台线程生成负载，让采集和负载并行
        import threading

        load_thread = threading.Thread(
            target=generate_gpu_load, args=(load_duration, device_id), daemon=True
        )
        load_thread.start()

    samples = []
    for cls in providers:
        samples.append(run_provider(cls, device_id))

    truths = [
        SysfsGroundTruth(device_id).read(),
        RocmSmiGroundTruth(device_id).read(),
    ]

    if load:
        load_thread.join(timeout=load_duration + 2)

    return samples, truths


def write_csv(
    output_dir: Path,
    samples: List[List[Sample]],
    truths: List[List[GroundTruth]],
):
    """把原始数据写成 CSV"""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "raw_samples.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "round",
                "timestamp",
                "source",
                "gpu_util",
                "vram_used_mb",
                "vram_total_mb",
                "temp_c",
                "power_w",
                "latency_ms",
                "error",
            ]
        )
        for i, (round_samples, round_truths) in enumerate(zip(samples, truths), 1):
            for s in round_samples:
                writer.writerow(
                    [
                        i,
                        s.ts,
                        s.provider,
                        s.gpu_util,
                        s.vram_used_mb,
                        s.vram_total_mb,
                        s.temp_c,
                        s.power_w,
                        s.latency_ms,
                        s.error or "",
                    ]
                )
            for gt in round_truths:
                writer.writerow(
                    [
                        i,
                        gt.ts,
                        gt.source,
                        gt.gpu_util,
                        gt.vram_used_mb,
                        gt.vram_total_mb,
                        gt.temp_c,
                        gt.power_w,
                        "",
                        gt.error or "",
                    ]
                )
    return csv_path


def compute_error_series(
    provider_samples: List[Sample],
    truth_series: List[GroundTruth],
    metric: str,
) -> Dict[str, float]:
    """计算某指标与基准序列的误差统计"""
    diffs = []
    rel_errs = []
    missing = 0
    for s, gt in zip(provider_samples, truth_series):
        pv = getattr(s, metric)
        tv = getattr(gt, metric)
        if pv is None or tv is None or s.error or gt.error:
            missing += 1
            continue
        diffs.append(pv - tv)
        if tv != 0:
            rel_errs.append(abs(pv - tv) / abs(tv) * 100)

    if not diffs:
        return {"mean_abs_err": None, "max_abs_err": None, "mean_rel_err": None, "missing": missing}

    return {
        "mean_abs_err": round(mean([abs(d) for d in diffs]), 3),
        "max_abs_err": round(max([abs(d) for d in diffs]), 3),
        "mean_rel_err": round(mean(rel_errs), 2) if rel_errs else None,
        "missing": missing,
    }


def build_report(
    samples: List[List[Sample]],
    truths: List[List[GroundTruth]],
    metrics: List[str],
) -> Dict[str, Any]:
    """生成对比报告"""
    # 按 provider 分组
    by_provider: Dict[str, List[Sample]] = {}
    for round_samples in samples:
        for s in round_samples:
            by_provider.setdefault(s.provider, []).append(s)

    # 按基准源分组
    by_truth: Dict[str, List[GroundTruth]] = {}
    for round_truths in truths:
        for gt in round_truths:
            by_truth.setdefault(gt.source, []).append(gt)

    report: Dict[str, Any] = {
        "rounds": len(samples),
        "providers": list(by_provider.keys()),
        "ground_truths": list(by_truth.keys()),
        "provider_init_errors": {},
        "comparisons": {},
    }

    # 记录初始化失败次数
    for pname, plist in by_provider.items():
        errors = sum(1 for s in plist if s.error)
        report["provider_init_errors"][pname] = errors

    # 对比：每个 provider vs 每个 truth source
    for pname, plist in by_provider.items():
        report["comparisons"][pname] = {}
        for tname, tlist in by_truth.items():
            # 对齐长度（理论上相同）
            n = min(len(plist), len(tlist))
            report["comparisons"][pname][tname] = {}
            for metric in metrics:
                report["comparisons"][pname][tname][metric] = compute_error_series(
                    plist[:n], tlist[:n], metric
                )

    return report


def print_report(report: Dict[str, Any]):
    """打印可读的对比报告"""
    print("\n" + "=" * 80)
    print("Feixue Monitor Ubuntu Provider 准确性对比报告")
    print("=" * 80)
    print(f"采样轮次: {report['rounds']}")
    print(f"测试 Provider: {', '.join(report['providers'])}")
    print(f"基准工具: {', '.join(report['ground_truths'])}")
    print("\n各 Provider 初始化/采集失败次数:")
    for pname, err in report["provider_init_errors"].items():
        print(f"  {pname}: {err}")

    metrics_label = {
        "gpu_util": "GPU 利用率 (%)",
        "vram_used_mb": "VRAM 已用 (MiB)",
        "vram_total_mb": "VRAM 总量 (MiB)",
        "temp_c": "温度 (°C)",
        "power_w": "功耗 (W)",
    }

    for pname, vs_truths in report["comparisons"].items():
        print(f"\n{'─' * 80}")
        print(f"Provider: {pname}")
        print("─" * 80)
        for tname, metrics_err in vs_truths.items():
            print(f"  vs 基准 [{tname}]:")
            for metric, stats in metrics_err.items():
                if stats["mean_abs_err"] is None:
                    print(f"    {metrics_label[metric]:20s}: 无有效数据 (缺失 {stats['missing']})")
                else:
                    rel = f", 平均相对误差 {stats['mean_rel_err']}%" if stats["mean_rel_err"] is not None else ""
                    print(
                        f"    {metrics_label[metric]:20s}: 平均绝对误差 {stats['mean_abs_err']:>10.3f}, "
                        f"最大绝对误差 {stats['max_abs_err']:>10.3f}{rel}, 缺失 {stats['missing']}"
                    )


def main():
    parser = argparse.ArgumentParser(description="Feixue Monitor Provider 准确性测试")
    parser.add_argument("--samples", type=int, default=30, help="采样次数")
    parser.add_argument("--interval", type=float, default=1.0, help="采样间隔（秒）")
    parser.add_argument("--load", action="store_true", help="采样期间生成 GPU 负载")
    parser.add_argument(
        "--output",
        type=str,
        default=str(PLUGIN_ROOT / "tools" / "provider_accuracy_report"),
        help="报告输出目录",
    )
    parser.add_argument("--device", type=int, default=0, help="GPU device id")
    args = parser.parse_args()

    providers = [AmdSysfsProvider, AmdSmiProvider, AmdRocmProvider]
    metrics = ["gpu_util", "vram_used_mb", "vram_total_mb", "temp_c", "power_w"]

    all_samples: List[List[Sample]] = []
    all_truths: List[List[GroundTruth]] = []

    print(f"开始对比测试：{args.samples} 轮，间隔 {args.interval}s，负载={args.load}")
    print(f"Provider: {[c.__name__ for c in providers]}")
    print(f"基准: sysfs_direct, rocm-smi")
    print("-" * 80)

    for i in range(args.samples):
        samples, truths = collect_round(
            providers, args.device, load=args.load, load_duration=args.interval * 0.8
        )
        all_samples.append(samples)
        all_truths.append(truths)

        # 实时打印一行摘要
        parts = [f"round {i + 1:02d}"]
        for s in samples:
            if s.error:
                parts.append(f"{s.provider}: ERR")
            else:
                parts.append(
                    f"{s.provider}: util={s.gpu_util}% vram={s.vram_used_mb:.0f}MB"
                )
        print(" | ".join(parts))

        if i < args.samples - 1:
            time.sleep(args.interval)

    # 写入 CSV
    output_dir = Path(args.output)
    csv_path = write_csv(output_dir, all_samples, all_truths)

    # 生成并打印报告
    report = build_report(all_samples, all_truths, metrics)
    print_report(report)

    # 保存 JSON 报告
    json_path = output_dir / "report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n原始数据: {csv_path}")
    print(f"JSON 报告: {json_path}")


if __name__ == "__main__":
    main()
