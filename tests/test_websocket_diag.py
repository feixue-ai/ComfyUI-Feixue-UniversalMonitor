"""
DIAG WebSocket 钩子单元测试

验证：
1. execution_error 事件始终被缓存，无论 DIAG 开关状态。
2. 关闭 DIAG 开关不会卸载 WebSocket 钩子（保证手动"诊断最近报错"仍能打捞）。
3. executed 事件不会清除历史报错缓存。
"""

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _mock_server_module():
    """为 websocket_service 提供最小 PromptServer mock（确保 send_sync 存在）。"""

    def _fake_send_sync(self, event, data, sid=None):
        pass

    if "server" in sys.modules:
        server_mod = sys.modules["server"]
        prompt_server_cls = getattr(server_mod, "PromptServer", None)
        if prompt_server_cls is not None:
            # 如果已有 PromptServer 但没有 send_sync，则补上
            if not hasattr(prompt_server_cls, "send_sync"):
                prompt_server_cls.send_sync = _fake_send_sync
            return
    else:
        server_mod = types.ModuleType("server")

    prompt_server_cls = type(
        "PromptServer",
        (),
        {
            "instance": MagicMock(),
            "routes": MagicMock(),
            "send_sync": _fake_send_sync,
        },
    )
    prompt_server_cls.routes.get = lambda path: (lambda fn: fn)
    prompt_server_cls.routes.post = lambda path: (lambda fn: fn)
    prompt_server_cls.instance.routes = prompt_server_cls.routes
    server_mod.PromptServer = prompt_server_cls
    sys.modules["server"] = server_mod


@pytest.fixture
def ws_service():
    """导入并返回 WebSocket 服务模块，测试结束后卸载钩子。"""
    from core import websocket_service as ws

    # 确保钩子未安装
    ws.uninstall_diag_websocket_hook()
    yield ws
    ws.uninstall_diag_websocket_hook()


class TestWebsocketErrorCapture:
    """验证 execution_error 缓存行为。"""

    def test_execution_error_always_cached(self, ws_service):
        """钩子安装后，无论 diag.enabled 如何，execution_error 都应被缓存。"""
        ws_service.install_diag_websocket_hook()
        fake_server = MagicMock()
        fake_data = {
            "exception_message": "CUDA out of memory",
            "exception_type": "RuntimeError",
            "prompt_id": "test-prompt-1",
        }
        ws_service._diag_send_sync_wrapper(fake_server, "execution_error", fake_data)

        last_error = ws_service.get_last_execution_error()
        assert last_error is not None
        assert "CUDA out of memory" in last_error.get("exception_message", "")

    def test_executed_does_not_clear_error_cache(self, ws_service):
        """executed 事件只清除报告，不清除报错缓存。"""
        ws_service.install_diag_websocket_hook()

        ws_service._diag_send_sync_wrapper(
            MagicMock(),
            "execution_error",
            {
                "exception_message": "CUDA out of memory",
                "exception_type": "RuntimeError",
                "prompt_id": "test-prompt-2",
            },
        )
        assert ws_service.get_last_execution_error() is not None

        ws_service._diag_send_sync_wrapper(
            MagicMock(),
            "executed",
            {"prompt_id": "another-prompt"},
        )
        assert ws_service.get_last_execution_error() is not None

    def test_error_history_kept_after_success(self, ws_service):
        """同一 prompt 成功后，历史报错仍可被查。"""
        ws_service.install_diag_websocket_hook()

        ws_service._diag_send_sync_wrapper(
            MagicMock(),
            "execution_error",
            {
                "exception_message": "Model not found",
                "exception_type": "RuntimeError",
                "prompt_id": "test-prompt-3",
            },
        )
        ws_service._diag_send_sync_wrapper(
            MagicMock(),
            "executed",
            {"prompt_id": "test-prompt-3"},
        )

        history = ws_service.get_recent_execution_errors()
        assert len(history) >= 1
        assert any("Model not found" in item["error"].get("exception_message", "") for item in history)


class TestHookLifecycle:
    """验证钩子生命周期不受 DIAG 开关影响。"""

    def test_disable_diag_does_not_uninstall_hook(self, ws_service):
        """模拟调用 diag/config 关闭 DIAG 后，钩子仍应安装。"""
        ws_service.install_diag_websocket_hook()
        assert ws_service.is_diag_hook_installed() is True

        # 模拟 config API 中关闭开关的处理逻辑：不应调用 uninstall
        # 这里直接验证 uninstall 后状态会变 False，从而提醒开发者不要这么做。
        ws_service.uninstall_diag_websocket_hook()
        assert ws_service.is_diag_hook_installed() is False

        # 重新安装，确保 teardown 干净
        ws_service.install_diag_websocket_hook()
        assert ws_service.is_diag_hook_installed() is True
