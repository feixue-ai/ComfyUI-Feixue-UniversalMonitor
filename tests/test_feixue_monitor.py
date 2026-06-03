#!/usr/bin/env python3
"""
飞雪监测器 v3.0 功能测试脚本

测试目标：
1. 验证后端API功能完整性
2. 确保数据采集准确且稳定
3. 验证爆显存场景处理
4. 测试WebSocket通信
5. 检查接口契约合规性

测试环境：AMD RX 6800 + ROCm 7.2.1 + Ubuntu 24.04
"""
import sys
import os
import time
import json
from datetime import datetime

# 添加项目路径
sys.path.insert(0, '/home/woman/AI/ComfyUI/custom_nodes/feixue')

# 测试结果收集器
test_results = []
performance_metrics = []


def record_test(test_name: str, passed: bool, details: str = "", duration_ms: float = 0):
    """记录测试结果"""
    test_results.append({
        'name': test_name,
        'passed': passed,
        'details': details,
        'duration_ms': duration_ms,
        'timestamp': datetime.now().isoformat()
    })
    if duration_ms > 0:
        performance_metrics.append({
            'test': test_name,
            'duration_ms': duration_ms
        })


def test_backend_import():
    """Test 1: 测试模块导入"""
    print("=" * 60)
    print("Test 1: 模块导入测试")
    print("=" * 60)

    start_time = time.time()

    try:
        from core.monitor import FeixueHardwareInfo, get_snapshot
        print("  [PASS] core.monitor 导入成功")

        from core.websocket_service import FeixueMonitorService
        print("  [PASS] core.websocket_service 导入成功")

        elapsed = (time.time() - start_time) * 1000
        record_test("模块导入", True, "所有核心模块导入成功", elapsed)
        return True

    except Exception as e:
        print(f"  [FAIL] 导入失败: {e}")
        import traceback
        traceback.print_exc()

        elapsed = (time.time() - start_time) * 1000
        record_test("模块导入", False, f"导入错误: {str(e)}", elapsed)
        return False


def test_hardware_info_initialization():
    """Test 2: 测试硬件信息初始化"""
    print("\n" + "=" * 60)
    print("Test 2: FeixueHardwareInfo 初始化")
    print("=" * 60)

    start_time = time.time()

    try:
        from core.monitor import FeixueHardwareInfo

        hw = FeixueHardwareInfo()
        elapsed = (time.time() - start_time) * 1000

        print(f"  [PASS] 初始化成功 ({elapsed:.1f}ms)")

        # 从status属性获取信息
        status = hw.status
        data_source = status.get('active_source', 'unknown')
        device_names = status.get('device_names', ['Unknown'])
        device_name = device_names[0] if device_names else 'Unknown'

        print(f"         数据源: {data_source}")
        print(f"         GPU设备: {device_name}")

        # 验证状态信息
        print(f"         设备数量: {status['device_count']}")
        print(f"         是否可用: {status['initialized']}")

        hw.shutdown()
        record_test("硬件初始化", True,
                   f"源={data_source}, 设备={status['device_count']}",
                   elapsed)
        return True

    except Exception as e:
        print(f"  [FAIL] 初始化失败: {e}")
        import traceback
        traceback.print_exc()

        elapsed = (time.time() - start_time) * 1000
        record_test("硬件初始化", False, f"错误: {str(e)}", elapsed)
        return False


