"""Tool 実装から CybermailClient を組み立てるための小さなヘルパー。"""

from typing import Any

from utils.client import CybermailClient


def create_client(tool: Any) -> CybermailClient:
    """Tool のランタイム情報からクライアントを生成する。

    セッションキャッシュ用の KV ストアはランタイムによって存在しないことがあるため、
    取得できない場合は None（＝毎回ログイン）にフォールバックする。
    """
    storage = getattr(getattr(tool, "session", None), "storage", None)
    return CybermailClient(tool.runtime.credentials, storage=storage)


def get_str(parameters: dict[str, Any], name: str, default: str = "") -> str:
    value = parameters.get(name)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def get_int(parameters: dict[str, Any], name: str) -> int | None:
    value = parameters.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} には数値を指定してください: {value!r}") from None


def get_bool(parameters: dict[str, Any], name: str) -> bool:
    value = parameters.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)
