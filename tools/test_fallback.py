#!/usr/bin/env python3
"""测试字段级 fallback 机制是否能正确补全主 Provider 缺失字段。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.monitor import FeixueHardwareInfo


def test_normal_collection():
    """正常采集：amdsmi 作为主 source，所有字段有效。"""
    m = FeixueHardwareInfo()
    assert m._active_source == 'amdsmi', f"expected amdsmi, got {m._active_source}"
    assert m._fallback_source == 'sysfs'
    assert m._fallback_provider is not None

    s = m.get_snapshot()
    gpu = s['gpus'][0]
    assert gpu['vram_total_mb'] > 0
    assert gpu['gpu_temperature'] > 0
    assert gpu['power_draw'] > 0
    print("[PASS] normal collection")
    return m


def test_field_fallback(m: FeixueHardwareInfo):
    """模拟主 Provider 温度/功耗为 0，验证 fallback 能补全。"""
    gpu_data = m._get_default_gpu_data(0)
    gpu_data['gpu_utilization'] = 5
    gpu_data['vram_used_mb'] = 1000
    gpu_data['vram_total_mb'] = 16000
    # 温度和功耗为 0，应触发 fallback
    gpu_data['gpu_temperature'] = 0.0
    gpu_data['power_draw'] = 0.0

    # 强制重置 fallback cache，让温度/功耗重新检测
    m._field_fallback_cache = {0: {}}
    m._supplement_fields_from_fallback(gpu_data, 0)

    assert gpu_data['gpu_temperature'] > 0, f"temperature fallback failed: {gpu_data['gpu_temperature']}"
    assert gpu_data['power_draw'] > 0, f"power fallback failed: {gpu_data['power_draw']}"
    print(f"[PASS] field fallback: temp={gpu_data['gpu_temperature']}°C, power={gpu_data['power_draw']}W")


def test_no_fallback_when_valid(m: FeixueHardwareInfo):
    """主 Provider 字段有效时，fallback 不应改变数值。"""
    gpu_data = m._get_default_gpu_data(0)
    gpu_data['gpu_utilization'] = 10
    gpu_data['vram_used_mb'] = 2000
    gpu_data['vram_total_mb'] = 16000
    gpu_data['gpu_temperature'] = 55.0
    gpu_data['power_draw'] = 30.0

    m._field_fallback_cache = {0: {}}
    m._supplement_fields_from_fallback(gpu_data, 0)

    assert gpu_data['gpu_temperature'] == 55.0
    assert gpu_data['power_draw'] == 30.0
    print("[PASS] no fallback when valid")


if __name__ == "__main__":
    m = test_normal_collection()
    test_field_fallback(m)
    test_no_fallback_when_valid(m)
    print("\nAll fallback tests passed.")