def test_get_snapshot():
    """Test 3: 测试数据快照获取（连续10次）"""
    print("\n" + "=" * 60)
    print("Test 3: get_snapshot() 功能测试 (10次连续采集)")
    print("=" * 60)

    start_time = time.time()
    success_count = 0
    total_time = 0
    sample_data = None

    try:
        from core.monitor import get_snapshot

        for i in range(10):
            iter_start = time.time()
            snapshot = get_snapshot()
            iter_elapsed = (time.time() - iter_start) * 1000
            total_time += iter_elapsed

            # 验证快照不为空
            assert snapshot is not None, f"第{i+1}次: 快照为None"

            # 验证必需字段存在
            required_fields = ['cpu_utilization', 'ram', 'gpus', 'timestamp']
            for field in required_fields:
                assert field in snapshot, f"第{i+1}次: 缺少{field}"

            # 验证GPU数据存在
            assert 'gpus' in snapshot and len(snapshot['gpus']) > 0, \
                f"第{i+1}次: 缺少GPU数据"

            # 提取关键指标
            cpu = snapshot['cpu_utilization']
            ram_percent = snapshot['ram']['percent']
            gpu_util = snapshot['gpus'][0]['gpu_utilization']

            # 保存最后一次样本数据
            if i == 9:
                sample_data = snapshot.copy()

            status_symbol = "✓" if (iter_elapsed < 2000) else "⚠"
            print(f"  [{i+1:2d}/10] {status_symbol} CPU:{cpu:3d}% "
                  f"RAM:{ram_percent:3d}% GPU:{gpu_util:3d}% "
                  f"({iter_elapsed:6.1f}ms)")

            success_count += 1
            time.sleep(0.5)  # 等待500ms

        avg_time = total_time / 10
        elapsed = (time.time() - start_time) * 1000

        print(f"\n  [PASS] {success_count}/10 次快照获取成功")
        print(f"         平均响应时间: {avg_time:.1f}ms")
        print(f"         总耗时: {elapsed/1000:.2f}s")

        record_test("数据快照获取", True,
                   f"{success_count}/10成功, 平均{avg_time:.1f}ms",
                   elapsed)

        # 如果有样本数据，保存到文件供后续分析
        if sample_data:
            with open('/tmp/feixue_sample_snapshot.json', 'w') as f:
                json.dump(sample_data, f, indent=2, default=str)
            print(f"         样本数据已保存至 /tmp/feixue_sample_snapshot.json")

        return True

    except Exception as e:
        print(f"\n  [FAIL] 快照获取失败: {e}")
        import traceback
        traceback.print_exc()

        elapsed = (time.time() - start_time) * 1000
        record_test("数据快照获取", False,
                   f"{success_count}/10成功, 错误: {str(e)}",
                   elapsed)
        return False


def test_vram_overflow_scenario():
    """Test 4: 测试爆显存场景"""
    print("\n" + "=" * 60)
    print("Test 4: 爆显存场景模拟（边界条件测试）")
    print("=" * 60)

    start_time = time.time()

    try:
        from core.monitor import FeixueHardwareInfo

        hw = FeixueHardwareInfo()

        # 模拟各种VRAM边界情况
        test_cases = [
            (16000, 16384, 97, "正常高占用"),
            (16384, 16384, 100, "刚好满载"),
            (17000, 16384, 100, "超过总量（爆显存）"),
            (18000, 16384, 100, "严重超载"),
            (0, 16384, 0, "无使用"),
            (8192, 16384, 50, "半满"),
            (-100, 16384, 0, "负值使用量"),
            (100, 0, 0, "零总量（防除零）"),
            (20000, 16000, 100, "大幅超出"),
        ]

        all_passed = True
        results = []

        for used, total, expected_percent, description in test_cases:
            percent = hw._calculate_vram_percent(used, total)
            passed = (percent == expected_percent)
            status = "[PASS]" if passed else "[FAIL]"

            if not passed:
                all_passed = False

            results.append({
                'used': used,
                'total': total,
                'actual': percent,
                'expected': expected_percent,
                'description': description,
                'passed': passed
            })

            print(f"  {status} {description:20s}: "
                  f"VRAM {used:>6d}/{total:>6d}MB -> "
                  f"{percent:3d}% (预期 {expected_percent:3d}%)")

        hw.shutdown()
        elapsed = (time.time() - start_time) * 1000

        if all_passed:
            print(f"\n  [PASS] 所有 {len(test_cases)} 个爆显存边界条件处理正确")
            record_test("爆显存场景", True,
                       f"{len(test_cases)}/{len(test_cases)} 边界条件通过",
                       elapsed)
        else:
            failed_count = sum(1 for r in results if not r['passed'])
            print(f"\n  [FAIL] 有 {failed_count} 个边界条件处理错误")
            record_test("爆显存场景", False,
                       f"{len(test_cases)-failed_count}/{len(test_cases)} 通过",
                       elapsed)

        return all_passed

    except Exception as e:
        print(f"\n  [FAIL] 爆显存测试失败: {e}")
        import traceback
        traceback.print_exc()

        elapsed = (time.time() - start_time) * 1000
        record_test("爆显存场景", False, f"异常: {str(e)}", elapsed)
        return False


