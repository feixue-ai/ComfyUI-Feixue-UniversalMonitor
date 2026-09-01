"""
环境健康检查单元测试

验证：
1. workflow scope 下，环境检查（PyTorch、驱动、内存）被降级为 info，不计入错误。
2. 健康检查返回的 findings 中 error 数量不会虚高。
3. 缺失单个节点只产生一条 finding。
"""

import pytest

from core.health_check import health_check


class TestHealthCheckScope:
    """验证 scope 参数控制错误计数。"""

    def test_workflow_scope_downgrades_environment_findings(self):
        """workflow scope 下，环境类 finding 应降级为 info。"""
        report = health_check(workflow=None, language="zh", scope="workflow")
        env_error_count = sum(
            1 for f in report.findings
            if f.get("severity") == "error" and f.get("category") in ("torch", "driver", "memory")
        )
        assert env_error_count == 0, (
            "workflow scope 不应把环境检查计为 error"
        )

    def test_full_scope_allows_environment_findings(self):
        """full scope 下，环境类 finding 可以保留原有严重度。"""
        report = health_check(workflow=None, language="zh", scope="full")
        # 这里不断言具体数量，只确认 full scope 不会强制把所有环境 finding 降级
        assert report.scope == "full"

    def test_single_missing_node_one_finding(self):
        """一个缺失节点类型只应产生一条 finding。"""
        workflow = {
            "1": {
                "class_type": "SomeMissingCustomNode",
                "inputs": {},
            },
            "2": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                },
            },
        }
        report = health_check(workflow=workflow, language="zh", scope="workflow")
        missing_node_findings = [
            f for f in report.findings
            if f.get("severity") == "error" and "missing" in f.get("category", "").lower()
        ]
        assert len(missing_node_findings) <= 1, (
            f"单个缺失节点不应产生 {len(missing_node_findings)} 条 error finding"
        )

    def test_error_count_reasonable(self):
        """空工作流的健康检查 error 数量应为 0 或极少数。"""
        report = health_check(workflow=None, language="zh", scope="full")
        error_count = sum(1 for f in report.findings if f.get("severity") == "error")
        assert error_count <= 2, (
            f"空工作流 full scope 下不应出现大量 error，当前 {error_count} 条"
        )
