"""
Pytest 全局配置：在无 ComfyUI 运行时允许测试导入插件根 __init__。

插件 __init__.py 会执行 `from server import PromptServer`，该模块只在 ComfyUI
进程内存在。本 conftest 在导入 __init__ 前注入一个最小 mock，使 API 路由
装饰器可用，同时不触发真实 ComfyUI 初始化。
"""

import sys
import types
from unittest.mock import MagicMock


def _ensure_mock_server():
    if "server" in sys.modules:
        return

    server_mod = types.ModuleType("server")
    prompt_server_cls = type(
        "PromptServer",
        (),
        {
            "instance": MagicMock(),
            "routes": MagicMock(),
        },
    )
    # routes.get/post 装饰器保持被装饰函数原样返回，便于测试
    prompt_server_cls.routes.get = lambda path: (lambda fn: fn)
    prompt_server_cls.routes.post = lambda path: (lambda fn: fn)
    prompt_server_cls.instance.routes = prompt_server_cls.routes
    server_mod.PromptServer = prompt_server_cls
    sys.modules["server"] = server_mod


_ensure_mock_server()
