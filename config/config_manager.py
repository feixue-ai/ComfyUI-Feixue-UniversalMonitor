import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULTS = {
    "refresh_interval": 1.0,
    "ui": {
        "theme": "neu",
        "position": {"x": 20, "y": 20},
        "show_on_startup": True,
    },
    "data_sources": {
        "linux_amd_priority": ["amdsmi", "rocm_smi_lib", "sysfs"],
        "windows_amd_priority": ["adlx"],
    },
}

TYPE_SCHEMA = {
    "refresh_interval": (float, int),
    "ui.theme": str,
    "ui.position.x": (int, float),
    "ui.position.y": (int, float),
    "ui.show_on_startup": bool,
    "data_sources.linux_amd_priority": list,
    "data_sources.windows_amd_priority": list,
}


class ConfigManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, config_path: str | Path | None = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_path: str | Path | None = None):
        if self._initialized:
            return
        self._initialized = True
        self._config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._data: dict[str, Any] = {}
        self._watchers: list[Callable[[], None]] = []
        self._watch_thread: threading.Thread | None = None
        self._watch_running = False
        self._last_mtime: float = 0
        self._load()

    def _load(self) -> None:
        raw = DEFAULTS.copy()
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                raw = self._deep_merge(raw, user_cfg)
            except (json.JSONDecodeError, OSError):
                pass
        self._data = raw
        self._last_mtime = self._config_path.stat().st_mtime if self._config_path.exists() else 0

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        result = base.copy()
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigManager._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key: str, value: Any) -> None:
        keys = key.split(".")
        target = self._data
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

    def _validate_type(self, key: str, value: Any) -> bool:
        expected = TYPE_SCHEMA.get(key)
        if expected is None:
            return True
        if isinstance(expected, tuple):
            return isinstance(value, expected)
        return isinstance(value, expected)

    def start_watching(self, interval: float = 2.0) -> None:
        if self._watch_running:
            return
        self._watch_running = True
        self._watch_thread = threading.Thread(target=self._watch_loop, args=(interval,), daemon=True)
        self._watch_thread.start()

    def _watch_loop(self, interval: float) -> None:
        while self._watch_running:
            time.sleep(interval)
            try:
                if not self._config_path.exists():
                    continue
                mtime = self._config_path.stat().st_mtime
                if mtime > self._last_mtime:
                    self._load()
                    for cb in self._watchers:
                        try:
                            cb()
                        except Exception:
                            pass
            except Exception:
                pass

    def stop_watching(self) -> None:
        self._watch_running = False
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=3)

    def add_watcher(self, callback: Callable[[], None]) -> None:
        self._watchers.append(callback)

    def reload(self) -> None:
        self._load()

    @property
    def data(self) -> dict[str, Any]:
        return self._data.copy()

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path else self._config_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def init(self, **kwargs) -> 'ConfigManager':
        """初始化配置管理器（兼容 monitor.py 的调用接口）。"""
        self._load()
        return self


def get_config_manager(config_path: str | Path | None = None) -> ConfigManager:
    """获取 ConfigManager 单例或创建新实例。"""
    if ConfigManager._instance is not None:
        return ConfigManager._instance
    return ConfigManager(config_path=config_path)


def init_config_manager(eventEmitter=None):
    """初始化并返回 ConfigManager 实例（兼容旧接口）。"""
    mgr = get_config_manager()
    return mgr