def test_data_format_compliance():
    """Test 5: 测试接口契约合规性"""
    print("\n" + "=" * 60)
    print("Test 5: 接口契约格式验证")
    print("=" * 60)

    start_time = time.time()

    try:
        from core.monitor import get_snapshot

        snapshot = get_snapshot()

        # 定义必需字段和类型
        required_fields = {
            'timestamp': float,
            'cpu_utilization': int,
            'ram': dict,
            'gpus': list
        }

        all_valid = True
        validation_results = []

        # 验证顶层字段
        print("\n  === 顶层字段验证 ===")
        for field, field_type in required_fields.items():
            exists = field in snapshot
            correct_type = isinstance(snapshot.get(field), field_type) if exists else False

            status = "[PASS]" if (exists and correct_type) else "[FAIL]"
            type_str = snapshot.get(field).__class__.__name__ if exists else "N/A"

            validation_results.append({
                'field': field,
                'exists': exists,
                'correct_type': correct_type,
                'passed': exists and correct_type
            })

            print(f"  {status} '{field}': {'存在' if exists else '缺失'} | "
                  f"类型: {type_str} (预期: {field_type.__name__})")

            if not (exists and correct_type):
                all_valid = False

        # 验证RAM子字段
        print("\n  === RAM子字段验证 ===")
        if 'ram' in snapshot:
            ram_fields = {
                'total_gb': (int, float),
                'used_gb': (int, float),
                'percent': int
            }
            for rf, expected_types in ram_fields.items():
                exists = rf in snapshot['ram']
                correct_type = isinstance(snapshot['ram'].get(rf), expected_types) if exists else False

                status = "[PASS]" if (exists and correct_type) else "[FAIL]"
                validation_results.append({
                    'field': f'ram.{rf}',
                    'exists': exists,
                    'correct_type': correct_type,
                    'passed': exists and correct_type
                })

                print(f"  {status} ram.{rf}: {'存在' if exists else '缺失'}")

                if not (exists and correct_type):
                    all_valid = False

        # 验证GPU子字段
        print("\n  === GPU子字段验证 ===")
        if 'gpus' in snapshot and len(snapshot['gpus']) > 0:
            gpu = snapshot['gpus'][0]
            gpu_fields = [
                'gpu_utilization',
                'vram_used_mb',
                'vram_total_mb',
                'vram_percent',
                'gpu_temperature',
                'power_draw'
            ]

            for gf in gpu_fields:
                exists = gf in gpu
                status = "[PASS]" if exists else "[FAIL]"
                value = gpu.get(gf, "N/A")

                validation_results.append({
                    'field': f'gpus[0].{gf}',
                    'exists': exists,
                    'value': value,
                    'passed': exists
                })

                print(f"  {status} gpus[0].{gf}: "
                      f"{'存在' if exists else '缺失'} "
                      f"(值: {value})")

                if not exists:
                    all_valid = False

        elapsed = (time.time() - start_time) * 1000

        if all_valid:
            print(f"\n  [PASS] 接口契约完全符合要求")
            record_test("接口契约验证", True,
                       "所有字段类型和结构符合规范",
                       elapsed)
        else:
            failed_count = sum(1 for v in validation_results if not v['passed'])
            print(f"\n  [FAIL] 接口契约不符合要求 ({failed_count}项不通过)")
            record_test("接口契约验证", False,
                       f"{failed_count}项不符合规范",
                       elapsed)

        return all_valid

    except Exception as e:
        print(f"\n  [FAIL] 格式验证失败: {e}")
        import traceback
        traceback.print_exc()

        elapsed = (time.time() - start_time) * 1000
        record_test("接口契约验证", False, f"异常: {str(e)}", elapsed)
        return False


def test_websocket_service():
    """Test 6: 测试WebSocket服务"""
    print("\n" + "=" * 60)
    print("Test 6: WebSocket服务测试")
    print("=" * 60)

    start_time = time.time()

    try:
        from core.websocket_service import FeixueMonitorService

        service = FeixueMonitorService(rate=1.0)

        print(f"  [PASS] 服务创建成功")
        print(f"         默认刷新率: {service.rate}s")
        print(f"         运行状态: {'运行中' if service._running else '已停止'}")

        # 测试设置刷新率
        test_rates = [
            (0.5, "高频模式 (2Hz)", lambda r: r == 0.5),
            (2.0, "低频模式 (0.5Hz)", lambda r: r == 2.0),
            (0.1, "超低延迟请求", lambda r: r >= 0.25),  # 应被钳位到最小值
            (20.0, "超高延迟请求", lambda r: r <= 10.0),  # 应被钳位到最大值
        ]

        rate_tests_passed = 0
        for rate_value, description, validator in test_rates:
            old_rate = service.rate
            service.set_rate(rate_value)
            actual_rate = service.rate
            passed = validator(actual_rate)

            status = "[PASS]" if passed else "[FAIL]"
            rate_tests_passed += 1 if passed else 0

            print(f"  {status} {description}: "
                  f"请求 {rate_value}s -> 实际 {actual_rate}s")

            if not passed:
                print(f"         预期: >=0.25 或 <=10.0，实际: {actual_rate}")

        # 验证统计信息属性
        stats = service.stats
        has_stats = isinstance(stats, dict)
        print(f"\n  {'[PASS]' if has_stats else '[FAIL]'} 统计信息可访问: {has_stats}")

        # 验证is_running属性
        is_running_correct = service.is_running == service._running
        print(f"  {'[PASS]' if is_running_correct else '[FAIL]'} is_running 属性一致")

        elapsed = (time.time() - start_time) * 1000

        all_passed = (rate_tests_passed == len(test_rates)) and has_stats and is_running_correct

        if all_passed:
            print(f"\n  [PASS] WebSocket服务功能正常")
            record_test("WebSocket服务", True,
                       f"{rate_tests_passed}/{len(test_rates)} 刷新率测试通过",
                       elapsed)
        else:
            print(f"\n  [FAIL] WebSocket服务存在问题")
            record_test("WebSocket服务", False,
                       f"部分功能未通过验证",
                       elapsed)

        return all_passed

    except Exception as e:
        print(f"\n  [FAIL] WebSocket服务测试失败: {e}")
        import traceback
        traceback.print_exc()

        elapsed = (time.time() - start_time) * 1000
        record_test("WebSocket服务", False, f"异常: {str(e)}", elapsed)
        return False


