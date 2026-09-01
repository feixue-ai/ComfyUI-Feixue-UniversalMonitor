#!/usr/bin/env python3
"""
实时对比 GNOME Vitals 数据源、飞雪监测器 (amdsmi) 和 rocm-smi 基准。

Vitals (AMD GPU) 读取：
  /sys/class/drm/card{i}/device/gpu_busy_percent
  /sys/class/drm/card{i}/device/mem_info_vram_used
  /sys/class/drm/card{i}/device/mem_info_vram_total
  /sys/class/hwmon/hwmon*/temp*_input

飞雪监测器 (v3.40.7) 读取：
  libamd_smi.so (ctypes) 为主，sysfs 字段级 fallback
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from core.monitor import FeixueHardwareInfo


def read_sysfs(path: str) -> int:
    try:
        return int(Path(path).read_text().strip())
    except Exception:
        return -1


def read_hwmon_temps() -> dict:
    """读取 amdgpu hwmon 所有温度传感器"""
    temps = {}
    for f in sorted(Path("/sys/class/hwmon").glob("hwmon*/name")):
        try:
            name = f.read_text().strip()
            if "amdgpu" not in name:
                continue
            hwmon_dir = f.parent
            for temp_file in sorted(hwmon_dir.glob("temp*_input")):
                sensor = temp_file.name.split("_")[0]  # temp1, temp2, temp3
                try:
                    val = int(temp_file.read_text().strip())
                    temps[sensor] = val / 1000.0
                except Exception:
                    pass
        except Exception:
            pass
    return temps


def get_rocm_smi() -> dict:
    try:
        out = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--showuse", "--showtemp", "--showpower", "--csv"],
            capture_output=True, text=True, timeout=5,
        )
        lines = out.stdout.strip().splitlines()
        if len(lines) < 2:
            return {}
        headers = [h.strip() for h in lines[0].split(",")]
        values = [v.strip() for v in lines[1].split(",")]
        data = dict(zip(headers, values))
        return {
            "gpu_util": float(data.get("GPU use (%)", 0) or 0),
            "vram_used_mb": float(data.get("VRAM Total Used Memory (B)", 0) or 0) / (1024 * 1024),
            "vram_total_mb": float(data.get("VRAM Total Memory (B)", 0) or 0) / (1024 * 1024),
            "temp_c": float(data.get("Temperature (Sensor junction) (C)", 0) or 0),
            "power_w": float(data.get("Average Graphics Package Power (W)", 0) or 0),
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    device = 1  # 当前系统 GPU 是 card1
    card_path = f"/sys/class/drm/card{device}/device"
    monitor = FeixueHardwareInfo()

    print("=" * 100)
    print("Vitals vs 飞雪监测器 实时对比（按 Ctrl+C 停止）")
    print("=" * 100)
    print(f"{'时间':>8} | {'来源':>12} | {'GPU%':>6} | {'VRAM已用(MB)':>14} | {'VRAM总量(MB)':>14} | {'温度°C':>10} | {'功耗W':>8}")
    print("-" * 100)

    try:
        while True:
            ts = time.strftime("%H:%M:%S")

            # Vitals 数据源 (sysfs)
            vitals_gpu_util = read_sysfs(f"{card_path}/gpu_busy_percent")
            vitals_vram_used = read_sysfs(f"{card_path}/mem_info_vram_used")
            vitals_vram_total = read_sysfs(f"{card_path}/mem_info_vram_total")
            vitals_temps = read_hwmon_temps()

            # 飞雪监测器
            fx_snapshot = monitor.get_snapshot()
            fx_gpu = fx_snapshot.get("gpus", [{}])[0]

            # rocm-smi 基准
            rocm = get_rocm_smi()

            print(
                f"{ts} | {'Vitals sysfs':>12} | {vitals_gpu_util:>6} | "
                f"{vitals_vram_used / (1024 * 1024):>14.1f} | {vitals_vram_total / (1024 * 1024):>14.1f} | "
                f"{vitals_temps.get('temp2', -1):>6.1f}/{vitals_temps.get('temp1', -1):<3.0f} | {'N/A':>8}"
            )
            print(
                f"{ts} | {'Feixue amdsmi':>12} | {fx_gpu.get('gpu_utilization', -1):>6} | "
                f"{fx_gpu.get('vram_used_mb', -1):>14.1f} | {fx_gpu.get('vram_total_mb', -1):>14.1f} | "
                f"{fx_gpu.get('gpu_temperature', -1):>10.1f} | {fx_gpu.get('power_draw', -1):>8.1f}"
            )
            if "error" not in rocm:
                print(
                    f"{ts} | {'rocm-smi':>12} | {rocm.get('gpu_util', -1):>6.1f} | "
                    f"{rocm.get('vram_used_mb', -1):>14.1f} | {rocm.get('vram_total_mb', -1):>14.1f} | "
                    f"{rocm.get('temp_c', -1):>10.1f} | {rocm.get('power_w', -1):>8.1f}"
                )
            else:
                print(f"{ts} | {'rocm-smi':>12} | {rocm['error']}")
            print("-" * 100)

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n停止对比。")


if __name__ == "__main__":
    main()
