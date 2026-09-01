"""
DIAG 诊断引擎单元测试

验证：
1. 常见 ComfyUI 报错能命中正确分类，不再误报为 workflow_validation / connection。
2. 诊断报告的建议数量严格 <= 3 条。
3. 未知错误不罗列多种猜测。
"""

import pytest

from core.diagnoser import DiagEngine


@pytest.fixture
def engine():
    return DiagEngine(language="zh")


class TestErrorClassification:
    """验证常见报错被正确分类。"""

    def test_cuda_oom(self, engine):
        report = engine.diagnose_text(
            "RuntimeError: CUDA out of memory. Tried to allocate 3.50 GiB. "
            "GPU 0 has a total capacity of 15.99 GiB."
        )
        assert report.matched is True
        assert report.category == "oom"
        assert "CUDA" in report.title or "显存" in report.title

    def test_cuda_oom_in_traceback(self, engine):
        """exception_message 是通用 Prompt execution failed，真正 OOM 在 traceback 中。"""
        report = engine.diagnose({
            "exception_message": "Prompt execution failed",
            "exception_type": "RuntimeError",
            "traceback": [
                "File ...",
                "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB",
            ],
        })
        assert report.category == "oom"

    def test_model_not_found(self, engine):
        report = engine.diagnose_text(
            "Cannot find model models/checkpoints/sd_xl_base_1.0.safetensors"
        )
        assert report.matched is True
        assert report.category == "model_missing"

    def test_node_not_found(self, engine):
        report = engine.diagnose_text(
            "When loading the graph, the following node types were not found: "
            "LayerMask:LoadSegmentAnythingModels"
        )
        assert report.matched is True
        assert report.category == "node_not_found"

    def test_import_error(self, engine):
        report = engine.diagnose_text(
            "ModuleNotFoundError: No module named 'opencv_python_headless'"
        )
        assert report.matched is True
        assert report.category == "import_error"

    def test_prompt_validation_failed(self, engine):
        report = engine.diagnose_text(
            "Prompt outputs failed validation: Value not in list: ckpt_name: 'abc.safetensors' not in []"
        )
        assert report.matched is True
        assert report.category == "workflow_validation"

    def test_frontend_connection_interrupted_not_matched_by_backend(self, engine):
        """普通后端执行错误不应被误诊为前端连接中断。"""
        report = engine.diagnose_text(
            "Connection refused while downloading model from https://example.com/model.safetensors"
        )
        assert report.category != "workflow_validation"

    def test_input_slot_not_connected_not_matched_by_random_text(self, engine):
        """随机文本中的 'input' 不应触发 input_slot_not_connected。"""
        report = engine.diagnose_text(
            "Invalid input shape for tensor operation: expected [B, C, H, W]"
        )
        assert report.category != "workflow_validation"

    def test_required_widget_empty_load_image(self, engine):
        """Load Image 未选择图片应识别为必填参数为空。"""
        report = engine.diagnose_text("[加载图片] 必填参数未填写：image")
        assert report.matched is True
        assert report.category == "workflow_validation"
        assert "必填参数为空" in report.title

    def test_required_widget_empty_from_comfyui_text(self, engine):
        """ComfyUI 中文提示"部分要点 必需输入"应命中必填参数为空。"""
        report = engine.diagnose_text("部分要点 必需输入")
        assert report.matched is True
        assert report.category == "workflow_validation"
        assert "必填参数为空" in report.title

    def test_input_slot_not_connected_chinese(self, engine):
        """缺少输入 应识别为输入插槽未连接。"""
        report = engine.diagnose_text("[加载图片] 输入插槽未连接：图片")
        assert report.matched is True
        assert report.category == "workflow_validation"
        assert "输入插槽未连接" in report.title

    def test_required_input_missing_from_prompt(self, engine):
        """ComfyUI /prompt 校验错误 required_input_missing 应被正确识别。"""
        report = engine.diagnose_text("[LoadImage:5] required_input_missing: image")
        assert report.matched is True
        assert report.category == "workflow_validation"
        assert "必填输入缺失" in report.title

    def test_value_not_in_list_from_prompt(self, engine):
        """ComfyUI /prompt 校验错误 value_not_in_list 应被正确识别。"""
        report = engine.diagnose_text("[CheckpointLoaderSimple:1] value_not_in_list: ckpt_name 'abc.safetensors' not in []")
        assert report.matched is True
        assert report.category == "workflow_validation"
        assert "选项值不在列表中" in report.title

    def test_invalid_input_type_from_prompt(self, engine):
        """ComfyUI /prompt 校验错误 invalid_input_type 应被正确识别。"""
        report = engine.diagnose_text("[KSampler:3] invalid_input_type: seed INT")
        assert report.matched is True
        assert report.category == "workflow_validation"
        assert "输入值类型转换失败" in report.title


class TestSuggestionLimit:
    """验证每个错误只保留一条最优先建议。"""

    def test_suggestions_exactly_one(self, engine):
        for sample in [
            "CUDA out of memory",
            "Cannot find model models/checkpoints/abc.safetensors",
            "ModuleNotFoundError: No module named 'numpy'",
            "When loading the graph, the following node types were not found: FooNode",
        ]:
            report = engine.diagnose_text(sample)
            assert len(report.suggestions) == 1, (
                f"{sample!r} produced {len(report.suggestions)} suggestions"
            )

    def test_unknown_error_single_hint(self, engine):
        report = engine.diagnose_text(
            "Some completely unrecognized gibberish error message 12345"
        )
        assert report.matched is False
        assert report.category == "unknown"
        assert len(report.suggestions) == 1


class TestNodeInfoPreservation:
    """验证节点信息不被错误分类丢弃。"""

    def test_missing_node_type_extracted(self, engine):
        report = engine.diagnose({
            "exception_message": "Node class 'FooBar:BizBaz' not found",
            "exception_type": "RuntimeError",
        })
        assert report.category == "node_not_found"
        node_info = report.node_info
        assert node_info.get("missing_node_type") == "FooBar:BizBaz"

    def test_missing_model_path_extracted(self, engine):
        report = engine.diagnose({
            "exception_message": "Cannot find model models/loras/my_lora.safetensors",
            "exception_type": "RuntimeError",
        })
        assert report.category == "model_missing"
        node_info = report.node_info
        assert "my_lora.safetensors" in node_info.get("missing_model_path", "")