def test_performance_benchmark():
    """Test 7: 性能基准测试"""
    print("\n" + "=" * 60)
    print("Test 7: 性能基准测试（100次快速采集）")
    print("=" * 60)

    start_time = time.time()

    try:
        from core.monitor import get_snapshot

        iterations = 100
        times = []
        errors = 0

        print(f"\n  执行 {iterations} 次快速采集...")

        for i in range(iterations):
            iter_start = time.time()
            try:
                snapshot = get_snapshot()
                elapsed = (time.time() - iter_start) * 1000
                times.append(elapsed)

                if i % 25 == 0:
                    print(f"  进度: {i+1:3d}/{iterations}...")

            except Exception as e:
                errors += 1
                times.append(-1)  # 标记错误

        total_elapsed = (time.time() - start_time) * 1000

        # 计算统计数据
        valid_times = [t for t in times if t > 0]
        if valid_times:
            avg_time = sum(valid_times) / len(valid_times)
            min_time = min(valid_times)
            max_time = max(valid_times)

            # 计算百分位数
            sorted_times = sorted(valid_times)
            p50_idx = int(len(sorted_times) * 0.50)
            p90_idx = int(len(sorted_times) * 0.90)
            p95_idx = int(len(sorted_times) * 0.95)
            p99_idx = int(len(sorted_times) * 0.99)

            p50 = sorted_times[p50_idx]
            p90 = sorted_times[p90_idx]
            p95 = sorted_times[p95_idx]
            p99 = sorted_times[p99_idx]

            success_rate = (len(valid_times) / iterations) * 100

            print(f"\n  === 性能统计 ===")
            print(f"  成功率:     {success_rate:.1f}% ({len(valid_times)}/{iterations})")
            print(f"  错误数:     {errors}")
            print(f"  平均耗时:   {avg_time:.2f}ms")
            print(f"  最小耗时:   {min_time:.2f}ms")
            print(f"  最大耗时:   {max_time:.2f}ms")
            print(f"  P50 (中位): {p50:.2f}ms")
            print(f"  P90:        {p90:.2f}ms")
            print(f"  P95:        {p95:.2f}ms")
            print(f"  P99:        {p99:.2f}ms")
            print(f"  总耗时:     {total_elapsed/1000:.2f}s")

            # 性能评估
            performance_ok = (p95 < 500) and (success_rate > 99)  # P95<500ms, 成功率>99%
            status = "[PASS]" if performance_ok else "[WARN]"

            print(f"\n  {status} 性能评估:")
            print(f"         P95 < 500ms: {'通过' if p95 < 500 else '未通过'} ({p95:.2f}ms)")
            print(f"         成功率 > 99%: {'通过' if success_rate > 99 else '未通过'} ({success_rate:.1f}%)")

            record_test("性能基准测试", True if performance_ok else False,
                       f"P95={p95:.1f}ms, 成功率={success_rate:.1f}%, 平均={avg_time:.1f}ms",
                       total_elapsed)

            # 保存详细性能数据
            perf_data = {
                'iterations': iterations,
                'success_count': len(valid_times),
                'error_count': errors,
                'success_rate': success_rate,
                'avg_ms': round(avg_time, 2),
                'min_ms': round(min_time, 2),
                'max_ms': round(max_time, 2),
                'p50_ms': round(p50, 2),
                'p90_ms': round(p90, 2),
                'p95_ms': round(p95, 2),
                'p99_ms': round(p99, 2),
                'total_seconds': round(total_elapsed / 1000, 2),
                'timestamp': datetime.now().isoformat()
            }

            with open('/tmp/feixue_performance_data.json', 'w') as f:
                json.dump(perf_data, f, indent=2)
            print(f"\n  详细性能数据已保存至 /tmp/feixue_performance_data.json")

            return performance_ok

        else:
            print(f"\n  [FAIL] 所有采集都失败了")
            record_test("性能基准测试", False, "所有采集均失败", total_elapsed)
            return False

    except Exception as e:
        print(f"\n  [FAIL] 性能测试失败: {e}")
        import traceback
        traceback.print_exc()

        elapsed = (time.time() - start_time) * 1000
        record_test("性能基准测试", False, f"异常: {str(e)}", elapsed)
        return False


def main():
    """主测试函数"""
    print("\n" + "=" * 70)
    print("  飞雪监测器 v3.0 全面功能测试套件")
    print("  环境: AMD RX 6800 + ROCm 7.2.1 + Ubuntu 24.04")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")

    # 执行所有测试
    tests = [
        ("模块导入", test_backend_import),
        ("硬件初始化", test_hardware_info_initialization),
        ("数据快照", test_get_snapshot),
        ("爆显存场景", test_vram_overflow_scenario),
        ("接口契约", test_data_format_compliance),
        ("WebSocket服务", test_websocket_service),
        ("性能基准", test_performance_benchmark),
    ]

    results = {}
    for test_name, test_func in tests:
        result = test_func()
        results[test_name] = result
        print()  # 测试间空行

    # 输出总结报告
    print("\n" + "=" * 70)
    print("  📊 测试结果汇总报告")
    print("=" * 70)

    total_tests = len(results)
    passed_tests = sum(results.values())
    pass_rate = (passed_tests / total_tests) * 100

    print(f"\n  总体结果: {passed_tests}/{total_tests} 通过 ({pass_rate:.1f}%)\n")

    print("  详细结果:")
    print("  " + "-" * 50)
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        symbol = "✓" if result else "✗"
        print(f"  {symbol} [{status:8s}] {test_name}")

        # 找到对应的详细信息
        matching = [r for r in test_results if r['name'] == test_name]
        if matching:
            detail = matching[0]
            print(f"      详情: {detail['details']}")
            if detail['duration_ms'] > 0:
                print(f"      耗时: {detail['duration_ms']:.1f}ms")

    print("\n  " + "-" * 50)

    # 性能指标摘要
    if performance_metrics:
        print("\n  ⚡ 性能指标摘要:")
        for metric in performance_metrics[:5]:  # 显示前5个
            print(f"    - {metric['test']}: {metric['duration_ms']:.1f}ms")

    # 最终结论
    print("\n" + "=" * 70)
    if passed_tests == total_tests:
        print("  ✅ 结论: 所有测试通过！飞雪监测器v3.0可以投入使用！")
        print("=" * 70)
        exit_code = 0
    elif pass_rate >= 80:
        print(f"  ⚠️  结论: 基本通过 ({pass_rate:.0f}%)，建议修复少量问题后上线")
        print("=" * 70)
        exit_code = 1
    else:
        print(f"  ❌ 结论: 未通过测试 ({pass_rate:.0f}%)，需要全面排查问题")
        print("=" * 70)
        exit_code = 2

    # 生成完整测试报告JSON
    report = {
        'summary': {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'failures': total_tests - passed_tests,
            'pass_rate': pass_rate,
            'exit_code': exit_code,
            'timestamp': datetime.now().isoformat(),
            'environment': {
                'gpu': 'AMD RX 6800',
                'driver': 'ROCm 7.2.1',
                'os': 'Ubuntu 24.04'
            }
        },
        'results': test_results,
        'performance_metrics': performance_metrics,
        'verdict': (
            'PASS - 可以投入生产环境' if exit_code == 0
            else 'WARNING - 建议修复后上线' if exit_code == 1
            else 'FAIL - 需要全面排查'
        )
    }

    report_path = '/tmp/feixue_test_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n  📄 完整测试报告已保存至: {report_path}")
    print(f"  📄 样本数据已保存至: /tmp/feixue_sample_snapshot.json")
    print(f"  📄 性能数据已保存至: /tmp/feixue_performance_data.json\n")

    return exit_code


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
